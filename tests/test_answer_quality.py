"""Quality metadata must stay qualitative, scoped, bounded and portable."""
import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.agent import run_turn, tools_for
from app.answer_quality import Assessment, kind
from app.connectors import Services
from test_app import Store, fixture_config, FakeAI, FakeBlock, FakeStream

FIELDS = {"confidence": "medium", "basis": "Only the source implementation was read.",
          "coverage": "partial", "gaps": ["Runtime tests not run."],
          "further_investigation": True, "next_step": "Run the affected tests."}
COMMIT = "a" * 40


class QualityTests(unittest.TestCase):
    def test_percentages_come_from_evidence_and_requested_work_checklists(self):
        assessment = Assessment("review")
        assessment.observe("api_read", {"source": "fixture:source"})
        checks = [{"claim": f"Claim {i}", "supported": i < 3, "source": "fixture:source"} for i in range(5)]
        work = [{"task": f"Task {i}", "completed": i < 4} for i in range(5)]
        assessment.record({**FIELDS, "checks": checks, "work_items": work})
        self.assertEqual(assessment.metadata()["accuracy_percent"], 60)
        self.assertEqual(assessment.metadata()["completion_percent"], 80)
        self.assertEqual(assessment.metadata()["accuracy"], "not_measured")
        assessment.observe("api_read", failed=True)
        self.assertIsNone(assessment.metadata()["accuracy_percent"])
        self.assertIsNone(assessment.metadata()["completion_percent"])

    def test_unverified_sources_duplicate_work_and_false_completion_rejected(self):
        for extras in (
            {"checks": [{"claim": "Known fact", "supported": True, "source": "not read"}]},
            {"work_items": [{"task": "Fix", "completed": True}]},
            {"work_items": [{"task": "Fix", "completed": False}] * 2},
            {"work_items": [{"task": "Fix", "completed": "yes"}]},
        ):
            with self.subTest(extras=extras), self.assertRaises(ValueError):
                Assessment("review").record({**FIELDS, **extras})
        assessment = Assessment("review")
        assessment.record(FIELDS)
        self.assertIsNone(assessment.metadata()["accuracy_percent"])
        self.assertIsNone(assessment.metadata()["completion_percent"])

    def test_only_relevant_prompts_and_disabled_behavior(self):
        for question in ("What is your name?", "Hello", "Show PR 7 details"):
            self.assertIsNone(kind(question))
        for question, expected in (("Review this code", "review"), ("Design an architecture", "design"),
                                   ("Investigate the failure", "analysis"), ("Write technical notes", "note"),
                                   ("Search the web for this fact", "search")):
            self.assertEqual(kind(question), expected)
        self.assertIsNone(kind("Hello\n\nUntrusted attachment manifest\nReview everything"))
        self.assertIsNone(kind("Review this code", "plain"))
        config = {**fixture_config(), "_quality_kind": "review"}
        self.assertIn("assess_answer", {t["name"] for t in tools_for(config)})
        with patch.dict(os.environ, {"AIMATE_ANSWER_QUALITY_ENABLED": "0"}):
            self.assertIsNone(kind("Review this code"))
            self.assertNotIn("assess_answer", {t["name"] for t in tools_for(config)})
            self.assertIsNone(Assessment("review").metadata())

    def test_truthful_default_and_current_turn_source_counts(self):
        assessment = Assessment("review")
        self.assertFalse(assessment.metadata()["assessed"])
        self.assertEqual(assessment.metadata()["accuracy"], "not_measured")
        for _ in range(2):
            assessment.observe("api_read", {"source": "https://example.test/1"})
        assessment.observe("api_read", failed=True)
        assessment.observe("assess_answer", failed=True)
        assessment.record(FIELDS)
        metadata = assessment.metadata()
        self.assertTrue(metadata["assessed"])
        self.assertEqual(metadata["source_count"], 1)
        self.assertEqual(metadata["failed_reads"], 1)
        self.assertEqual(metadata["gaps"], FIELDS["gaps"])
        assessment.observe("api_read", {"source": "https://example.test/2"})
        self.assertFalse(assessment.metadata()["assessed"])
        self.assertIsNone(Assessment(None).metadata())

    def test_percentages_false_completeness_and_unbounded_content_rejected(self):
        for change in ({"accuracy": 95}, {"confidence": "100%"}, {"coverage": "complete"},
                       {"further_investigation": False}, {"next_step": ""},
                       {"basis": ""}, {"basis": "x" * 401}, {"gaps": ["x"] * 7},
                       {"further_investigation": "no"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Assessment("review").record({**FIELDS, **change})
        assessment = Assessment("design")
        assessment.record({**FIELDS, "coverage": "not_applicable", "gaps": [],
                           "further_investigation": False, "next_step": ""})
        self.assertEqual(assessment.metadata()["coverage"], "not_applicable")


class QualityLoopTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.calls = []
        def remote(request):
            self.calls.append(request)
            if "/git/trees/" in request.url.path:
                return httpx.Response(200, json={"tree": [{"type": "blob", "path": "src/retry.py",
                                                           "size": 10, "mode": "100644"}]})
            return httpx.Response(200, json={"description": "Current evidence."})
        self.factory = lambda cfg: Services(cfg, httpx.MockTransport(remote))

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def test_native_search_assessment_persist_and_fallback(self):
        class Stream(FakeStream):
            async def get_final_message(self):
                content = ([FakeBlock(type="tool_use", id="search", name="find_repository_files",
                                     input={"repo": "team/repo", "ref": COMMIT, "path_pattern": "*.py"})]
                           if self.stage == 0 else
                           [FakeBlock(type="tool_use", id="quality", name="assess_answer", input=FIELDS)]
                           if self.stage == 1 else [FakeBlock(type="text", text="A partial review.")])
                return SimpleNamespace(content=content, usage=SimpleNamespace(input_tokens=20, output_tokens=5))
        class AI(FakeAI):
            def stream(self, **kwargs):
                stream = Stream(self.stage)
                self.stage += 1
                return stream
        cid = self.store.new_conversation()
        async def turn():
            return [event async for event in run_turn(self.store, cid, "Review this repository",
                client_factory=AI, services_factory=self.factory, model_mode="standard")]
        events = asyncio.run(turn())
        quality = events[-1]["quality"]
        self.assertEqual(quality["confidence"], "medium")
        self.assertEqual(quality["source_count"], 1)
        saved = json.loads(self.store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
        self.assertEqual(saved["quality"], quality)
        self.assertTrue(all(request.method == "GET" for request in self.calls))
        with patch.dict(os.environ, {"AIMATE_ANSWER_QUALITY_ENABLED": "0"}):
            events = asyncio.run(turn())
            self.assertIsNone(events[-1]["quality"])
            self.assertTrue(any(e["event"] == "tool_done" and e["name"] == "assess_answer"
                                and not e["ok"] for e in events))

    def test_responses_search_and_assessment_use_same_contract(self):
        from app.bedrock_gpt import Connection, PROVIDER, DEFAULT_MODEL
        cfg = self.store.config()
        cfg["ai"] = {"provider": PROVIDER, "model": DEFAULT_MODEL, "region": "us-east-2",
                     "api_key": "synthetic-bedrock-token", "bedrock_mode": "advanced"}
        self.store.save_config(cfg)
        payloads = []
        def remote(request):
            body = json.loads(request.content)
            payloads.append(body)
            calls = [("find_repository_files", {"repo": "team/repo", "ref": COMMIT, "path_pattern": "*.py"}),
                     ("assess_answer", FIELDS)]
            output = ([{"type": "function_call", "call_id": "call"+str(len(payloads)),
                        "name": calls[len(payloads)-1][0], "arguments": json.dumps(calls[len(payloads)-1][1])}]
                      if len(payloads) <= 2 else [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "Partial review."}]}])
            events = []
            if len(payloads) > 2:
                events.append({"type": "response.output_text.delta", "delta": "Partial review."})
            events.append({"type": "response.completed", "response": {"model": body["model"], "output": output,
                "usage": {"input_tokens": 20, "output_tokens": 5}}})
            return httpx.Response(200, text="".join("data: "+json.dumps(e)+"\n\n" for e in events),
                                  headers={"content-type": "text/event-stream"})
        transport = httpx.MockTransport(remote)
        cid = self.store.new_conversation()
        async def turn():
            return [event async for event in run_turn(self.store, cid, "Review this repository",
                services_factory=self.factory, model_mode="standard")]
        with patch("app.bedrock_gpt.Connection",
                   side_effect=lambda config, store=None: Connection(config, store, transport)):
            events = asyncio.run(turn())
        self.assertTrue(events[-1]["quality"]["assessed"])
        self.assertEqual(events[-1]["quality"]["source_count"], 1)
        result = next(item for item in payloads[1]["input"] if item.get("type") == "function_call_output")
        self.assertIn("src/retry.py", result["output"])
        self.assertEqual(len(payloads), 3)  # No independent evaluator call.
