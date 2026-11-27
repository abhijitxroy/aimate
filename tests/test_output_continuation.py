"""Bounded output recovery: synthetic providers, no live reads or AI billing."""
import asyncio
import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from app.agent import run_turn, _run_chatgpt_turn
from app.output_continuation import budget, retries, output_limited, normalize_event, persisted
from app.opencode_responses import Stream as ResponsesStream
from app.opencode_bedrock import message as gateway_message, ChatStream
from app.gemini_vertex import message as vertex_message
from test_app import FakeAI, FakeBlock, Store, fixture_config
from test_investigation_completion import Stream


class OutputContinuationTests(unittest.TestCase):
    def test_budget_and_detection_preserve_safe_fallbacks(self):
        self.assertEqual(budget("us.anthropic.claude-opus-5-5", "design"), 16384)
        self.assertEqual(budget("us.anthropic.claude-opus-5-5", "review", 1), 32768)
        self.assertEqual(budget("claude-3-5-sonnet-20241022", "review", 2), 8192)
        self.assertEqual(budget("claude-3-haiku-20240307", "review", 2), 4096)
        self.assertEqual(budget("unknown-model", "design", 2), 4096)
        self.assertEqual(budget("us.openai.gpt-6.2-sol", "analysis"), 16384)
        self.assertEqual(retries({"_local_ai": True}), 0)
        with patch.dict(os.environ, {"AIMATE_OUTPUT_CONTINUATION_ENABLED": "0"}):
            self.assertEqual(retries({}), 0)
            self.assertEqual(budget("claude-opus-5-5", "review"), 4096)
        limited = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
        self.assertTrue(output_limited(limited))
        event = {"type": "response.incomplete", "response": limited}
        self.assertEqual(normalize_event(event)["type"], "response.completed")
        self.assertEqual(normalize_event(event)["response"]["status"], "incomplete")
        for value in (None, {}, {"status": "incomplete", "incomplete_details": None},
                      {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}}):
            self.assertFalse(output_limited(value))
        user={"role":"user","content":"identical"};internal={"role":"user","content":"identical"}
        self.assertEqual(persisted([user,internal],{id(internal)}),[user])

    def native(self, exhausted=False, disabled=False, revoked=False):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory); config = fixture_config()
            config["ai"]["model"] = "us.anthropic.claude-opus-5-5"
            store.save_config(config); cid = store.new_conversation()
            requests, reads = [], []
            class Services:
                async def read(self, service, path, query):
                    reads.append(path)
                    return {"source": "https://fixture.example/evidence", "data": {"finding": "synthetic"}}
            class Answer(FakeAI):
                def stream(self, **kwargs):
                    requests.append(copy.deepcopy(kwargs))
                    if self.stage == 0 and not exhausted:
                        self.stage += 1
                        return Stream([FakeBlock(type="tool_use", id="read-1", name="api_read",
                            input={"service": "github", "path": "/fixture"})])
                    self.stage += 1
                    if exhausted or self.stage == 2:
                        return Stream([FakeBlock(type="text", text="Preparing the design."),
                            FakeBlock(type="tool_use", id="partial-" + str(self.stage),
                            name="propose_action", input={})], "Preparing the design.", "max_tokens")
                    return Stream([FakeBlock(type="text", text="Final design: A → B.")],
                                  "Final design: A → B.")
                async def create(self, **kwargs):
                    requests.append(copy.deepcopy(kwargs))
                    return SimpleNamespace(content=[SimpleNamespace(type="text", text="Concise supported findings.")],
                        usage=SimpleNamespace(input_tokens=10, output_tokens=2), stop_reason="end_turn")
            denied = False
            def check():
                if denied:
                    raise ValueError("Access revoked")
            async def run():
                nonlocal denied
                events = []
                async for event in run_turn(store, cid, "Show the design and architecture",
                        client_factory=Answer, services_factory=lambda _: Services(),
                        model_mode="standard", access_check=check):
                    events.append(event)
                    if revoked and event["event"] == "continuation":
                        denied = True
                return events
            with patch.dict(os.environ, {"AIMATE_OUTPUT_CONTINUATION_ENABLED": "0" if disabled else "1",
                                        "AIMATE_FINAL_SYNTHESIS_ENABLED": "0" if disabled else "1"}):
                if revoked:
                    with self.assertRaisesRegex(ValueError, "Access revoked"):
                        asyncio.run(run())
                    self.assertEqual(len(requests), 2)
                    self.assertFalse(store.rows("SELECT * FROM turns"))
                    store.db.close()
                    return
                events = asyncio.run(run())
            self.assertFalse(store.rows("SELECT * FROM actions"))
            self.assertEqual(len(store.rows("SELECT * FROM turns")), 1)
            self.assertEqual(sum(m["role"]=="user" and isinstance(m["content"],str)
                                 for m in store.history(cid)),1)
            metadata = json.loads(store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
            store.db.close()
            return events, requests, reads, metadata

    def test_native_finishes_without_repeating_reads_or_partial_actions(self):
        events, requests, reads, metadata = self.native()
        self.assertEqual(reads, ["/fixture"])
        self.assertEqual([r["max_tokens"] for r in requests], [16384, 16384, 32768])
        self.assertEqual(sum(e["event"] == "continuation" for e in events), 1)
        self.assertIn("Final design", "".join(e.get("delta", "") for e in events))
        self.assertNotIn("completion", events[-1])
        self.assertEqual(metadata["output_retries"], 1)
        self.assertEqual(events[-1]["usage"], {"input_tokens": 30, "output_tokens": 6})
        self.assertIn("Not executed", json.dumps(requests[-1]["messages"]))

    def test_native_exhaustion_synthesizes_final_findings_and_disabled_mode_is_bounded(self):
        events, requests, reads, _ = self.native(exhausted=True)
        self.assertEqual(len(requests), 4)  # three responses, one tool-free synthesis
        self.assertNotIn("tools", requests[-1])
        self.assertEqual(events[-1]["completion"]["reason"], "final_answer_recovered")
        self.assertIn("Concise supported findings.", "".join(e.get("delta", "") for e in events))
        self.assertNotIn("Ask Continue", "".join(e.get("delta", "") for e in events))
        self.assertEqual(reads, [])
        events, requests, _, _ = self.native(exhausted=True, disabled=True)
        self.assertEqual(len(requests), 1)
        self.assertEqual(events[-1]["completion"]["reason"], "output_limit")

    def test_revoked_access_blocks_automatic_continuation_and_save(self):
        self.native(revoked=True)

    def test_responses_pairs_truncated_calls_and_finishes_in_the_same_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory); store.save_config(fixture_config()); cid = store.new_conversation()
            requests = []
            class Connection:
                def status(self): return {"active": "synthetic"}
                async def models(self): return [{"slug": "test-model"}]
            async def response_events(connection, payload, **kwargs):
                requests.append(copy.deepcopy(payload))
                if len(requests) == 1:
                    yield {"type": "response.output_text.delta", "delta": "Preparing."}
                    result = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                        "output": [{"type": "function_call", "name": "propose_action",
                                    "call_id": "truncated-1", "arguments": '{"service":'}]}
                else:
                    yield {"type": "response.output_text.delta", "delta": "Final diagram."}
                    result = {"status": "completed", "output": []}
                result.update(model="test-model", usage={"input_tokens": 10, "output_tokens": 2})
                yield {"type": "response.completed", "response": result}
            async def run():
                return [e async for e in _run_chatgpt_turn(store, cid, "Show the design",
                    Connection(), lambda _: None, model_mode="standard")]
            with patch("app.chatgpt.response_events", response_events):
                events = asyncio.run(run())
            self.assertEqual(len(requests), 2)
            self.assertNotIn("max_output_tokens", requests[0])  # account endpoint contract
            paired = next(i for i in requests[1]["input"] if i.get("type") == "function_call_output")
            self.assertEqual(paired["call_id"], "truncated-1")
            self.assertIn("Not executed", paired["output"])
            self.assertIn("\n\nFinal diagram.", "".join(e.get("delta", "") for e in events))
            self.assertNotIn("completion", events[-1])
            self.assertEqual(events[-1]["output_retries"], 1)
            self.assertFalse(store.rows("SELECT * FROM actions"))
            self.assertEqual(len(store.rows("SELECT * FROM turns")), 1)
            self.assertEqual(sum(m["role"]=="user" and isinstance(m["content"],str)
                                 for m in store.history(cid)),1)
            store.db.close()

    def test_gateway_and_vertex_preserve_output_exhaustion_without_running_partial_calls(self):
        limited = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "function_call", "name": "propose_action", "call_id": "cut",
                        "arguments": '{"service":'}], "usage": {"input_tokens": 10, "output_tokens": 2}}
        event = {"type": "response.incomplete", "response": limited}
        async def run():
            response = httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")
            stream = ResponsesStream(response, "us.openai.gpt-6.2-sol", gateway_message)
            async for _ in stream.text_stream: pass
            reply = await stream.get_final_message()
            self.assertEqual(reply.stop_reason, "max_tokens")
            self.assertEqual(reply.content[0].input, {})
            self.assertEqual(reply.usage.output_tokens, 2)
            packet = {"choices": [{"delta": {"content": "Partial"}, "finish_reason": "length"}]}
            stream = ChatStream(httpx.Response(200, text="data: " + json.dumps(packet) + "\n\n"), "glm-test")
            async for _ in stream.text_stream: pass
            self.assertEqual((await stream.get_final_message()).stop_reason, "max_tokens")
        asyncio.run(run())
        self.assertEqual(vertex_message("gemini-test", [], {}, "MAX_TOKENS").stop_reason, "max_tokens")

