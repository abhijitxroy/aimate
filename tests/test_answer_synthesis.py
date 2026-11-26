import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent import run_turn, _run_chatgpt_turn
from app.answer_synthesis import packet
from test_app import FakeAI, FakeBlock, Store, fixture_config
from test_investigation_completion import Stream


class SynthesisTests(unittest.TestCase):
    def test_packet_is_bounded_preserves_sources_and_excludes_reasoning(self):
        messages = [{"role": "assistant", "content": [{"type": "thinking", "thinking": "PRIVATE REASONING"}]}]
        for n in range(80):
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(n),
                "content": json.dumps({"source": "https://fixture.example/" + str(n),
                                      "data": "SSL " + str(n) + " " + "x" * 5000})}]})
        text = packet(messages, "Explain SSL")
        data = json.loads(text)
        self.assertLessEqual(len(text.encode()), 32000)
        self.assertNotIn("PRIVATE REASONING", text)
        self.assertGreater(data["omitted_results"], 0)
        self.assertTrue(data["evidence"][0]["source"].startswith("https://fixture.example/"))
        self.assertGreater(data["evidence"][0]["total_characters"], data["evidence"][0]["end"])

    def native(self, outcome="answer", disabled=False, private=False):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            owner = store
            if private:
                from app.private_chat import PrivateChat
                cid = "private-synthesis"
                store = PrivateChat(owner, cid)
            else:
                cid = store.new_conversation()
            requests = []
            class Answer(FakeAI):
                def stream(self, **kwargs):
                    return Stream([])
                async def create(self, **kwargs):
                    requests.append(kwargs)
                    if outcome == "error":
                        raise ValueError("Synthetic provider failure")
                    text = "" if outcome == "empty" else "Supported finding. Runtime ownership is unverified."
                    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                        usage=SimpleNamespace(input_tokens=10, output_tokens=5), stop_reason="end_turn")
            async def run():
                return [event async for event in run_turn(store, cid, "Investigate synthetic SSL",
                    client_factory=Answer, services_factory=lambda _: None, model_mode="standard")]
            with patch.dict(os.environ, {"AIMATE_FINAL_SYNTHESIS_ENABLED": "0" if disabled else "1"}):
                events = asyncio.run(run())
            metadata = store.turns[-1]["usage"] if private else json.loads(store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
            self.assertEqual(metadata["completion"]["status"], "partial" if outcome == "answer" and not disabled else "incomplete")
            self.assertEqual(len(requests), 0 if disabled else 1)
            if requests:
                self.assertNotIn("tools", requests[0])
                self.assertNotIn("ai-private-token", json.dumps(requests))
            if private:
                self.assertEqual(owner.rows("SELECT count(*) n FROM turns")[0]["n"], 0)
                store.close()
                self.assertEqual(store.turns, [])
            owner.db.close()
            return events

    def test_native_empty_answer_recovers_once_with_no_tools(self):
        self.assertIn("Supported finding", "".join(e.get("delta", "") for e in self.native()))

    def test_private_recovery_never_persists_owner_transcript(self):
        self.assertEqual(self.native(private=True)[-1]["completion"]["status"], "partial")

    def test_revoked_access_prevents_saving_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            cid = store.new_conversation()
            revoked = False
            class Answer(FakeAI):
                def stream(self, **kwargs):
                    return Stream([])
                async def create(self, **kwargs):
                    nonlocal revoked
                    revoked = True
                    return SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=0))
            def check():
                if revoked:
                    raise ValueError("Revoked")
            async def run():
                return [e async for e in run_turn(store, cid, "Review", client_factory=Answer,
                    services_factory=lambda _: None, model_mode="standard", access_check=check)]
            with self.assertRaisesRegex(ValueError, "Revoked"):
                asyncio.run(run())
            self.assertEqual(store.rows("SELECT count(*) n FROM turns")[0]["n"], 0)
            store.db.close()

    def test_failed_empty_and_disabled_recovery_preserve_checkpoint_without_loop(self):
        for outcome, disabled in (("error", False), ("empty", False), ("answer", True)):
            with self.subTest(outcome=outcome, disabled=disabled):
                self.assertEqual(self.native(outcome, disabled)[-1]["completion"]["status"], "incomplete")

    def test_responses_recovers_empty_answer_without_more_lookups(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            cid = store.new_conversation()
            requests = []
            class Connection:
                def status(self):
                    return {"active": "synthetic"}
                async def models(self):
                    return [{"slug": "test-model"}]
            async def stream(connection, payload, **kwargs):
                requests.append(payload)
                if len(requests) == 2:
                    yield {"type": "response.output_text.delta", "delta": "Supported partial findings."}
                yield {"type": "response.completed", "response": {"output": [], "model": "test-model",
                    "usage": {"input_tokens": 10, "output_tokens": 2}}}
            async def run():
                return [event async for event in _run_chatgpt_turn(store, cid, "Review synthetic input",
                    Connection(), lambda _: None, model_mode="standard")]
            with patch("app.chatgpt.response_events", stream):
                events = asyncio.run(run())
            self.assertEqual(len(requests), 2)
            self.assertNotIn("tools", requests[1])
            self.assertEqual(requests[1]["tool_choice"], "none")
            self.assertEqual(events[-1]["completion"]["status"], "partial")
            self.assertEqual(store.rows("SELECT count(*) n FROM turns")[0]["n"], 1)
            store.db.close()
