"""Budget checkpoints use synthetic evidence, never live services."""
import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent import run_turn, _run_chatgpt_turn
from app.answer_quality import Assessment
from app.investigation_completion import reason, checkpoint
from test_app import FakeAI, FakeBlock, Store, fixture_config


class Stream:
    def __init__(self, blocks, text="", stop=None):
        self.blocks, self.text, self.stop = blocks, text, stop
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    @property
    def text_stream(self):
        async def chunks():
            if self.text:
                yield self.text
        return chunks()
    async def get_final_message(self):
        return SimpleNamespace(content=self.blocks, stop_reason=self.stop,
                               usage=SimpleNamespace(input_tokens=10, output_tokens=2))


class CompletionTests(unittest.TestCase):
    def test_gate_does_not_certify_accuracy_and_can_be_disabled(self):
        self.assertEqual(reason(8, [{}]), "tool_limit")
        self.assertEqual(reason(0, [], "max_tokens"), "output_limit")
        self.assertEqual(reason(0, [], final_text=False), "empty_answer")
        self.assertIsNone(reason(8, [], final_text=True))
        quality = Assessment("analysis")
        quality.value = {"coverage": "complete", "gaps": [], "confidence": "high"}
        state, metadata = checkpoint("tool_limit", quality)
        self.assertEqual(state["status"], "incomplete")
        self.assertEqual(metadata["coverage"], "partial")
        self.assertFalse(metadata["assessed"])
        self.assertIsNone(metadata["completion_percent"])
        self.assertEqual(quality.value["coverage"], "complete")
        with patch.dict(os.environ, {"AIMATE_COMPLETION_CHECKPOINT_ENABLED": "0"}):
            self.assertIsNone(reason(8, [{}], "max_tokens", False))

    def test_native_budget_saves_paired_checkpoint_skips_last_proposal_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            cid = store.new_conversation()
            reads, params = [], []
            class Services:
                async def read(self, service, path, query):
                    reads.append(path)
                    return {"source": "https://fixture.example" + path, "data": {"evidence": "synthetic"}}
            class Endless(FakeAI):
                def stream(self, **kwargs):
                    params.append(kwargs)
                    current = self.stage
                    self.stage += 1
                    call = {"type": "tool_use", "id": "call-" + str(current),
                            "name": "api_read" if current < 8 else "propose_action",
                            "input": {"service": "github", "path": "/fixture/" + str(current)}}
                    return Stream([FakeBlock(**call)])
            async def run():
                return [event async for event in run_turn(store, cid, "Investigate synthetic evidence",
                    client_factory=Endless, services_factory=lambda _: Services(), model_mode="standard")]
            events = asyncio.run(run())
            self.assertEqual(len(reads), 8)
            self.assertEqual(params[-1]["tool_choice"], {"type": "none"})
            self.assertEqual(events[-1]["completion"]["reason"], "tool_limit")
            self.assertEqual(store.rows("SELECT count(*) n FROM actions")[0]["n"], 0)
            history = store.history(cid)
            self.assertEqual(history[-2]["content"][0]["tool_use_id"], "call-8")
            self.assertTrue(history[-2]["content"][0]["is_error"])
            store.db.close()
            store = Store(directory)
            metadata = json.loads(store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
            self.assertEqual(metadata["completion"]["status"], "incomplete")
            self.assertIn("incomplete", store.history(cid)[-1]["content"])
            class Continued(FakeAI):
                def stream(self, **kwargs):
                    self.assertion = kwargs["messages"]
                    return Stream([FakeBlock(type="text", text="Continued from evidence.")], "Continued from evidence.")
            async def resume():
                return [event async for event in run_turn(store, cid, "Continue", client_factory=Continued,
                    services_factory=lambda _: Services(), model_mode="standard")]
            self.assertNotIn("completion", asyncio.run(resume())[-1])
            self.assertEqual(len(reads), 8)
            self.assertEqual(store.rows("SELECT count(*) n FROM turns")[0]["n"], 2)
            store.db.close()

    def test_native_truncated_output_and_empty_answer_are_saved_as_incomplete(self):
        for stop, text, expected in (("max_tokens", "Partial finding", "output_limit"), (None, "", "empty_answer")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                store = Store(directory)
                store.save_config(fixture_config())
                cid = store.new_conversation()
                class Answer(FakeAI):
                    def stream(self, **kwargs):
                        return Stream([FakeBlock(type="text", text=text)], text, stop)
                async def run():
                    return [event async for event in run_turn(store, cid, "Review synthetic input",
                        client_factory=Answer, services_factory=lambda _: None, model_mode="standard")]
                events = asyncio.run(run())
                self.assertEqual(events[-1]["completion"]["reason"], expected)
                self.assertEqual(store.rows("SELECT count(*) n FROM turns")[0]["n"], 1)
                store.db.close()

    def test_private_checkpoint_stays_in_memory_and_revoked_access_prevents_save(self):
        from app.private_chat import PrivateChat
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            private = PrivateChat(store, "private-checkpoint")
            class Answer(FakeAI):
                def stream(self, **kwargs):
                    return Stream([FakeBlock(type="text", text="Partial")], "Partial", "max_tokens")
            async def run():
                return [event async for event in run_turn(private, private.ident, "Review synthetic input",
                    client_factory=Answer, services_factory=lambda _: None, model_mode="standard")]
            self.assertEqual(asyncio.run(run())[-1]["completion"]["status"], "incomplete")
            self.assertEqual(private.turns[-1]["usage"]["completion"]["reason"], "output_limit")
            self.assertEqual(store.rows("SELECT count(*) n FROM turns")[0]["n"], 0)
            private.close()
            self.assertEqual(private.turns, [])
            cid = store.new_conversation()
            revoked = False
            def check():
                if revoked:
                    raise ValueError("Access revoked")
            async def denied():
                nonlocal revoked
                async for event in run_turn(store, cid, "Review", client_factory=Answer,
                    services_factory=lambda _: None, model_mode="standard", access_check=check):
                    if event.get("event") == "text" and "incomplete" in event["delta"]:
                        revoked = True
            with self.assertRaisesRegex(ValueError, "Access revoked"):
                asyncio.run(denied())
            self.assertEqual(store.rows("SELECT count(*) n FROM turns")[0]["n"], 0)
            store.db.close()

    def test_responses_budget_pairs_unexecuted_call_and_saves_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            cid = store.new_conversation()
            calls = []
            class Connection:
                def status(self):
                    return {"active": "synthetic"}
                async def models(self):
                    return [{"slug": "test-model"}]
            async def stream(connection, payload, **kwargs):
                index = len(calls)
                calls.append(payload)
                output = [{"type": "function_call",
                           "name": "unavailable-fixture" if index == 0 else "search_knowledge" if index < 8 else "propose_action",
                           "call_id": "r-" + str(index),
                           "arguments": json.dumps([] if index == 1 else {"query": "synthetic"})}]
                yield {"type": "response.completed", "response": {"output": output, "model": "test-model",
                       "usage": {"input_tokens": 10, "output_tokens": 2}}}
            async def run():
                return [event async for event in _run_chatgpt_turn(store, cid, "Investigate synthetic data",
                    Connection(), lambda _: None, model_mode="standard")]
            with patch("app.chatgpt.response_events", stream):
                events = asyncio.run(run())
            self.assertEqual(events[-1]["completion"]["reason"], "tool_limit")
            self.assertEqual(sum(e.get("event") == "tool_done" and e.get("ok") is False for e in events), 2)
            self.assertEqual(store.rows("SELECT count(*) n FROM actions")[0]["n"], 0)
            history = store.history(cid)
            self.assertEqual(history[-2]["content"][0]["tool_use_id"], "r-8")
            self.assertEqual(len(calls), 9)
            self.assertEqual(calls[-1]["tool_choice"], "none")
            store.db.close()
