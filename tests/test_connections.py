"""Connection reports, independent saves and stale-status handling."""
import asyncio
import tempfile
import time
import unittest
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from app.connection_checks import check_connection
from app.connectors import Services
from app.store import Store
from test_app import create_app, fixture_config


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.denied = None
        self.calls = []

        def remote(request):
            self.calls.append(request)
            if self.denied and self.denied in request.url.path:
                return httpx.Response(403, json={"secret": "NEVER RETURN THIS BODY"})
            if request.url.path.endswith(("/user", "/myself", "/whoAmI/api/json")):
                return httpx.Response(200, json={"login": "test-user", "name": "test-user", "authenticated": True})
            return httpx.Response(200, json={"private": True, "default_branch": "main",
                                            "permissions": {"push": True}, "name": "Project",
                                            "fullName": "team/build", "buildable": True})
        transport = httpx.MockTransport(remote)
        self.services = lambda cfg: Services(cfg, transport)
        self.client = TestClient(create_app(self.store, services_factory=self.services))
        login = self.client.post("/api/login", json={"password": self.store.password}).json()
        self.headers = {"X-CSRF-Token": login["csrf"]}

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def test_github_checks_real_capabilities_and_persists_report(self):
        report = self.client.post("/api/connections/github/test", headers=self.headers).json()
        self.assertTrue(report["ok"])
        target = report["targets"][0]
        self.assertEqual(len(target["checks"]), 4)
        self.assertIn("Repository reports push access.", target["details"])
        self.assertTrue(all(r.method == "GET" for r in self.calls))
        state = self.client.get("/api/state").json()
        self.assertEqual(state["connection_checks"]["github"]["status"], "passed")
        for token in ("github-private-token", "ai-private-token"):
            self.assertNotIn(token, str(state))

    def test_partial_access_is_red_and_does_not_leak_error_body(self):
        self.denied = "/actions/runs"
        report = self.client.post("/api/connections/github/test", headers=self.headers).json()
        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["targets"][0]["checks"][-1]["name"], "Actions")
        self.assertIn("HTTP 403", report["targets"][0]["checks"][-1]["message"])
        self.assertNotIn("NEVER RETURN THIS BODY", str(report))

    def test_missing_connection_is_failed_with_remedy(self):
        self.store.save_config({"ai": {}, "github": {}, "jira": {}, "jenkins": {}})
        report = self.client.post("/api/connections/jira/test", headers=self.headers).json()
        self.assertFalse(report["ok"])
        self.assertIn("token", report["message"])

    def test_invalid_token_stops_before_target_checks(self):
        self.denied = "/user"
        report = self.client.post("/api/connections/github/test", headers=self.headers).json()
        self.assertFalse(report["ok"])
        self.assertIn("HTTP 403", report["message"])
        self.assertFalse(report["targets"])

    def test_section_save_preserves_other_connections_and_checks(self):
        self.client.post("/api/connections/github/test", headers=self.headers)
        result = self.client.put("/api/settings/jira", headers=self.headers,
                                 json={"url": "https://jira.example", "projects": ["OTHER"], "auth": "bearer", "api_version": "2"})
        self.assertEqual(result.status_code, 200)
        cfg = self.store.config()
        self.assertEqual(cfg["github"]["token"], "github-private-token")
        self.assertEqual(cfg["jira"]["token"], "jira-private-token")
        self.assertEqual(self.store.connection_checks()["github"]["status"], "passed")

    def test_editing_checked_connection_invalidates_green(self):
        self.client.post("/api/connections/github/test", headers=self.headers)
        self.client.put("/api/settings/github", headers=self.headers,
                        json={"url": "https://github.example/api/v3", "repos": ["team/other"]})
        self.assertEqual(self.store.connection_checks()["github"]["status"], "unchecked")

    def test_checking_unchanged_settings_does_not_invalidate_proposals(self):
        body = {"url": "https://github.example/api/v3", "repos": ["team/repo"]}
        self.client.put("/api/settings/github", headers=self.headers, json=body)
        version = self.store.config()["_version"]
        self.client.put("/api/settings/github", headers=self.headers, json=body)
        self.assertEqual(self.store.config()["_version"], version)

    def test_expired_check_is_not_green(self):
        cfg = self.store.config()
        self.store.save_connection_check("github", cfg, {"status": "passed", "checked_at": time.time() - 3601})
        self.assertEqual(self.store.connection_checks()["github"]["status"], "unchecked")

    def test_bad_repo_explains_expected_format(self):
        result = self.client.put("/api/settings/github", headers=self.headers,
                                 json={"url": "https://api.github.com", "repos": ["https://github.com/team"]})
        self.assertEqual(result.status_code, 400)
        self.assertIn("OWNER/REPO", result.json()["detail"])

    def test_organization_url_save_uses_api_and_keeps_token(self):
        result = self.client.put("/api/settings/github", headers=self.headers,
                                 json={"url": "https://github.com/intel-innersource/",
                                       "repos": ["abhijitxroy/aimate", "frameworks.devops.oneapi.ci"],
                                       "token": ""})
        self.assertEqual(result.status_code, 200)
        saved = self.store.config()["github"]
        self.assertEqual(saved["url"], "https://api.github.com")
        self.assertEqual(saved["repos"], ["abhijitxroy/aimate", "intel-innersource/frameworks.devops.oneapi.ci"])
        self.assertEqual(saved["token"], "github-private-token")

    def test_other_services_return_actual_target_details(self):
        for service in ("jira", "jenkins"):
            with self.subTest(service=service):
                report = self.client.post(f"/api/connections/{service}/test", headers=self.headers).json()
                self.assertTrue(report["ok"])
                self.assertTrue(report["targets"][0]["details"])

    def test_ai_returns_answer_and_always_closes(self):
        class AI:
            def __init__(self):
                self.messages = self
                self.closed = False
            async def create(self, **kwargs):
                return SimpleNamespace(model="verified-model", content=[SimpleNamespace(type="text", text="OK")])
            async def close(self):
                self.closed = True
        client = AI()
        report = asyncio.run(check_connection("ai", fixture_config(), None, lambda cfg: client, None))
        self.assertTrue(report["ok"])
        self.assertIn("Reply: OK", report["details"])
        self.assertTrue(client.closed)

    def test_chatgpt_check_is_honest_about_no_inference(self):
        class Account:
            async def models(self):
                return [{"slug": "test-model", "display_name": "Test model"}]
        cfg = fixture_config()
        cfg["ai"]["provider"] = "chatgpt"
        report = asyncio.run(check_connection("ai", cfg, None, None, Account()))
        self.assertTrue(report["ok"])
        self.assertIn("an AI answer was not requested", report["details"][-1])

    def test_jenkins_token_rotation_keeps_controller_and_username(self):
        old = self.store.config()["jenkins"]
        response = self.client.put("/api/settings/jenkins", headers=self.headers, json={"token": "replacement-jenkins-token"})
        self.assertEqual(response.status_code, 200)
        updated = self.store.config()["jenkins"]
        self.assertEqual(updated["url"], old["url"])
        self.assertEqual(updated["username"], old["username"])
        self.assertEqual(updated["token"], "replacement-jenkins-token")
        self.assertNotIn("replacement-jenkins-token", str(response.json()))

    def test_github_token_save_survives_reload_and_repository_edit(self):
        old = self.store.config()["github"]
        response = self.client.put("/api/settings/github", headers=self.headers,
                                   json={"token": "replacement-github-token"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("replacement-github-token", str(response.json()))
        reopened = Store(self.directory.name)
        try:
            saved = reopened.config()["github"]
            self.assertEqual(saved["token"], "replacement-github-token")
            self.assertEqual(saved["url"], old["url"])
            self.assertEqual(saved["repos"], old["repos"])
        finally:
            reopened.db.close()
        response = self.client.put("/api/settings/github", headers=self.headers,
                                   json={"repos": ["team/other"], "token": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.config()["github"]["token"], "replacement-github-token")
        self.assertTrue(self.client.get("/api/state").json()["config"]["github"]["token_configured"])

    def test_unknown_service_and_csrf_are_rejected(self):
        self.assertEqual(self.client.post("/api/connections/other/test", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.put("/api/settings/github", json={}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
