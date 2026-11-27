"""Bedrock GPT wire, persistence and permission checks; no paid/external calls."""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from app.bedrock_gpt import Connection, DEFAULT_MODEL, PROVIDER
from app.agent import ai_client, responses_history, run_turn
from app.store import Store
from app.validation import validate_config
from test_app import create_app, fixture_config


class BedrockGPTTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.config = fixture_config()
        self.config["ai"] = {"provider": PROVIDER, "model": DEFAULT_MODEL,
                             "region": "us-east-2", "api_key": "synthetic-bedrock-token",
                             "bedrock_mode": "advanced"}
        self.store.save_config(self.config)
        self.requests, self.mode = [], "answer"
        self.transport = httpx.MockTransport(self.handle)

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def handle(self, request):
        self.requests.append(request)
        self.assertEqual(request.url.host, "bedrock-runtime.us-east-2.amazonaws.com")
        self.assertEqual(request.url.path, "/openai/v1/responses")
        self.assertEqual(request.headers["authorization"], "Bearer synthetic-bedrock-token")
        payload = json.loads(request.content)
        self.assertNotIn("synthetic-bedrock-token", json.dumps(payload))
        self.assertFalse(payload["store"])
        if self.mode == "denied":
            return httpx.Response(403, json={"error": "synthetic-bedrock-token must never appear in diagnostics"})
        text = "GPT answered."
        output = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]
        if not payload["stream"]:
            return httpx.Response(200, json={"status": "completed", "model": payload["model"],
                "output": output, "usage": {"input_tokens": 12, "output_tokens": 3}})
        self.assertTrue(all(tool["type"] == "function" for tool in payload.get("tools", [])))
        events = [{"type": "response.output_text.delta", "delta": text}]
        if payload.get("instructions", "").startswith("Classify an engineering"):
            self.assertNotIn("tools", payload)
            events = [{"type": "response.output_text.delta", "delta": '{"route":"analysis"}'}]
        elif self.mode == "proposal" and len(self.requests) == 1:
            events = []
            output = [{"type": "function_call", "call_id": "proposal1", "name": "propose_action",
                       "arguments": json.dumps({"service": "github", "operation": "create_issue",
                           "payload": {"repo": "team/repo", "title": "Review build"}, "reason": "User requested"})}]
        elif self.mode == "read" and len(self.requests) == 1:
            events = []
            output = [{"type": "function_call", "call_id": "read1", "name": "api_read",
                       "arguments": json.dumps({"service": "github", "path": "/repos/team/repo/pulls/1"})}]
        if self.mode == "changed":
            config = self.store.config()
            config["ai"]["api_key"] = "replacement-token"
            self.store.save_config(config)
        if self.mode != "interrupted":
            limited = self.mode == "length" and len(self.requests) == 1
            events.append({"type": "response.incomplete" if limited else "response.completed", "response": {
                           **({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}} if limited else {}),
                           "model": payload["model"], "output": output,
                           "usage": {"input_tokens": 12, "output_tokens": 3,
                                     "input_tokens_details": {"cached_tokens": 4}}}})
        return httpx.Response(200, text="".join("data: " + json.dumps(event) + "\n\n" for event in events),
                              headers={"content-type": "text/event-stream"})

    def turn(self, role="admin", mode="standard"):
        cid = self.store.new_conversation()
        class Services:
            def __init__(self, config): pass
            async def read(self, service, path, params=None):
                return {"source": "https://api.github.com" + path,
                        "data": {"title": "Synthetic reviewed PR", "state": "open"}}
            async def prepare(self, service, operation, payload):
                return {"method": "POST", "path": "/repos/team/repo/issues", "body": payload}
            async def execute(self, plan):
                raise AssertionError("An unconfirmed change was executed")
        with patch("app.bedrock_gpt.Connection", side_effect=lambda config, store=None:
                   Connection(config, store, self.transport)):
            async def run():
                return [event async for event in run_turn(self.store, cid, "Review my project",
                    services_factory=Services, role=role, model_mode=mode)]
            return cid, asyncio.run(run())

    def test_stream_routes_only_to_bedrock_and_records_tokens_and_history(self):
        cid, events = self.turn()
        self.assertEqual(events[-1]["event"], "done")
        self.assertEqual(events[-1]["model"], DEFAULT_MODEL)
        self.assertEqual(events[-1]["usage"], {"input_tokens": 12, "output_tokens": 3})
        self.assertTrue(self.store.history(cid))
        row = self.store.rows("SELECT provider,model,tokens FROM usage_events")[0]
        self.assertEqual((row["provider"], row["model"]), (PROVIDER, DEFAULT_MODEL))
        self.assertEqual(json.loads(row["tokens"])["cache_read_input_tokens"], 4)
        self.assertNotIn("synthetic-bedrock-token", json.dumps(events))

    def test_read_tool_returns_evidence_to_the_same_bedrock_loop(self):
        self.mode = "read"
        _, events = self.turn()
        self.assertTrue(any(event["event"] == "source" for event in events))
        self.assertEqual(len(self.requests), 2)
        continuation = json.loads(self.requests[1].content)["input"]
        evidence = next(item for item in continuation if item.get("type") == "function_call_output")
        self.assertEqual(evidence["call_id"], "read1")
        self.assertIn("Synthetic reviewed PR", evidence["output"])
        self.assertFalse(self.store.rows("SELECT * FROM actions"))

    def test_wire_output_limit_continues_without_another_user_request(self):
        self.mode = "length"
        _, events = self.turn()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual([json.loads(r.content)["max_output_tokens"] for r in self.requests], [16384, 32768])
        self.assertEqual(events[-1]["output_retries"], 1)
        self.assertNotIn("completion", events[-1])
        self.assertEqual(events[-1]["usage"]["input_tokens"], 24)
        self.assertEqual(len(self.store.rows("SELECT * FROM turns")), 1)

    def test_reviewed_proposal_stays_pending_and_viewer_has_no_write_tool(self):
        self.mode = "proposal"
        _, events = self.turn()
        card = next(event["action"] for event in events if event["event"] == "action")
        self.assertEqual(self.store.action(card["id"])["status"], "pending")
        self.requests.clear()
        self.mode = "answer"
        self.turn(role="viewer")
        names = {tool["name"] for tool in json.loads(self.requests[0].content)["tools"]}
        self.assertNotIn("propose_action", names)
        self.assertIn("api_read", names)

    def test_auto_and_manual_analysis_keep_the_configured_profile(self):
        config = self.store.config()
        config["ai"]["analysis_model"] = "us.openai.gpt-6.1-sol"
        self.store.save_config(config)
        _, events = self.turn(mode="auto")
        self.assertEqual([json.loads(request.content)["model"] for request in self.requests],
                         [DEFAULT_MODEL, "us.openai.gpt-6.1-sol"])
        self.assertEqual(events[-1]["usage"]["input_tokens"], 24)
        self.requests.clear()
        _, events = self.turn(mode="analysis")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(events[-1]["model"], "us.openai.gpt-6.1-sol")

    def test_changed_key_or_incomplete_stream_is_not_saved(self):
        for mode in ("interrupted", "changed"):
            self.mode = mode
            self.store.save_config(self.config)
            before = len(self.store.rows("SELECT * FROM turns"))
            with self.assertRaisesRegex(ValueError, "completion|connection changed"):
                self.turn()
            self.assertEqual(len(self.store.rows("SELECT * FROM turns")), before)

    def test_auth_error_is_sanitized(self):
        self.mode = "denied"
        with self.assertRaises(ValueError) as error:
            asyncio.run(Connection(self.config, transport=self.transport).create(
                model=DEFAULT_MODEL, max_tokens=16, messages=[{"role": "user", "content": "Reply OK."}]))
        self.assertIn("access denied", str(error.exception))
        self.assertNotIn("synthetic-bedrock-token", str(error.exception))

    def test_settings_reuse_only_bedrock_keys_and_reject_retired_profiles(self):
        raw = {**self.config, "ai": {"provider": PROVIDER, "bedrock_mode": "simple",
                                    "model": "global.openai.gpt-6-luna"}}
        old = {"ai": {"provider": "bedrock", "api_key": "saved-bedrock-key"}}
        config = validate_config(raw, old)
        self.assertEqual(config["ai"]["api_key"], "saved-bedrock-key")
        self.assertEqual(config["ai"]["model"], "global.openai.gpt-6-luna")
        self.assertEqual(config["ai"]["region"], "us-east-2")
        self.assertFalse(validate_config(raw, {"ai": {"provider": "anthropic", "api_key": "other-key"}})["ai"]["api_key"])
        for model in ("us.openai.gpt-5.6-sol", "global.openai.gpt-5.6-luna"):
            with self.assertRaisesRegex(ValueError, "retired"):
                validate_config({**raw, "ai": {**raw["ai"], "model": model}}, old)
        client = ai_client(self.config)
        self.assertIsInstance(client, Connection)

    def test_disabled_feature_keeps_existing_provider_and_catalog_auth_intact(self):
        with patch.dict(os.environ, {"AIMATE_BEDROCK_GPT_ENABLED": "0"}):
            with self.assertRaisesRegex(ValueError, "disabled"):
                validate_config(self.config, {})
            self.assertEqual(validate_config(fixture_config(), {})["ai"]["provider"], "anthropic")
            with TestClient(create_app(self.store, demo=False)) as client:
                self.assertEqual(client.get("/api/bedrock/gpt/models").status_code, 401)
                client.post("/api/login", json={"password": self.store.password})
                response = client.get("/api/bedrock/gpt/models").json()
                self.assertFalse(response["enabled"])
                self.assertEqual(response["models"], [])

    def test_http_connection_check_is_metered_and_never_returns_a_key(self):
        with patch("app.bedrock_gpt.Connection", side_effect=lambda config, store=None:
                   Connection(config, store, self.transport)):
            with TestClient(create_app(self.store, demo=False)) as client:
                auth = client.post("/api/login", json={"password": self.store.password}).json()
                response = client.post("/api/connections/ai/test", headers={"X-CSRF-Token": auth["csrf"]})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["ok"])
                self.assertNotIn("synthetic-bedrock-token", response.text)
                self.assertTrue(self.store.rows("SELECT * FROM usage_events"))

    def test_foreign_reasoning_is_not_sent_and_tool_envelopes_are_flattened(self):
        messages = [{"role": "assistant", "content": [{"type": "responses", "items": [
            {"type": "reasoning", "encrypted_content": "foreign-private-blob"},
            {"type": "message", "id": "foreign-id", "role": "assistant", "content": []}]}]}]
        packed = responses_history(messages, PROVIDER)
        self.assertNotIn("foreign", json.dumps(packed))
        payload = {"tools": [{"type": "namespace", "name": "project", "tools": [
            {"type": "function", "name": "api_read"}]}],
            "input": [{"type": "function_call", "namespace": "project", "name": "api_read"}]}
        changed = Connection.prepare(payload)
        self.assertEqual(changed["tools"][0]["type"], "function")
        self.assertNotIn("namespace", changed["input"][0])
        self.assertIn("namespace", payload["input"][0])
