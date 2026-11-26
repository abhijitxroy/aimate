import asyncio
import os
import unittest
from unittest.mock import patch

from app.model_routing import select_model
from test_app import fixture_config, create_app
from fastapi.testclient import TestClient


class PolicyTests(unittest.TestCase):
    def test_quality_and_economy_use_configured_slots_without_classifier(self):
        async def forbidden():
            raise AssertionError("Fixed preference must not pay for classification.")
        for mode, expected, route in (("auto-quality", "deep", "analysis"), ("auto-economy", "routine", "standard")):
            result = asyncio.run(select_model({"model": "routine", "analysis_model": "deep"}, mode, forbidden))
            self.assertEqual(result["model"], expected)
            self.assertEqual(result["route"], route)
            self.assertEqual(result["routing_usage"]["input_tokens"], 0)
            self.assertIn("selected provider", result["notice"])

    def test_missing_analysis_and_disabled_policy_fail_without_escalation(self):
        async def forbidden():
            raise AssertionError("No classification")
        with self.assertRaisesRegex(ValueError, "Configure an Analysis"):
            asyncio.run(select_model({"model": "routine"}, "auto-quality", forbidden))
        with patch.dict(os.environ, {"AIMATE_AUTO_POLICY_ENABLED": "0"}):
            with self.assertRaisesRegex(ValueError, "policies are disabled"):
                asyncio.run(select_model({"model": "routine"}, "auto-economy", forbidden))
            self.assertEqual(asyncio.run(select_model({"model": "routine"}, "standard", forbidden))["model"], "routine")

    def test_api_accepts_user_policy_and_records_mode(self):
        import tempfile
        import json
        from app.store import Store
        from test_app import FakeAI
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            config = fixture_config()
            config["ai"]["analysis_model"] = "deep-fixture"
            store.save_config(config)
            class Answer(FakeAI):
                def __init__(self, config):
                    super().__init__(config)
                    self.stage = 2
            app = create_app(store, client_factory=Answer, services_factory=lambda _: None, demo=False)
            with TestClient(app) as c:
                login = c.post("/api/login", json={"password": store.password})
                c.headers["X-CSRF-Token"] = login.json()["csrf"]
                cid = c.post("/api/conversations", json={}).json()["id"]
                # Supplied-only evidence avoids external service calls.
                response = c.post("/api/chat", json={"conversation": cid, "question": "What is your name?", "model_mode": "auto-quality"})
                self.assertEqual(response.status_code, 200)
                data = c.get("/api/conversations/" + cid).json()
                self.assertEqual(data["turns"][-1]["usage"]["mode"], "auto-quality")
                self.assertNotIn("error", [json.loads(line[6:]).get("event") for line in response.text.splitlines() if line.startswith("data: ")])
            store.db.close()
