"""Boundary and workflow tests: no external network, credentials or AI billing."""
import asyncio
import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

# Avoid creating a real user workspace while importing the ASGI entrypoint.
_import_directory = tempfile.TemporaryDirectory()
os.environ["APP_DATA_DIR"] = _import_directory.name
from app.agent import propose
from app.connectors import Services, clean_path, scrub, scoped_jql
from app.main import app as entrypoint, create_app, validate_config
from app.store import Store


def tearDownModule():
    entrypoint.state.store.db.close()
    _import_directory.cleanup()


def fixture_config():
    return {
        "allow_writes": True,
        "ai": {"provider": "anthropic", "model": "test-model", "api_key": "ai-private-token"},
        "github": {"url": "https://github.example/api/v3", "token": "github-private-token", "repos": ["team/repo"]},
        "jira": {"url": "https://jira.example", "token": "jira-private-token", "auth": "bearer",
                 "api_version": "2", "projects": ["DEMO"]},
        "jenkins": {"url": "https://jenkins.example", "token": "jenkins-private-token",
                    "username": "operator", "jobs": ["team/build"]},
    }


class FakeBlock:
    def __init__(self, **value):
        self.value = value

    def model_dump(self, **kwargs):
        return self.value


class FakeStream:
    def __init__(self, stage):
        self.stage = stage

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    @property
    def text_stream(self):
        async def stream():
            if self.stage >= 2:
                yield "DEMO-123 is blocked by a failed build. "
                yield "I prepared a Jira comment for your confirmation."
        return stream()

    async def get_final_message(self):
        if self.stage == 0:
            content = [FakeBlock(type="tool_use", id="read1", name="api_read",
                                 input={"service": "jira", "path": "/rest/api/2/issue/DEMO-123"})]
        elif self.stage == 1:
            content = [FakeBlock(type="tool_use", id="propose1", name="propose_action",
                                 input={"service": "jira", "operation": "comment_issue",
                                        "payload": {"issue": "DEMO-123", "body": "Build failed; inspect the log."},
                                        "reason": "Record the observed failure"})]
        else:
            content = [FakeBlock(type="text", text="DEMO-123 is blocked. Comment proposed.")]
        return SimpleNamespace(content=content, usage=SimpleNamespace(input_tokens=100, output_tokens=20))


class FakeAI:
    def __init__(self, config):
        self.stage = 0
        self.messages = self

    def stream(self, **kwargs):
        # Assert credentials are never sent as context.
        packed = json.dumps(kwargs)
        for token in ("ai-private-token", "github-private-token", "jira-private-token", "jenkins-private-token"):
            if token in packed:
                raise AssertionError("Credential leaked to model context")
        current = self.stage
        self.stage += 1
        return FakeStream(current)

    async def close(self):
        pass


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.requests = []
        self.file_sha = "a" * 40
        self.fail_writes = False

        def remote(request):
            self.requests.append(request)
            if request.method != "GET":
                if self.fail_writes:
                    raise httpx.ReadTimeout("Connection lost after submission", request=request)
                return httpx.Response(201, json={"id": "new-comment", "body": "Build failed; inspect the log."})
            if request.url.path.endswith("/crumbIssuer/api/json"):
                return httpx.Response(200, json={"crumbRequestField": "Jenkins-Crumb", "crumb": "test-crumb"})
            if request.url.path.endswith("/contents/app.py"):
                return httpx.Response(200, json={"sha": self.file_sha, "encoding": "base64",
                                                 "content": base64.b64encode(b"old code\n").decode()})
            if "/repos/" in request.url.path:
                return httpx.Response(200, json={"default_branch": "main", "name": "repo"})
            return httpx.Response(200, json={"key": "DEMO-123", "fields": {"summary": "Build failed"}})

        self.transport = httpx.MockTransport(remote)
        self.services = lambda config: Services(config, self.transport)
        self.app = create_app(self.store, services_factory=self.services, client_factory=FakeAI)
        self.client = TestClient(self.app)
        result = self.client.post("/api/login", json={"password": self.store.password})
        self.assertEqual(result.status_code, 200)
        self.csrf = {"X-CSRF-Token": result.json()["csrf"]}
        self.cid = self.client.post("/api/conversations", headers=self.csrf).json()["id"]

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def card(self, service="jira", operation="comment_issue", payload=None):
        payload = payload or {"issue": "DEMO-123", "body": "A reviewed comment"}
        return asyncio.run(propose(self.store, self.store.config(), self.services(self.store.config()), self.cid,
                                   {"service": service, "operation": operation, "payload": payload, "reason": "test"}))

    def test_login_and_csrf_boundary(self):
        anonymous = TestClient(self.app)
        self.assertEqual(anonymous.get("/api/state").status_code, 401)
        self.assertEqual(self.client.post("/api/conversations").status_code, 403)
        self.assertEqual(self.client.post("/api/conversations", headers={
            **self.csrf, "Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/state", headers={"Host": "evil.example"}).status_code, 400)
        anonymous.close()

    def test_hosted_https_origin_cookie_and_csrf(self):
        with patch.dict(os.environ, {"APP_PUBLIC_URL": "https://aimate.example",
                                     "APP_PASSWORD": "test-host-password"}):
            hosted = create_app(self.store, services_factory=self.services, client_factory=FakeAI)
        with TestClient(hosted, base_url="https://aimate.example") as client:
            result = client.post("/api/login", json={"password": self.store.password},
                                 headers={"Origin": "https://aimate.example"})
            self.assertEqual(result.status_code, 200)
            cookie = result.headers["set-cookie"].lower()
            self.assertIn("secure", cookie)
            self.assertIn("httponly", cookie)
            self.assertIn("samesite=strict", cookie)
            headers = {"Origin": "https://aimate.example", "X-CSRF-Token": result.json()["csrf"]}
            self.assertEqual(client.post("/api/conversations", headers=headers).status_code, 200)
            self.assertEqual(client.post("/api/conversations", headers={"Origin": "https://aimate.example"}).status_code, 403)
            self.assertEqual(client.post("/api/conversations", headers={**headers, "Origin": "http://aimate.example"}).status_code, 403)
            self.assertEqual(client.post("/api/conversations", headers={**headers, "Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(client.get("/healthz").json(), {"status": "ok"})
            self.assertTrue(client.get("/api/mode").json()["hosted"])

    def test_hosted_mode_requires_password_and_origin(self):
        for url, password in [("http://aimate.example", "long-password"),
                              ("https://aimate.example/path", "long-password"),
                              ("https://aimate.example", "")]:
            with patch.dict(os.environ, {"APP_PUBLIC_URL": url, "APP_PASSWORD": password}):
                with self.assertRaises(ValueError):
                    create_app(self.store)

    def test_public_github_reads_without_token_stay_scoped(self):
        config = fixture_config()
        config["github"] = {"url": "https://api.github.com", "repos": ["team/repo"], "token": ""}
        service = Services(config, self.transport)
        result = asyncio.run(service.read("github", "/repos/team/repo/contents/app.py"))
        self.assertEqual(result["data"]["text"], "old code\n")
        self.assertNotIn("authorization", self.requests[-1].headers)
        with self.assertRaises(ValueError):
            asyncio.run(service.read("github", "/repos/other/repo"))
        with self.assertRaises(ValueError):
            service.plan("github", "create_issue", {"repo": "team/repo", "title": "No token"})
        with self.assertRaises(ValueError):
            asyncio.run(service.request("github", "POST", "/repos/team/repo/issues", body={"title": "No token"}))
        config["github"]["url"] = "https://github.example/api/v3"
        with self.assertRaises(ValueError):
            service.section("github")

    def test_github_can_be_configured_and_checked_before_ai(self):
        config = fixture_config()
        config["ai"] = {"provider": "anthropic", "model": "", "clear_token": True}
        config["github"] = {"url": "https://api.github.com", "repos": ["team/repo"], "clear_token": True}
        saved = self.client.put("/api/settings", json=config, headers=self.csrf)
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(saved.json()["config"]["ai"]["api_key_configured"])
        checked = self.client.post("/api/connections/github/test", headers=self.csrf)
        self.assertEqual(checked.status_code, 200)
        self.assertTrue(checked.json()["ok"])
        self.assertEqual(checked.json()["targets"], [{"target": "team/repo", "ok": True}])
        self.assertNotIn("authorization", self.requests[-1].headers)

    def test_tokens_encrypted_and_not_returned(self):
        raw = (Path(self.directory.name) / "app.sqlite3").read_bytes()
        self.assertNotIn(b"github-private-token", raw)
        public = self.client.get("/api/state").text
        self.assertNotIn("private-token", public)
        self.assertTrue(self.client.get("/api/state").json()["config"]["github"]["token_configured"])

    def test_token_preserved_and_explicitly_cleared(self):
        raw = fixture_config()
        raw["github"]["token"] = ""
        new = validate_config(raw, self.store.config())
        self.assertEqual(new["github"]["token"], "github-private-token")
        raw["github"]["clear_token"] = True
        self.assertEqual(validate_config(raw, self.store.config())["github"]["token"], "")

    def test_chat_fetches_then_proposes_without_writing(self):
        response = self.client.post("/api/chat", headers=self.csrf,
                                    json={"conversation": self.cid, "question": "Explain DEMO-123 and propose a comment"})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertTrue(any(e["event"] == "source" for e in events))
        self.assertTrue(any(e["event"] == "action" for e in events))
        self.assertTrue(any(e["event"] == "done" for e in events))
        self.assertTrue(all(r.method == "GET" for r in self.requests))
        history = self.client.get(f"/api/conversations/{self.cid}").json()
        self.assertEqual(len(history["turns"]), 1)
        self.assertEqual(history["actions"][0]["status"], "pending")

    def test_confirmation_writes_exact_body_once(self):
        card = self.card()
        self.assertEqual(len(self.requests), 0)
        endpoint = f"/api/actions/{card['id']}/confirm"
        result = self.client.post(endpoint, headers=self.csrf)
        self.assertEqual(result.json()["status"], "completed")
        self.assertEqual(json.loads(self.requests[-1].content), {"body": "A reviewed comment"})
        self.assertEqual(self.requests[-1].url.path, "/rest/api/2/issue/DEMO-123/comment")
        self.assertEqual(self.client.post(endpoint, headers=self.csrf).status_code, 409)
        self.assertEqual(sum(r.method != "GET" for r in self.requests), 1)
        self.assertEqual(len(self.client.get("/api/audit").json()["entries"]), 2)

    def test_cancel_never_writes(self):
        card = self.card()
        result = self.client.post(f"/api/actions/{card['id']}/cancel", headers=self.csrf)
        self.assertEqual(result.json()["status"], "cancelled")
        self.assertEqual(self.requests, [])

    def test_expired_and_changed_settings_block_write(self):
        card = self.card()
        self.store.execute("UPDATE actions SET created=? WHERE id=?", (time.time() - 1900, card["id"]))
        self.assertEqual(self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.csrf).status_code, 409)
        other = self.card()
        self.store.save_config(fixture_config())
        self.assertEqual(self.client.post(f"/api/actions/{other['id']}/confirm", headers=self.csrf).status_code, 409)
        self.assertEqual(self.requests, [])

    def test_transport_failure_not_replayed(self):
        card = self.card()
        self.fail_writes = True
        endpoint = f"/api/actions/{card['id']}/confirm"
        self.assertEqual(self.client.post(endpoint, headers=self.csrf).json()["status"], "unknown")
        self.assertEqual(self.client.post(endpoint, headers=self.csrf).status_code, 409)
        self.assertEqual(len(self.requests), 1)

    def test_file_preview_and_stale_sha(self):
        card = self.card("github", "write_file", {"repo": "team/repo", "branch": "fix/demo",
                         "path": "app.py", "message": "Fix bug", "content": "new code\n", "sha": self.file_sha})
        self.assertEqual(card["preview"]["preview"]["previous"], "old code\n")
        self.assertEqual(card["preview"]["preview"]["proposed"], "new code\n")
        self.file_sha = "b" * 40
        self.assertEqual(self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.csrf).status_code, 400)
        self.assertTrue(all(r.method == "GET" for r in self.requests))

    def test_default_branch_write_blocked(self):
        with self.assertRaisesRegex(ValueError, "default branch"):
            self.card("github", "write_file", {"repo": "team/repo", "branch": "main", "path": "app.py",
                                             "message": "Fix", "content": "x", "sha": self.file_sha})
        self.assertTrue(all(r.method == "GET" for r in self.requests))

    def test_scope_and_path_bypasses_refused(self):
        service = self.services(self.store.config())
        for path in ["/repos/team/other/issues", "/repos/team/repo/actions/secrets", "//evil.example",
                     "/repos/team/repo/contents/%2e%2e/file", "/repos/team%2Frepo/issues",
                     "/repos/team/repo/contents/%252e%252e/file"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                asyncio.run(service.read("github", path))
        with self.assertRaises(ValueError):
            asyncio.run(service.read("jira", "/rest/api/2/issue/OTHER-123"))
        with self.assertRaises(ValueError):
            asyncio.run(service.read("jenkins", "/job/other/api/json"))
        self.assertEqual(self.requests, [])

    def test_jenkins_build_uses_crumb_and_correct_form(self):
        card = self.card("jenkins", "build_job", {"job": "team/build", "parameters": {"BRANCH": "fix/demo"}})
        result = self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.csrf)
        self.assertEqual(result.json()["status"], "completed")
        self.assertEqual(self.requests[-1].url.path, "/job/team/job/build/buildWithParameters")
        self.assertEqual(self.requests[-1].headers["Jenkins-Crumb"], "test-crumb")
        self.assertEqual(self.requests[-1].content, b"BRANCH=fix%2Fdemo")

    def test_writes_disabled_blocks_proposals(self):
        config = fixture_config()
        config["allow_writes"] = False
        self.store.save_config(config)
        with self.assertRaisesRegex(ValueError, "Enable change proposals"):
            self.card()


class QueryTests(unittest.TestCase):
    def test_jql_scope_is_not_escapable(self):
        self.assertEqual(scoped_jql("status = Open OR assignee = currentUser() ORDER BY updated DESC", ["DEMO"]),
                         "project IN (DEMO) AND (status = Open OR assignee = currentUser()) ORDER BY updated DESC")
        self.assertEqual(scoped_jql('summary ~ "order by something"', ["DEMO"]),
                         'project IN (DEMO) AND (summary ~ "order by something")')
        for query in ["status=Open) OR project=OTHER OR (status=Open", 'summary ~ "unterminated', "(status=Open"]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                scoped_jql(query, ["DEMO"])

    def test_redaction_and_cloud_description(self):
        config = fixture_config()
        self.assertEqual(scrub({"text": "token github-private-token", "password": "hidden"}, config),
                         {"text": "token [redacted]", "password": "[redacted]"})
        config["jira"]["api_version"] = "3"
        plan = Services(config).plan("jira", "comment_issue", {"issue": "DEMO-123", "body": "First\nSecond"})
        self.assertEqual(plan["body"]["body"]["type"], "doc")
        self.assertEqual(len(plan["body"]["body"]["content"]), 2)

    def test_https_and_invalid_settings(self):
        raw = fixture_config()
        raw["jira"]["url"] = "http://jira.example"
        with self.assertRaises(ValueError):
            validate_config(raw, {})
        with self.assertRaises(ValueError):
            clean_path("/repos/team/repo/contents/../secret")


if __name__ == "__main__":
    unittest.main()
