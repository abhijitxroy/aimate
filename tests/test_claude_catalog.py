import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from test_app import FakeAI, Store, fixture_config
from app.claude_catalog import Catalog, model_id
from app.main import create_app


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_cache_is_scoped_coalesced_expired_and_bounded(self):
        calls = []
        now = [0]
        async def fetch(ai):
            calls.append(ai["api_key"])
            await asyncio.sleep(0)
            return {"models": [{"id": "global.anthropic.claude-opus-5-5"}], "message": "Catalog only"}
        catalog = Catalog(fetch, lambda: now[0])
        ai = {"provider": "bedrock", "api_key": "fixture-a", "region": "us-east-2"}
        await asyncio.gather(catalog.get(ai), catalog.get(ai))
        self.assertEqual(len(calls), 1)
        await catalog.get({**ai, "api_key": "fixture-b"})
        await catalog.get({**ai, "region": "us-east-1"})
        self.assertEqual(len(calls), 3)
        now[0] = 301
        await catalog.get(ai)
        self.assertEqual(len(calls), 4)
        for index in range(10):
            await catalog.get({**ai, "api_key": f"fixture-{index}"})
        self.assertEqual(len(catalog.entries), 8)
        self.assertNotIn("fixture-a", json.dumps(catalog.entries))

    async def test_unknown_and_rotated_catalog_choices_fail_closed(self):
        async def fetch(ai):
            return {"models": [{"id": "global.anthropic.claude-opus-4-7"}], "message": "Listed"}
        catalog = Catalog(fetch)
        ai = {"provider": "bedrock", "api_key": "fixture-a"}
        await catalog.get(ai)
        self.assertEqual(catalog.choose(ai, "global.anthropic.claude-opus-4-7"), "global.anthropic.claude-opus-4-7")
        with self.assertRaisesRegex(ValueError, "Refresh"):
            catalog.choose({**ai, "api_key": "fixture-b"}, "global.anthropic.claude-opus-4-7")
        for invalid in ("https://bad.example/model", "../anthropic.claude-opus-5", "openai.gpt-6"):
            with self.assertRaises(ValueError):
                model_id(invalid)
        with patch.dict(os.environ, {"AIMATE_MANUAL_MODELS_ENABLED": "0"}):
            with self.assertRaisesRegex(ValueError, "disabled"):
                catalog.choose(ai, "us.anthropic.claude-sonnet-5-5")

    async def test_disabled_automatic_discovery_keeps_presets_and_explicit_refresh(self):
        calls = []
        async def fetch(ai):
            calls.append(True); return {"models": [], "message": "Unavailable"}
        catalog = Catalog(fetch)
        ai = {"provider": "bedrock", "api_key": "fixture"}
        with patch.dict(os.environ, {"AIMATE_CLAUDE_CATALOG_ENABLED": "0"}):
            value = await catalog.get(ai)
            self.assertEqual(len(value["presets"]), 6)
            self.assertFalse(calls)
            await catalog.get(ai, force=True)
            self.assertEqual(len(calls), 1)

    async def test_unavailable_discovery_keeps_six_presets_without_claiming_access(self):
        async def fetch(ai):
            raise RuntimeError("Synthetic network failure")
        value = await Catalog(fetch).get({"provider": "bedrock", "api_key": "fixture"})
        self.assertEqual(len(value["presets"]), 6)
        self.assertEqual(value["models"], [])
        self.assertIn("unavailable", value["message"])


class ManualModelTests(unittest.TestCase):
    def test_api_manual_model_is_used_and_slots_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            config = fixture_config()
            config["ai"] = {"provider": "bedrock", "model": "us.anthropic.claude-haiku-5-5",
                            "analysis_model": "us.anthropic.claude-sonnet-5-5",
                            "api_key": "synthetic-fixture", "region": "us-east-2"}
            store.save_config(config)
            seen = []
            class Answer(FakeAI):
                def __init__(self, cfg):
                    super().__init__(cfg); self.stage = 2
                def stream(self, **kwargs):
                    seen.append(kwargs); return super().stream(**kwargs)
            app = create_app(store, client_factory=Answer, services_factory=lambda _: None)
            with TestClient(app) as client:
                client.headers["X-CSRF-Token"] = client.post("/api/login", json={"password": store.password}).json()["csrf"]
                cid = client.post("/api/conversations", json={}).json()["id"]
                for chosen in ("us.anthropic.claude-opus-5-5", "us.anthropic.claude-fable-5-2"):
                    response = client.post("/api/chat", json={"conversation": cid, "question": "What is your name?",
                        "model_mode": "manual", "manual_model": chosen})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(seen[-1]["model"], chosen)
                    self.assertEqual(store.config()["ai"]["model"], config["ai"]["model"])
                    self.assertEqual(store.config()["ai"]["analysis_model"], config["ai"]["analysis_model"])
                    usage = client.get("/api/conversations/" + cid).json()["turns"][-1]["usage"]
                    self.assertEqual((usage["mode"], usage["model"], usage["route"]), ("manual", chosen, "manual"))
                with patch.dict(os.environ, {"AIMATE_MANUAL_MODELS_ENABLED": "0"}):
                    count = len(seen)
                    self.assertEqual(client.post("/api/chat", json={"conversation": cid, "question": "Hello",
                        "model_mode": "manual", "manual_model": "us.anthropic.claude-opus-5-5"}).status_code, 400)
                    self.assertEqual(len(seen), count)
                self.assertEqual(client.post("/api/chat", json={"conversation": cid, "question": "Hello",
                    "model_mode": "manual", "manual_model": "../model"}).status_code, 400)
            store.db.close()
