"""Routing and persistence without external calls or billable inference."""
import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace

from app.agent import run_turn
from app.connection_checks import check_connection
from app.model_routing import parse_route, route_input, select_model
from app.store import Store
from app.validation import validate_config
from test_app import FakeBlock, fixture_config, create_app
from fastapi.testclient import TestClient


class RoutingTests(unittest.TestCase):
    def test_manual_selection_skips_classifier(self):
        async def forbidden():
            raise AssertionError("Manual selection must not classify")
        ai = {"model": "standard-id", "analysis_model": "analysis-id"}
        for mode, model in (("standard", "standard-id"), ("analysis", "analysis-id")):
            result = asyncio.run(select_model(ai, mode, forbidden))
            self.assertEqual(result["model"], model)
            self.assertEqual(result["routing_usage"]["input_tokens"], 0)

    def test_auto_obeys_ai_decision_and_retains_usage_on_bad_json(self):
        ai = {"model": "standard-id", "analysis_model": "analysis-id"}
        for text, expected in (('{"route":"analysis"}', "analysis-id"),
                               ('{"route":"standard"}', "standard-id"), ("bad", "standard-id")):
            async def classify():
                return text, {"input_tokens": 23, "output_tokens": 4}
            result = asyncio.run(select_model(ai, "auto", classify))
            self.assertEqual(result["model"], expected)
            self.assertEqual(result["routing_usage"]["input_tokens"], 23)
            self.assertEqual("notice" in result, text == "bad")

    def test_unconfigured_auto_does_not_classify_and_manual_analysis_errors(self):
        async def forbidden():
            raise AssertionError("No second model")
        result = asyncio.run(select_model({"model": "standard-id"}, "auto", forbidden))
        self.assertEqual(result["model"], "standard-id")
        self.assertIn("notice", result)
        with self.assertRaisesRegex(ValueError, "Add an Analysis model"):
            asyncio.run(select_model({"model": "standard-id"}, "analysis", forbidden))
        with self.assertRaises(ValueError):
            parse_route('{"route":"unconfigured-provider"}')

    def test_router_context_bounded_and_excludes_tool_results(self):
        history = [{"role": "assistant", "content": [
            {"type": "text", "text": "Investigating PR 123"},
            {"type": "tool_use", "input": {"token": "not-context"}}]},
            {"role": "user", "content": [{"type": "tool_result", "content": "not-context"}]}]
        packed = route_input("q" * 30000, history)
        self.assertNotIn("not-context", packed)
        self.assertIn("PR 123", packed)
        self.assertEqual(len(json.loads(packed)["request"]), 4000)
        with_reference = json.loads(route_input("Continue", [], "saved " * 1000))
        self.assertEqual(len(with_reference["saved_reference"]), 1600)

    def test_simple_bedrock_keeps_optional_analysis_id_and_saved_key(self):
        raw = {"ai": {"provider": "bedrock", "bedrock_mode": "simple",
                      "analysis_model": "account-analysis-id"}}
        cfg = validate_config(raw, {"ai": {"provider": "bedrock", "api_key": "saved"}})
        self.assertEqual(cfg["ai"]["analysis_model"], "account-analysis-id")
        self.assertEqual(cfg["ai"]["api_key"], "saved")
        self.assertEqual(cfg["ai"]["model"], "us.anthropic.claude-haiku-5-5")

    def test_turn_uses_analysis_and_persists_router_and_answer_tokens(self):
        class AI:
            closed = False
            def __init__(self):
                self.messages = self
                self.calls = []
            async def create(self, **kwargs):
                self.calls.append(("router", kwargs))
                self_assert.assertNotIn("tools", kwargs)
                self_assert.assertEqual(kwargs["max_tokens"], 128)
                self_assert.assertNotIn("private-token", json.dumps(kwargs))
                return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"route":"analysis"}')],
                                       usage=SimpleNamespace(input_tokens=12, output_tokens=4))
            def stream(self, **kwargs):
                self.calls.append(("answer", kwargs))
                class Stream:
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        pass
                    @property
                    def text_stream(self):
                        async def text():
                            yield "Evidence-based analysis."
                        return text()
                    async def get_final_message(self):
                        return SimpleNamespace(content=[FakeBlock(type="text", text="Evidence-based analysis.")],
                                               usage=SimpleNamespace(input_tokens=100, output_tokens=20),
                                               model="analysis-id")
                return Stream()
            async def close(self):
                self.closed = True
        self_assert = self
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            cfg = fixture_config()
            cfg["ai"].update(model="standard-id", analysis_model="analysis-id")
            store.save_config(cfg)
            cid = store.new_conversation()
            ai = AI()
            async def collect():
                return [e async for e in run_turn(store, cid, "Debug this failure", client_factory=lambda cfg: ai)]
            events = asyncio.run(collect())
            self.assertEqual([c[1]["model"] for c in ai.calls], ["standard-id", "analysis-id"])
            self.assertEqual(events[-1]["usage"], {"input_tokens": 112, "output_tokens": 24})
            self.assertEqual(events[-1]["by_model"]["standard-id"]["input_tokens"], 12)
            saved = json.loads(store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
            self.assertEqual(saved["route"], "analysis")
            self.assertEqual(saved["usage"], events[-1]["usage"])
            self.assertTrue(ai.closed)
            store.db.close()

    def test_access_report_does_not_claim_analysis_permission_from_standard(self):
        class AI:
            def __init__(self):
                self.messages = self
            async def create(self, **kwargs):
                if kwargs["model"] == "analysis-id":
                    raise ValueError("Analysis access denied")
                return SimpleNamespace(model="standard-id", content=[SimpleNamespace(type="text", text="OK")])
            async def close(self):
                pass
        cfg = fixture_config()
        cfg["ai"].update(model="standard-id", analysis_model="analysis-id")
        report = asyncio.run(check_connection("ai", cfg, None, lambda cfg: AI(), None))
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["counts"], {"passed": 1, "total": 2, "unit": "models"})
        self.assertTrue(report["targets"][0]["ok"])
        self.assertFalse(report["targets"][1]["ok"])

    def test_invalid_mode_is_rejected_before_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            cid = store.new_conversation()
            with TestClient(create_app(store, demo=False)) as client:
                csrf = client.post("/api/login", json={"password": store.password}).json()["csrf"]
                for mode in ("unconfigured-model", ["analysis"]):
                    result = client.post("/api/chat", json={"conversation": cid, "question": "Debug", "model_mode": mode},
                                         headers={"X-CSRF-Token": csrf})
                    self.assertEqual(result.status_code, 400)
                    self.assertIn("Choose Auto", result.json()["detail"])
            store.db.close()
