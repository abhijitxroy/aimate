"""OAuth security and streamed tool-loop tests without real accounts or billing."""
import asyncio
import json
import logging
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from test_app import fixture_config
from app.agent import run_turn
from app.chatgpt import ChatGPT, ISSUER, PERMISSION, RESOURCE, response_events
from app.main import OAuthLogFilter, create_app
from app.store import Store


class ChatGPTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update(kid="test", alg="RS256", use="sig")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.requests = []
        self.nonce, self.subject = "", "test-subject"
        self.grant_scope, self.fail_refresh = "openid " + PERMISSION, False
        self.response_mode, self.response_count = "answer", 0
        self.extra_model = False
        self.transport = httpx.MockTransport(self.handle)
        self.connection = ChatGPT(self.store, self.transport)

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def handle(self, request):
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/jwks.json"):
            return httpx.Response(200, json={"keys": [self.jwk]})
        if path.endswith("/oauth/token"):
            form = parse_qs(request.content.decode())
            if form["grant_type"][0] == "refresh_token" and self.fail_refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
            claims = {"iss": ISSUER, "sub": self.subject, "aud": "oaiapp_test",
                      "iat": int(time.time()), "exp": int(time.time()) + 3600,
                      "nonce": self.nonce, "email": "demo@example.test"}
            token = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test"})
            return httpx.Response(200, json={"access_token": "access-secret", "refresh_token": "refresh-secret",
                "id_token": token, "scope": self.grant_scope, "token_type": "Bearer", "expires_in": 3600})
        if path == "/v1/models":
            self.assertEqual(request.headers["authorization"], "Bearer access-secret")
            models = [
                {"slug": "test-model", "display_name": "Test model", "visibility": "list"},
                {"slug": "hidden", "visibility": "hide"}]
            if self.extra_model:
                models.append({"slug": "analysis-model", "display_name": "Analysis model", "visibility": "list"})
            return httpx.Response(200, json={"models": models})
        if path == "/v1/responses":
            self.response_count += 1
            payload = json.loads(request.content)
            self.assertIs(payload["store"], False)
            self.assertIs(payload["stream"], True)
            self.assertNotIn("max_output_tokens", payload)
            self.assertNotIn("previous_response_id", payload)
            events = [{"type": "response.output_text.delta", "delta": "Repository answer."}]
            if self.response_mode in {"tool", "proposal"} and self.response_count == 1:
                output = [{"type": "function_call", "call_id": "call1", "namespace": "project",
                           "name": "api_read", "arguments": json.dumps({"service": "github", "path": "/repos/team/repo"})}]
                events = []
                if self.response_mode == "proposal":
                    output[0].update(name="propose_action", arguments=json.dumps({
                        "service": "github", "operation": "create_issue", "payload": {
                            "repo": "team/repo", "title": "Review build"}, "reason": "User requested it"}))
            else:
                output = [{"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": "Repository answer.", "annotations": []}]}]
            if payload.get("instructions", "").startswith("Classify an engineering"):
                self.assertNotIn("tools", payload)
                self.assertNotIn("private-token", json.dumps(payload))
                events = [{"type": "response.output_text.delta", "delta": '{"route":"analysis"}'}]
                output = [{"type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": '{"route":"analysis"}', "annotations": []}]}]
            if self.response_mode == "tool" and self.response_count == 2:
                self.assertEqual(payload["tools"][0]["type"], "namespace")
                result = next(i for i in payload["input"] if i.get("type") == "function_call_output")
                self.assertEqual(result["call_id"], "call1")
                self.assertIn("evidence", result["output"])
            if self.response_mode == "usage_error":
                events.append({"type": "response.failed", "response": {"error": {
                    "code": "subscription_sharing_usage_limit_exceeded"}}})
            elif self.response_mode != "interrupted":
                events.append({"type": "response.completed", "response": {
                    "output": output, "usage": {"input_tokens": 5, "output_tokens": 3}}})
            return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events),
                                  headers={"content-type": "text/event-stream"})
        if path.endswith("/openid-configuration"):
            return httpx.Response(200, json={"revocation_endpoint": ISSUER + "/revoke"})
        if path == "/revoke":
            return httpx.Response(200)
        raise AssertionError("Unexpected request: " + path)

    def attempt(self, account=None):
        url = self.connection.start("http://127.0.0.1:8765", "owner-session", account)
        query = {k: values[0] for k, values in parse_qs(urlsplit(url).query).items()}
        self.nonce = query["nonce"]
        return query

    def connect(self, account=None):
        query = self.attempt(account)
        asyncio.run(self.connection.callback({"state": query["state"], "code": "code", "client_id": "oaiapp_test"},
                    lambda token: token == "owner-session", "http://127.0.0.1:8765"))
        return query

    def test_registration_pkce_identity_encryption_and_models(self):
        query = self.connect()
        self.assertEqual(query["client_id"], "dynamic_agent_client")
        self.assertEqual(query["agent_name_hint"], "AiMate")
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertEqual(query["redirect_uri"], "http://127.0.0.1:8765/auth/callback")
        self.assertTrue(self.connection.status()["plan_enabled"])
        self.assertEqual(asyncio.run(self.connection.models()), [{"slug": "test-model", "display_name": "Test model"}])
        public = json.dumps(self.connection.status())
        self.assertNotIn("access-secret", public)
        self.assertNotIn("refresh-secret", public)
        storage = self.store.rows("SELECT encrypted FROM chatgpt_auth")[0]["encrypted"]
        self.assertNotIn("access-secret", storage)
        self.assertEqual(ChatGPT(self.store).record()["host_id"], query["ext_agent_host_id"])
        exchange = parse_qs(next(r.content.decode() for r in self.requests if r.url.path.endswith("/oauth/token")))
        self.assertEqual(exchange["client_id"], ["oaiapp_test"])
        self.assertNotIn("client_secret", exchange)

    def test_callback_rejects_wrong_expired_reused_state_and_dead_session(self):
        query = self.attempt()
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.callback({"state": "wrong"}, lambda _: True, "http://127.0.0.1:8765"))
        self.assertFalse(self.requests)
        self.connection.pending[query["state"]]["expires"] = 0
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.callback({"state": query["state"], "code": "code"},
                                                lambda _: True, "http://127.0.0.1:8765"))
        query = self.connect()
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.callback({"state": query["state"], "code": "code"},
                                                lambda _: True, "http://127.0.0.1:8765"))
        query = self.attempt("oaiapp_test")
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.callback({"state": query["state"], "code": "code"},
                                                lambda _: False, "http://127.0.0.1:8765"))

    def test_returning_identity_cannot_replace_other_account(self):
        self.connect()
        self.subject = "different"
        with self.assertRaises(ValueError):
            self.connect("oaiapp_test")
        self.assertEqual(self.connection.record()["accounts"]["oaiapp_test"]["subject"], "test-subject")
        query = self.attempt("oaiapp_test")
        self.assertEqual(query["client_id"], "oaiapp_test")
        self.assertNotIn("agent_name_hint", query)

    def test_invalid_nonce_signature_audience_and_expiry(self):
        for changes in ({"nonce": "wrong"}, {"aud": "wrong"}, {"exp": 1}, {"iss": "https://wrong.example"}):
            claims = {"iss": ISSUER, "sub": "subject", "aud": "oaiapp_test", "nonce": "expected",
                      "iat": int(time.time()), "exp": int(time.time()) + 30, **changes}
            encoded = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test"})
            with self.assertRaises(ValueError):
                asyncio.run(self.connection.verify_identity(encoded, "oaiapp_test", "expected"))
        bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        encoded = jwt.encode({"sub": "x"}, bad_key, algorithm="RS256", headers={"kid": "test"})
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.verify_identity(encoded, "oaiapp_test", "expected"))

    def test_identity_without_plan_permission_cannot_infer(self):
        self.grant_scope = "openid email"
        self.connect()
        self.assertTrue(self.connection.status()["connected"])
        self.assertFalse(self.connection.status()["plan_enabled"])
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.access_token())
        self.assertFalse(any(r.url.host == "api.openai.com" for r in self.requests))

    def test_refresh_serialized_and_failed_refresh_not_overwritten(self):
        self.connect()
        record = self.connection.record()
        record["accounts"]["oaiapp_test"]["expires_at"] = 0
        self.connection.save(record)
        async def renew():
            return await asyncio.gather(*(self.connection.access_token() for _ in range(4)))
        self.assertEqual(asyncio.run(renew()), ["access-secret"] * 4)
        refreshes = [r for r in self.requests if b"grant_type=refresh_token" in r.content]
        self.assertEqual(len(refreshes), 1)
        record = self.connection.record()
        record["accounts"]["oaiapp_test"]["expires_at"] = 0
        self.connection.save(record)
        self.fail_refresh = True
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.access_token())
        self.assertEqual(self.connection.record(), record)

    def test_disconnect_revokes_and_keeps_registration(self):
        self.connect()
        result = asyncio.run(self.connection.disconnect())
        self.assertEqual(result["message"], "ChatGPT disconnected.")
        self.assertFalse(self.connection.status()["connected"])
        record = self.connection.record()["accounts"]["oaiapp_test"]
        self.assertNotIn("refresh_token", record)
        self.assertEqual(record["client_id"], "oaiapp_test")
        self.assertNotIn("id_token_hint", self.attempt("oaiapp_test"))

    def test_stream_completion_and_tool_evidence_saved(self):
        self.connect()
        config = fixture_config()
        config["ai"] = {"provider": "chatgpt", "model": "test-model"}
        self.store.save_config(config)
        cid = self.store.new_conversation()
        class Service:
            def __init__(self, _):
                pass
            async def read(self, service, path, params):
                return {"source": "https://github.com/team/repo", "data": "evidence"}
        async def run():
            return [e async for e in run_turn(self.store, cid, "Explain the repo",
                services_factory=Service, chatgpt=self.connection)]
        self.response_mode = "tool"
        events = asyncio.run(run())
        self.assertIn("source", [e["event"] for e in events])
        self.assertEqual(events[-1]["event"], "done")
        self.assertIn("evidence", json.dumps(self.store.history(cid)))
        for mode in ("interrupted", "usage_error"):
            other = self.store.new_conversation()
            self.response_mode = mode
            async def fail():
                return [e async for e in run_turn(self.store, other, "Explain", chatgpt=self.connection)]
            with self.assertRaises(ValueError):
                asyncio.run(fail())
            self.assertEqual(self.store.history(other), [])

    def test_read_mode_explains_missing_settings_without_exposing_write_tool_or_tokens(self):
        self.connect()
        config = fixture_config()
        config["ai"] = {"provider": "chatgpt", "model": "test-model"}
        config["allow_writes"] = False
        config["github"]["token"] = ""
        self.store.save_config(config)
        cid = self.store.new_conversation()
        async def run():
            return [e async for e in run_turn(self.store, cid, "Create a GitHub issue",
                chatgpt=self.connection)]
        events = asyncio.run(run())
        self.assertFalse(any(e["event"] == "action" for e in events))
        request = next(r for r in self.requests if r.url.path == "/v1/responses")
        payload = json.loads(request.content)
        self.assertEqual([t["name"] for t in payload["tools"][0]["tools"]], ["api_read", "configure_repository"])
        instructions = payload["instructions"]
        self.assertIn('"change_proposals_enabled": false', instructions)
        self.assertIn('"github": false', instructions)
        self.assertIn("Allow the assistant to prepare changes", instructions)
        self.assertIn("add its token in Settings", instructions)
        for secret in ("jira-private-token", "jenkins-private-token"):
            self.assertNotIn(secret, instructions)

    def test_http_callback_cross_site_exception_is_narrow_and_requires_csrf_start(self):
        app = create_app(self.store, demo=False, chatgpt_transport=self.transport)
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            self.assertEqual(client.post("/api/chatgpt/start", json={}).status_code, 401)
            login = client.post("/api/login", json={"password": self.store.password})
            self.assertEqual(client.post("/api/chatgpt/start", json={}).status_code, 403)
            headers = {"X-CSRF-Token": login.json()["csrf"]}
            started = client.post("/api/chatgpt/start", json={}, headers=headers)
            query = {k: v[0] for k, v in parse_qs(urlsplit(started.json()["url"]).query).items()}
            self.nonce = query["nonce"]
            client.cookies.clear()  # SameSite Strict cookie is absent on the OAuth redirect.
            callback = client.get("/auth/callback", params={"state": query["state"], "code": "code",
                "client_id": "oaiapp_test"}, headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False)
            self.assertEqual(callback.status_code, 303)
            self.assertEqual(callback.headers["location"], "/?chatgpt=connected")
            navigation_headers = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate",
                                  "Sec-Fetch-Dest": "document"}
            landing = client.get(callback.headers["location"], headers=navigation_headers)
            self.assertEqual(landing.status_code, 200)
            self.assertIn('id="settingsDialog"', landing.text)
            self.assertEqual(client.get("/api/state", headers=navigation_headers).status_code, 403)
            self.assertEqual(client.post("/api/settings", json={}, headers=navigation_headers).status_code, 403)
            self.assertEqual(client.get("/", headers={"Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"}).status_code, 403)
            self.assertEqual(client.get("/api/state", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
            self.assertEqual(client.get("/auth/callback", params={"state": "bad"},
                headers={"Sec-Fetch-Site": "cross-site"}, follow_redirects=False).headers["location"], "/?chatgpt=failed")
        self.assertFalse(OAuthLogFilter().filter(logging.LogRecord("test", 20, "", 0,
            'GET /auth/callback?code=secret', (), None)))

    def test_chatgpt_proposes_but_does_not_execute_writes(self):
        self.connect()
        config = fixture_config()
        config["ai"] = {"provider": "chatgpt", "model": "test-model"}
        self.store.save_config(config)
        cid = self.store.new_conversation()
        class Service:
            def __init__(self, _):
                pass
            async def prepare(self, service, operation, payload):
                return {"method": "POST", "path": "/repos/team/repo/issues", "body": payload}
            async def execute(self, _):
                raise AssertionError("Model executed an unconfirmed write")
        self.response_mode = "proposal"
        async def run():
            return [e async for e in run_turn(self.store, cid, "Propose an issue",
                services_factory=Service, chatgpt=self.connection)]
        events = asyncio.run(run())
        card = next(e["action"] for e in events if e["event"] == "action")
        self.assertEqual(card["status"], "pending")
        self.assertEqual(self.store.action(card["id"])["status"], "pending")

    def test_account_switch_or_disconnect_stops_existing_turn(self):
        self.connect()
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.access_token("oaiapp_other"))
        asyncio.run(self.connection.disconnect())
        with self.assertRaises(ValueError):
            asyncio.run(self.connection.access_token("oaiapp_test"))

    def test_auto_routes_chatgpt_to_available_analysis_and_counts_both_calls(self):
        self.connect()
        self.extra_model = True
        config = fixture_config()
        config["ai"] = {"provider": "chatgpt", "model": "test-model", "analysis_model": "analysis-model"}
        self.store.save_config(config)
        cid = self.store.new_conversation()
        async def run():
            return [e async for e in run_turn(self.store, cid, "Debug the failure", chatgpt=self.connection)]
        events = asyncio.run(run())
        payloads = [json.loads(r.content) for r in self.requests if r.url.path == "/v1/responses"]
        self.assertEqual([p["model"] for p in payloads], ["test-model", "analysis-model"])
        self.assertEqual(events[-1]["usage"], {"input_tokens": 10, "output_tokens": 6})
        self.assertEqual(events[-1]["by_model"]["analysis-model"]["input_tokens"], 5)
        metadata = json.loads(self.store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
        self.assertEqual(metadata["model"], "analysis-model")

    def test_manual_unavailable_analysis_fails_without_inference(self):
        self.connect()
        config = fixture_config()
        config["ai"] = {"provider": "chatgpt", "model": "test-model", "analysis_model": "not-in-catalog"}
        self.store.save_config(config)
        cid = self.store.new_conversation()
        async def run():
            return [e async for e in run_turn(self.store, cid, "Debug", chatgpt=self.connection, model_mode="analysis")]
        with self.assertRaisesRegex(ValueError, "Analysis model is unavailable"):
            asyncio.run(run())
        self.assertFalse(any(r.url.path == "/v1/responses" for r in self.requests))
