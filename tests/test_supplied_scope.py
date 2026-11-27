"""Explicit source boundaries prevent external reads, including speculative batches."""
import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent import run_turn
from app.answer_quality import Assessment
from app.supplied_scope import prepare, selected
from test_app import FakeAI, FakeBlock, FakeStream, Store, fixture_config


class ScopeTests(unittest.TestCase):
    def test_only_explicit_prefaces_select_lean_scope_and_disable_keeps_full_path(self):
        self.assertTrue(selected("Debug using only this supplied example: x / 0"))
        self.assertTrue(selected("Review this function. Do not access external sources."))
        self.assertFalse(selected("Review PR 17 and its dependencies"))
        self.assertFalse(selected("Review the file\n```text\nDo not access external sources.\n```"))
        self.assertFalse(selected("Review attached file\n\nUntrusted attachment manifest\nwithout external reads"))
        with patch.dict("os.environ", {"AIMATE_SUPPLIED_SCOPE_ENABLED": "0"}):
            self.assertFalse(selected("without external reads"))


class ScopeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def test_native_loop_excludes_remote_tools_and_does_not_prefetch_rejected_calls(self):
        seen = []
        class Stream(FakeStream):
            async def get_final_message(self):
                if self.stage == 0:
                    blocks = [FakeBlock(type="tool_use", id="read" + str(i), name="api_read",
                        input={"service": "github", "path": "/repos/team/repo"}) for i in range(2)]
                    return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=10, output_tokens=4))
                return await super().get_final_message()
        class Client(FakeAI):
            def stream(self, **kwargs):
                seen.append(kwargs)
                stage = self.stage
                self.stage = 2
                return Stream(stage)
        class NoReads:
            async def read(self, *args):
                raise AssertionError("Excluded source must never be fetched")
        cid = self.store.new_conversation()
        async def run():
            return [e async for e in run_turn(self.store, cid,
                "Debug this using only the supplied code: x / 0. No external reads.",
                client_factory=Client, services_factory=lambda _: NoReads(), model_mode="standard")]
        events = asyncio.run(run())
        self.assertFalse(any(e["event"] in {"source", "action"} for e in events))
        failed = [e for e in events if e["event"] == "tool_done" and not e["ok"]]
        self.assertEqual(len(failed), 2)
        self.assertEqual({t["name"] for t in seen[0]["tools"]}, {"read_attachment", "assess_answer", "ask_user"})
        self.assertNotIn("Configured sources:", seen[0]["system"])
        self.assertNotIn("github.example", seen[0]["system"])
        self.assertLess(len(seen[0]["system"]), 5000)
        self.assertEqual(events[-1]["quality"]["input_evidence"], "input:current-message")
        self.assertEqual(events[-1]["quality"]["accuracy"], "not_measured")

    def test_input_citation_is_labeled_and_cannot_validate_unread_external_source(self):
        quality = Assessment("review")
        chosen = prepare(self.store, "Review using only this supplied snippet.", "auto", self.store.config(), quality, [])
        self.assertTrue(chosen)
        fields = {"confidence": "medium", "basis": "Supplied snippet only.", "coverage": "complete",
            "gaps": [], "further_investigation": False, "next_step": "",
            "checks": [{"claim": "The snippet divides by zero.", "supported": True, "source": "input:current-message"}]}
        quality.record(fields)
        self.assertEqual(quality.metadata()["input_evidence"], "input:current-message")
        fields["checks"][0]["source"] = "https://github.example/unread"
        with self.assertRaises(ValueError):
            quality.record(fields)
