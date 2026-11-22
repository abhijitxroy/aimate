import asyncio
import unittest
import httpx
from app.validation import validate_config
from app.connectors import Services
from app.connection_checks import check_connection


def fixture_config():
    return {"ai": {}, "github": {}, "jenkins": {}, "jira": {
        "url": "https://jira.example", "token": "saved-pat", "auth": "bearer",
        "api_version": "2", "projects": ["DEMO"]}}


class JiraSimpleTests(unittest.TestCase):
    def config(self):
        old = fixture_config()
        raw = {**old, "jira": {"url": "https://jira.example", "token": "pat", "mode": "simple", "projects": ["OneAPI CI System"]}}
        return validate_config(raw, old)

    def test_simple_needs_no_keys_or_username(self):
        cfg = self.config()["jira"]
        self.assertEqual(cfg["access"], "all")
        self.assertEqual(cfg["projects"], [])
        self.assertEqual(cfg["auth"], "bearer")
        self.assertEqual(cfg["api_version"], "2")

    def test_discovery_verifies_pat_and_shows_names_and_keys(self):
        calls = []
        def remote(r):
            calls.append(r)
            if r.url.path.endswith("/myself"):
                return httpx.Response(200, json={"name": "operator"})
            return httpx.Response(200, json=[{"key": "ONEAPICI", "name": "OneAPI CI System"}])
        cfg = self.config()
        report = asyncio.run(check_connection("jira", cfg, Services(cfg, httpx.MockTransport(remote)), None, None))
        self.assertTrue(report["ok"])
        self.assertEqual(report["targets"][0]["target"], "ONEAPICI")
        self.assertEqual(report["targets"][0]["message"], "OneAPI CI System")
        self.assertTrue(all(r.headers["authorization"] == "Bearer pat" and r.method == "GET" for r in calls))
        self.assertNotIn("pat", str(report))

    def test_all_scope_reads_search_and_prepares_other_project(self):
        calls = []
        def remote(r):
            calls.append(r)
            return httpx.Response(200, json={"issues": [{"key": "OTHER-1"}]})
        service = Services(self.config(), httpx.MockTransport(remote))
        response = asyncio.run(service.read("jira", "/rest/api/2/search", {"jql": "status = Open"}))
        self.assertEqual(response["data"]["issues"][0]["key"], "OTHER-1")
        self.assertEqual(calls[0].url.params["jql"], "status = Open")
        asyncio.run(service.read("jira", "/rest/api/2/issue/OTHER-1"))
        plan = service.plan("jira", "create_issue", {"project": "OTHER", "summary": "Test"})
        self.assertEqual(plan["body"]["fields"]["project"]["key"], "OTHER")
        with self.assertRaises(ValueError):
            service.plan("jira", "create_issue", {"project": "Project Name", "summary": "Test"})

    def test_selected_scope_still_blocks_unlisted_projects(self):
        service = Services(fixture_config())
        with self.assertRaises(ValueError):
            service.issue("OTHER-1")
        with self.assertRaises(ValueError):
            asyncio.run(service.read("jira", "/rest/api/2/project"))

    def test_cloud_discovery_and_invalid_token(self):
        cfg = self.config()
        cfg["jira"].update(mode="advanced", auth="basic", username="a@example.com", api_version="3")
        def remote(r):
            if r.url.path.endswith("/myself"):
                return httpx.Response(200, json={"displayName": "Operator"})
            self.assertEqual(r.url.path, "/rest/api/3/project/search")
            return httpx.Response(200, json={"values": [{"key": "CLOUD", "name": "Cloud"}], "isLast": False})
        report = asyncio.run(check_connection("jira", cfg, Services(cfg, httpx.MockTransport(remote)), None, None))
        self.assertTrue(report["ok"])
        bad = Services(cfg, httpx.MockTransport(lambda r: httpx.Response(401, json={"private": "token"})))
        report = asyncio.run(check_connection("jira", cfg, bad, None, None))
        self.assertFalse(report["ok"])
        self.assertIn("invalid or expired", report["message"])
        self.assertEqual(report["targets"], [])

    def test_advanced_keys_and_jql_validation_remain_required(self):
        cfg = fixture_config()
        cfg["jira"].update(mode="advanced", access="selected", projects=["OneAPI CI System"])
        with self.assertRaisesRegex(ValueError, "project keys"):
            validate_config(cfg, fixture_config())
        with self.assertRaisesRegex(ValueError, "Unbalanced"):
            asyncio.run(Services(self.config()).read("jira", "/rest/api/2/search", {"jql": "status=Open) OR ("}))
