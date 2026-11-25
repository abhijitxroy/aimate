"""Synthetic Google OAuth/Vertex transport; no real credentials or inference."""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from fastapi.testclient import TestClient
from app.agent import ai_error, run_turn
from app.connectors import scrub
from app.gemini_vertex import Client, TOKEN_URL, credentials, contents
from app.store import Store
from app.validation import validate_config
from test_app import create_app, fixture_config


class GeminiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.info = {"type": "service_account", "project_id": "synthetic-project",
            "client_email": "fixture@synthetic-project.iam.gserviceaccount.com",
            "private_key": cls.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode(),
            "private_key_id": "synthetic-key-id", "token_uri": TOKEN_URL, "universe_domain": "googleapis.com"}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.config = fixture_config()
        self.config["ai"] = {"provider": "gemini", "model": "gemini-4-hydrogen",
            "gcp_credentials": json.dumps(self.info), "gcp_location": "global", "gcp_project": "synthetic-project"}
        self.store.save_config(self.config)
        self.requests, self.oauth, self.rounds = [], 0, 0
        self.mode = "answer"
        self.transport = httpx.MockTransport(self.handle)

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def handle(self, request):
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            self.oauth += 1
            assertion = parse_qs(request.content.decode())["assertion"][0]
            claims = jwt.decode(assertion, self.key.public_key(), algorithms=["RS256"], audience=TOKEN_URL)
            self.assertEqual(claims["iss"], self.info["client_email"])
            self.assertEqual(claims["scope"], "https://www.googleapis.com/auth/cloud-platform")
            self.assertEqual(claims["exp"] - claims["iat"], 3600)
            if self.mode == "revoked":
                return httpx.Response(400, json={"private_key": self.info["private_key"]})
            return httpx.Response(200, json={"access_token": "synthetic-access-token", "expires_in": 3600})
        self.assertEqual(request.url.host, "aiplatform.googleapis.com")
        self.assertEqual(request.headers["authorization"], "Bearer synthetic-access-token")
        self.assertNotIn(self.info["private_key"], request.content.decode())
        body = json.loads(request.content)
        self.assertGreaterEqual(body["generationConfig"]["maxOutputTokens"], 256)
        self.rounds += 1
        if self.mode == "denied":
            return httpx.Response(403, json={"error": {"message": "synthetic-access-token"}})
        parts = [{"text": "Vertex replied."}]
        if self.mode == "tools" and self.rounds == 1:
            self.assertTrue(body["tools"][0]["functionDeclarations"][0]["parametersJsonSchema"])
            parts = [{"functionCall": {"name": "api_read", "args": {
                "service": "github", "path": "/repos/team/repo/pulls/1"}}, "thoughtSignature": "synthetic-signature"}]
        elif self.mode == "tools":
            previous = body["contents"][-2]["parts"]
            self.assertEqual(previous[0]["thoughtSignature"], "synthetic-signature")
            self.assertEqual(body["contents"][-1]["parts"][0]["functionResponse"]["name"], "api_read")
        data = {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 12, "cachedContentTokenCount": 2,
                              "candidatesTokenCount": 3, "thoughtsTokenCount": 4}}
        if self.mode == "missing-usage":
            data.pop("usageMetadata")
        if request.url.path.endswith(":streamGenerateContent"):
            if self.mode == "truncated":
                data["candidates"][0].pop("finishReason")
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  text="data: " + json.dumps(data) + "\n\n")
        return httpx.Response(200, json=data)

    def test_saved_credentials_are_encrypted_hidden_and_isolated_from_bedrock(self):
        old = {**self.config, "ai": {"provider": "bedrock", "api_key": "synthetic-bedrock-key"}}
        normalized = validate_config(self.config, old)
        self.assertEqual(normalized["ai"]["api_key"], "synthetic-bedrock-key")
        back = {**self.config, "ai": {"provider": "opencode", "model": "", "api_key": ""}}
        self.assertEqual(validate_config(back, normalized)["ai"]["api_key"], "synthetic-bedrock-key")
        foreign = {**self.config, "ai": {"provider": "anthropic", "api_key": ""}}
        self.assertEqual(validate_config(foreign, normalized)["ai"]["api_key"], "")
        self.assertTrue(self.store.public_config()["ai"]["gcp_credentials_configured"])
        self.assertNotIn("gcp_credentials", self.store.public_config()["ai"])
        self.assertNotIn("BEGIN PRIVATE KEY", json.dumps(self.store.public_config()))
        self.assertEqual(scrub(self.info["private_key"], self.config), "[redacted]")
        self.assertEqual(scrub(json.dumps(self.info["private_key"])[1:-1], self.config), "[redacted]")
        removed = {**self.config, "ai": {**self.config["ai"], "gcp_credentials": "", "clear_gcp": True}}
        self.assertEqual(validate_config(removed, self.config)["ai"]["gcp_credentials"], "")
        self.assertNotIn(b"BEGIN PRIVATE KEY", (self.store.directory / "app.sqlite3").read_bytes())

    def test_fixed_endpoints_invalid_json_and_disabled_module(self):
        for change in ({"token_uri": "https://example.com/token"}, {"type": "external_account"}, {"private_key": "not-a-key"}):
            with self.assertRaises(ValueError):
                credentials(json.dumps({**self.info, **change}))
        for field, value in (("gcp_project", "../escape"), ("gcp_location", "https://example.com"), ("model", "gemini-4/foo")):
            raw = {**self.config, "ai": {**self.config["ai"], field: value}}
            with self.assertRaises(ValueError):
                validate_config(raw, self.config)
        with TestClient(create_app(self.store, demo=False)) as browser:
            self.assertEqual(browser.get("/api/gemini/models").status_code, 401)
            browser.post("/api/login", json={"password": self.store.password})
            self.assertTrue(browser.get("/api/gemini/models").json()["models"])
            with patch.dict(os.environ, {"AIMATE_GEMINI_ENABLED": "0"}):
                self.assertFalse(browser.get("/api/gemini/models").json()["enabled"])
                with self.assertRaises(ValueError):
                    Client(self.config, self.transport)

    def test_oauth_cache_refresh_text_image_and_usage(self):
        async def run():
            client = Client(self.config, self.transport)
            try:
                result = await client.create(model="gemini-4-hydrogen", max_tokens=16, messages=[
                    {"role": "user", "content": [{"type": "text", "text": "Hi"},
                    {"type": "image", "source": {"media_type": "image/png", "data": "synthetic-image"}}]}])
                self.assertEqual(result.content[0].text, "Vertex replied.")
                self.assertEqual(result.usage.input_tokens, 10)
                self.assertEqual(result.usage.output_tokens, 7)
                body = json.loads(self.requests[-1].content)
                self.assertEqual(body["contents"][0]["parts"][1]["inlineData"]["mimeType"], "image/png")
                await client.create(model="gemini-4-hydrogen", messages=[{"role": "user", "content": "Again"}])
                self.assertEqual(self.oauth, 1)
                client.expires = 0
                await client.access_token()
                self.assertEqual(self.oauth, 2)
                self.mode = "missing-usage"
                result = await client.create(model="gemini-4-hydrogen", messages=[{"role": "user", "content": "Usage"}])
                self.assertIsNone(result.usage)
            finally:
                await client.close()
                self.assertEqual(client.token, "")
        asyncio.run(run())

    def test_tools_keep_signatures_and_existing_scope_guards(self):
        self.mode = "tools"
        class Services:
            def __init__(self, config):
                self.calls = []
            async def read(self, service, path, params=None):
                if service != "github" or path != "/repos/team/repo/pulls/1":
                    raise ValueError("Outside fixture scope")
                return {"source": "https://github.com/team/repo/pull/1", "data": {"title": "Fixture PR"}}
        async def run():
            cid = self.store.new_conversation()
            events = [event async for event in run_turn(self.store, cid, "Read the PR",
                client_factory=lambda config: Client(config, self.transport), services_factory=Services, model_mode="standard")]
            self.assertTrue(any(e["event"] == "source" for e in events))
            self.assertEqual(events[-1]["event"], "done")
            self.assertEqual(events[-1]["usage"]["output_tokens"], 14)
            history = self.store.history(cid)
            restored = contents(history, "gemini-4-hydrogen")
            self.assertTrue(any(p.get("thoughtSignature") == "synthetic-signature" for r in restored for p in r["parts"]))
            migrated = contents(history, "gemini-4-neon")
            self.assertFalse(any("thoughtSignature" in p for r in migrated for p in r["parts"]))
            foreign = contents(history, "gemini-4-hydrogen", "other-project/global/gemini-4-hydrogen")
            self.assertFalse(any("thoughtSignature" in p for r in foreign for p in r["parts"]))
        asyncio.run(run())

    def test_safe_auth_errors_and_truncated_stream_are_not_saved(self):
        async def run():
            for mode in ("revoked", "denied", "truncated"):
                self.mode = mode
                client = Client(self.config, self.transport)
                try:
                    with self.assertRaises(Exception) as raised:
                        async with client.stream(model="gemini-4-hydrogen", messages=[{"role": "user", "content": "Hi"}]) as stream:
                            async for _ in stream.text_stream:
                                pass
                            await stream.get_final_message()
                    error = ai_error(raised.exception)
                    self.assertNotIn("synthetic-access-token", error)
                    self.assertNotIn("PRIVATE KEY", error)
                    self.assertNotIn("AWS", error)
                finally:
                    await client.close()
            self.mode = "truncated"
            cid = self.store.new_conversation()
            with self.assertRaises(ValueError):
                async for _ in run_turn(self.store, cid, "Hi", model_mode="standard",
                        client_factory=lambda config: Client(config, self.transport), services_factory=lambda config: None):
                    pass
            self.assertEqual(self.store.history(cid), [])
        asyncio.run(run())
