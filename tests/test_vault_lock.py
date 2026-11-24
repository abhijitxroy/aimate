import asyncio
import json
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient

from test_app import Store, create_app, fixture_config, FakeBlock
from app.agent import run_turn
from app.vault import save
from app.vault_lock import unlocked


class VaultLockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.app = create_app(self.store)
        self.client = TestClient(self.app)
        self.headers = {"x-csrf-token": self.client.post("/api/login", json={"password": self.store.password}).json()["csrf"]}

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def unlock(self, client=None, headers=None):
        return (client or self.client).post("/api/vault/unlock", headers=headers or self.headers,
                                           json={"verification": self.store.password})

    def test_locked_by_default_isolated_sessions_expiry_and_explicit_lock(self):
        self.assertEqual(self.client.get("/api/vault").status_code, 423)
        self.assertFalse(self.client.get("/api/vault/status").json()["unlocked"])
        self.assertEqual(self.unlock().status_code, 200)
        self.assertEqual(self.client.get("/api/vault").status_code, 200)
        other = TestClient(self.app)
        try:
            other.post("/api/login", json={"password": self.store.password})
            self.assertEqual(other.get("/api/vault").status_code, 423)
        finally:
            other.close()
        with patch("app.vault_lock.time.monotonic", return_value=10**15):
            self.assertEqual(self.client.get("/api/vault").status_code, 423)
        self.client.post("/api/vault/lock", headers=self.headers)
        self.assertEqual(self.client.get("/api/vault").status_code, 423)
        self.assertFalse(unlocked({"role": "viewer", "vault_until": 10**15}))

    def test_wrong_verification_rate_limit_and_csrf(self):
        self.assertEqual(self.client.post("/api/vault/unlock", json={"verification": self.store.password}).status_code, 403)
        for _ in range(5):
            response = self.client.post("/api/vault/unlock", headers=self.headers, json={"verification": "wrong"})
            self.assertEqual(response.status_code, 400)
        self.assertIn("Too many", self.unlock().text)
        self.assertEqual(self.client.get("/api/vault").status_code, 423)

    def test_enrolled_authenticator_requires_fresh_code_instead_of_dev_password(self):
        from app.otp import Authenticator, code_for_counter
        secret = "JBSWY3DPEHPK3PXP"
        Authenticator(self.store)._save({"secret": secret, "last_counter": -1, "recovery": []})
        self.assertEqual(self.unlock().status_code, 400)
        code = code_for_counter(secret, int(time.time() // 30))
        result = self.client.post("/api/vault/unlock", headers=self.headers, json={"verification": code})
        self.assertEqual(result.status_code, 200)
        self.client.post("/api/vault/lock", headers=self.headers)
        self.assertEqual(self.client.post("/api/vault/unlock", headers=self.headers,
                                         json={"verification": code}).status_code, 400)

    def test_reveal_writes_and_logout_require_unlock(self):
        ident = save(self.store, {"name": "Private entry", "value": "synthetic-secret", "ai_access": True})["id"]
        for method, path, body in [
            ("POST", "/api/vault", {"name": "Other", "value": "synthetic-other"}),
            ("PATCH", "/api/vault/" + ident, {"name": "Renamed", "value": "new"}),
            ("POST", "/api/vault/" + ident + "/reveal", {}),
            ("DELETE", "/api/vault/" + ident, {})]:
            self.assertEqual(self.client.request(method, path, headers=self.headers, json=body).status_code, 423)
        self.unlock()
        self.assertEqual(self.client.post("/api/vault/" + ident + "/reveal", headers=self.headers).json()["value"], "synthetic-secret")
        self.client.post("/api/logout", headers=self.headers)
        self.headers = {"x-csrf-token": self.client.post("/api/login", json={"password": self.store.password}).json()["csrf"]}
        self.assertEqual(self.client.get("/api/vault").status_code, 423)

    def test_model_cannot_read_after_vault_locks_mid_turn(self):
        secret = "synthetic-vault-only-secret"
        save(self.store, {"name": "Private entry", "value": secret, "ai_access": True})
        cid = self.store.new_conversation()
        allowed = iter([True, False])
        calls = []

        class Stream:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            @property
            def text_stream(self):
                async def chunks():
                    if len(calls) > 1: yield "The vault is locked."
                return chunks()
            async def get_final_message(self):
                blocks = ([FakeBlock(type="tool_use", id="vault-read", name="read_vault_entry",
                                    input={"name": "Private entry"})] if len(calls) == 1
                          else [FakeBlock(type="text", text="The vault is locked.")])
                return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=10, output_tokens=5))

        class AI:
            def __init__(self, config): self.messages = self
            def stream(self, **kwargs):
                calls.append(kwargs)
                return Stream()
            async def close(self): pass

        async def run():
            return [event async for event in run_turn(self.store, cid, "Use Private entry",
                    client_factory=AI, model_mode="standard", vault_access=lambda: next(allowed))]
        events = asyncio.run(run())
        self.assertTrue(any(event.get("event") == "tool_done" and not event.get("ok") for event in events))
        self.assertNotIn(secret, json.dumps(calls))
        self.assertNotIn(secret, json.dumps(self.store.history(cid)))
