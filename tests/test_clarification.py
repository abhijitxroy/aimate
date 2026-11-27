import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.agent import run_turn, responses_history
from app.clarification import request
from test_app import FakeAI, FakeBlock, FakeStream, Store, fixture_config


class ClarificationTests(unittest.TestCase):
    def test_invalid_questions_pause_and_disabled_feature_does_not_intercept(self):
        value = request([{"name": "ask_user", "input": {"question": "", "kind": "single"}}])
        self.assertEqual(value["status"], "awaiting_input")
        self.assertEqual(value["options"], [])
        value = request([{"name": "ask_user", "input": {
            "question": "Should I include closed tickets?", "kind": "yes_no"}}])
        self.assertEqual(value["options"], ["Yes", "No"])
        with patch.dict(os.environ, {"AIMATE_CLARIFICATION_ENABLED": "0"}):
            self.assertIsNone(request([{"name": "ask_user", "input": {}}]))

    def test_native_clarification_blocks_entire_mixed_batch_and_retains_context(self):
        class ClarifyStream(FakeStream):
            async def get_final_message(self):
                return SimpleNamespace(content=[
                    FakeBlock(type="tool_use", id="read", name="api_read",
                              input={"service": "jira", "path": "/rest/api/2/search"}),
                    FakeBlock(type="tool_use", id="ask", name="ask_user", input={
                        "question": "Which ticket should I check?", "kind": "single",
                        "options": ["DEMO-1", "DEMO-2"]}),
                    FakeBlock(type="tool_use", id="write", name="propose_action", input={}),
                ], usage=SimpleNamespace(input_tokens=10, output_tokens=12))
        seen = []
        class Client(FakeAI):
            def stream(self, **kwargs):
                seen.append(kwargs)
                return ClarifyStream(0)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder); store.save_config(fixture_config()); cid = store.new_conversation()
            prefetch = AsyncMock(side_effect=AssertionError("No lookup permitted"))
            async def run():
                return [event async for event in run_turn(store, cid, "Check the ticket",
                    client_factory=Client, services_factory=lambda _: None, model_mode="standard")]
            with patch("app.agent.prefetch_reads", prefetch):
                events = asyncio.run(run())
            prefetch.assert_not_awaited()
            self.assertFalse(any(event["event"] in {"tool", "source", "action"} for event in events))
            self.assertEqual(events[-1]["completion"]["status"], "awaiting_input")
            self.assertIn("CLARIFY BEFORE FETCHING", seen[0]["system"])
            saved = store.history(cid)
            self.assertIn("Which ticket", json.dumps(saved))
            results = [block for msg in saved if isinstance(msg["content"], list)
                       for block in msg["content"] if block["type"] == "tool_result"]
            self.assertEqual({block["tool_use_id"] for block in results}, {"read", "ask", "write"})
            self.assertEqual(store.rows("SELECT count(*) n FROM actions")[0]["n"], 0)
            store.db.close()

    def test_responses_clarification_has_no_reads_and_paired_continuation(self):
        from app.bedrock_gpt import Connection, PROVIDER, DEFAULT_MODEL
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder); config = fixture_config()
            config["ai"] = {"provider": PROVIDER, "model": DEFAULT_MODEL, "region": "us-east-2",
                            "api_key": "synthetic-fixture", "bedrock_mode": "advanced"}
            store.save_config(config); cid = store.new_conversation(); payloads = []
            def remote(req):
                payloads.append(json.loads(req.content))
                output = [{"type": "function_call", "call_id": "read", "name": "api_read",
                           "namespace": "project", "arguments": '{"service":"jira","path":"/rest/api/2/search"}'},
                          {"type": "function_call", "call_id": "ask", "name": "ask_user",
                           "namespace": "project", "arguments": json.dumps({
                               "question": "What scope should I use?", "kind": "multiple",
                               "options": ["Current sprint", "Older failures"]})}]
                result = {"type": "response.completed", "response": {"model": DEFAULT_MODEL,
                          "output": output, "usage": {"input_tokens": 10, "output_tokens": 12}}}
                return httpx.Response(200, text="data: " + json.dumps(result) + "\n\n",
                                      headers={"content-type": "text/event-stream"})
            async def run():
                return [event async for event in run_turn(store, cid, "Check failures",
                    services_factory=lambda _: None, model_mode="standard")]
            prefetch = AsyncMock(side_effect=AssertionError("No lookup permitted"))
            with patch("app.bedrock_gpt.Connection", side_effect=lambda config, store=None:
                       Connection(config, store, httpx.MockTransport(remote))), patch("app.agent.prefetch_reads", prefetch):
                events = asyncio.run(run())
            prefetch.assert_not_awaited()
            self.assertEqual(len(payloads), 1)
            self.assertEqual(events[-1]["completion"]["kind"], "multiple")
            self.assertIn("CLARIFY BEFORE FETCHING", payloads[0]["instructions"])
            items = responses_history(store.history(cid), PROVIDER)
            self.assertEqual({i["call_id"] for i in items if i.get("type") == "function_call_output"}, {"read", "ask"})
            store.db.close()

    def test_disabled_policy_keeps_normal_chat_and_tool_list(self):
        seen = []
        class Client(FakeAI):
            def __init__(self, config):
                super().__init__(config); self.stage = 2
            def stream(self, **kwargs):
                seen.append(kwargs); return super().stream(**kwargs)
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder); store.save_config(fixture_config()); cid = store.new_conversation()
            async def run():
                return [event async for event in run_turn(store, cid, "Hello",
                    client_factory=Client, services_factory=lambda _: None, model_mode="standard")]
            with patch.dict(os.environ, {"AIMATE_CLARIFICATION_ENABLED": "0"}):
                asyncio.run(run())
            self.assertNotIn("CLARIFY BEFORE FETCHING", seen[0]["system"])
            self.assertNotIn("ask_user", [t["name"] for t in seen[0]["tools"]])
            store.db.close()
