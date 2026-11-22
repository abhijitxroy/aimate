"""Workspace hierarchy, bounded recall and local cost accounting."""
import json
import asyncio
import tempfile
import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from test_app import create_app, fixture_config
from app.memory import context, recall, save_record
from app.store import Store
from app.usage import record, report
from app.agent import run_turn


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.save_config(fixture_config())
        self.client = TestClient(create_app(self.store))
        self.headers = {"X-CSRF-Token": self.client.post("/api/login", json={"password": self.store.password}).json()["csrf"]}
        self.cid = self.store.new_conversation("Build investigation")
        self.store.save_turn(self.cid, [
            {"role": "user", "content": "Investigate Jenkins build eleven"},
            {"role": "assistant", "content": [{"type": "text", "text": "Build eleven skipped GPU validation."},
                                            {"type": "tool_use", "name": "api_read", "input": {"path": "/internal"}}]},
            {"role": "user", "content": [{"type": "tool_result", "content": "SECRET INTERNAL TOOL BODY"}]}])

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.temp.cleanup()

    def post(self, path, body=None):
        return self.client.post(path, headers=self.headers, json=body)

    def test_nested_groups_move_preserves_messages_pin_and_restart(self):
        project = self.post("/api/groups", {"name": "Demo", "kind": "project"}).json()["id"]
        module = self.post("/api/groups", {"name": "CI", "kind": "module", "parent": project}).json()["id"]
        group = self.post("/api/groups", {"name": "Logs", "parent": module}).json()["id"]
        before = self.store.history(self.cid)
        response = self.client.patch(f"/api/conversations/{self.cid}", headers=self.headers,
                                     json={"group_id": group, "pinned": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.history(self.cid), before)
        reopened = Store(self.temp.name)
        self.assertEqual(reopened.conversation_group(self.cid), group)
        self.assertEqual(reopened.rows("SELECT pinned FROM conversation_flags")[0]["pinned"], 1)
        reopened.db.close()
        self.assertEqual(self.client.delete(f"/api/groups/{group}", headers=self.headers).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/conversations/{self.cid}", headers=self.headers,
                                         json={"group_id": None}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/groups/{group}", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/groups/{project}", headers=self.headers).status_code, 409)
        self.assertEqual(self.post("/api/groups", {"name": "demo"}).status_code, 400)
        self.assertEqual(self.post("/api/groups", {"name": "Bad", "kind": []}).status_code, 400)

    def test_continue_has_reference_without_copying_history_and_recall_is_bounded(self):
        child = self.post(f"/api/conversations/{self.cid}/continue").json()["id"]
        self.assertEqual(self.store.history(child), [])
        handoff = context(self.store, child)
        self.assertIn("Build eleven skipped", handoff)
        self.assertNotIn("SECRET INTERNAL", handoff)
        self.assertIn(self.cid, handoff)
        self.assertIn(self.cid, json.dumps(recall(self.store, child, "search_knowledge", {"query": "GPU validation"})))
        for i in range(5):
            self.store.save_turn(self.cid, [{"role": "user", "content": "large " * 4000}])
        output = recall(self.store, child, "read_past_conversation", {"conversation_id": self.cid})
        self.assertLessEqual(sum(len(t["text"]) for t in output["turns"]), 12000)
        self.assertTrue(output["next_before_turn"])
        self.client.delete(f"/api/conversations/{self.cid}", headers=self.headers)
        self.assertEqual(context(self.store, child), "")
        self.assertEqual(self.store.rows("SELECT * FROM memory_index WHERE conversation=?", (self.cid,)), [])

    def test_dictionary_unique_keys_scopes_and_secret_redaction(self):
        group = self.store.create_group("Project")
        first = self.post("/api/knowledge", {"key": "build", "value": "GPU build eleven github-private-token"}).json()["id"]
        self.assertEqual(self.post("/api/knowledge", {"key": "BUILD", "value": "Duplicate"}).status_code, 400)
        self.assertEqual(self.post("/api/knowledge", {"key": "build", "value": "Scoped", "group_id": group}).status_code, 200)
        found = recall(self.store, self.cid, "search_knowledge", {"query": "GPU"})
        self.assertIn("[redacted]", json.dumps(found))
        self.assertNotIn("github-private-token", json.dumps(found))
        self.assertEqual(self.client.patch(f"/api/knowledge/{first}", headers=self.headers,
                                          json={"key": "build", "value": "Updated"}).status_code, 200)
        self.assertEqual(self.client.get("/api/knowledge").json()["records"][0]["value"], "Updated")
        self.assertEqual(self.client.delete(f"/api/knowledge/{first}", headers=self.headers).status_code, 200)
        self.assertEqual(self.post("/api/knowledge", {"key": "Invalid", "value": "x", "group_id": "missing"}).status_code, 400)
        self.assertEqual(self.client.post("/api/knowledge", json={"key": "x", "value": "y"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/groups/{group}", headers=self.headers).status_code, 409)

    def test_ledger_model_day_rates_cache_and_chat_deletion(self):
        config = fixture_config()
        record(self.store, config, "alpha", {"input_tokens": 1000, "output_tokens": 200,
                                            "cache_read_input_tokens": 500})
        record(self.store, config, "beta", {"input_tokens": 2000, "output_tokens": 400}, "Auto routing")
        self.assertEqual(self.post("/api/usage/rates", {"model": "alpha", "input": 2, "output": 10,
                                                      "cache_read": .2, "cache_write": 3}).status_code, 200)
        usage = self.client.get("/api/usage?days=7&offset=330").json()
        self.assertEqual(usage["totals"]["requests"], 2)
        self.assertEqual(len(usage["daily"]), 1)
        self.assertEqual(len(usage["models"]), 2)
        self.assertAlmostEqual(usage["totals"]["estimated_usd"], .0041)
        self.assertEqual(usage["totals"]["unpriced_requests"], 1)
        self.client.delete(f"/api/conversations/{self.cid}", headers=self.headers)
        self.assertEqual(report(self.store)["totals"]["requests"], 2)
        self.assertEqual(self.client.get("/api/usage?days=0").status_code, 400)
        self.assertEqual(self.post("/api/usage/rates", {"model": "alpha", "input": -2,
                                                      "output": 1, "cache_read": 1, "cache_write": 1}).status_code, 400)
        config["ai"]["provider"] = "chatgpt"
        record(self.store, config, "alpha", {"input_tokens": 1000, "output_tokens": 100,
                                           "input_tokens_details": {"cached_tokens": 700}})
        usage = report(self.store)
        self.assertEqual(usage["totals"]["cache_read_input_tokens"], 1200)
        self.assertEqual(usage["totals"]["unpriced_requests"], 2)

    def test_agent_recalls_previous_chat_without_service_calls(self):
        child = self.post(f"/api/conversations/{self.cid}/continue").json()["id"]
        requests = []
        class Block:
            def __init__(self, **value):
                self.value = value
            def model_dump(self, **kwargs):
                return self.value
        class Stream:
            def __init__(self, first):
                self.first = first
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            @property
            def text_stream(self):
                async def stream():
                    if not self.first:
                        yield "The prior build skipped GPU validation."
                return stream()
            async def get_final_message(self):
                blocks = [Block(type="tool_use", id="recall", name="search_knowledge", input={"query": "GPU"})] if self.first else [
                    Block(type="text", text="The prior build skipped GPU validation.")]
                return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=100, output_tokens=20))
        class AI:
            def __init__(self):
                self.messages = self
            def stream(self, **params):
                requests.append(json.loads(json.dumps(params)))
                return Stream(len(requests) == 1)
            async def close(self):
                pass
        async def run():
            return [event async for event in run_turn(self.store, child, "Continue the investigation",
                                                      client_factory=lambda cfg: AI(), services_factory=lambda cfg: None)]
        events = asyncio.run(run())
        self.assertIn("Build eleven skipped", requests[0]["system"])
        self.assertNotIn("SECRET INTERNAL", requests[0]["system"])
        self.assertEqual(events[-1]["usage"]["input_tokens"], 200)
        self.assertEqual(report(self.store)["totals"]["requests"], 2)
        self.assertIn("Build eleven skipped", json.dumps(requests[1]["messages"]))
