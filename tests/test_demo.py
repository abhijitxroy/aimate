"""Exercise the demo through HTTP, including confirmation and network isolation."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

_import_directory = tempfile.TemporaryDirectory()
os.environ["APP_DATA_DIR"] = _import_directory.name
from app.main import app as entrypoint, create_app
from app.store import Store


def tearDownModule():
    if str(entrypoint.state.store.directory) == _import_directory.name:
        entrypoint.state.store.db.close()
    _import_directory.cleanup()


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.app = create_app(self.store, demo=True)
        self.client = TestClient(self.app)
        self.network = patch("httpx.AsyncHTTPTransport.handle_async_request",
                             side_effect=AssertionError("Demo attempted an external network request"))
        self.network.start()
        login = self.client.post("/api/demo/login")
        self.assertEqual(login.status_code, 200)
        self.headers = {"X-CSRF-Token": login.json()["csrf"]}
        self.cid = self.client.post("/api/conversations", headers=self.headers).json()["id"]

    def tearDown(self):
        self.network.stop()
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def chat(self, question):
        response = self.client.post("/api/chat", headers=self.headers,
                                    json={"conversation": self.cid, "question": question})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertNotIn("error", [e["event"] for e in events], events)
        return events

    def proposal(self, question):
        return next(e["action"] for e in self.chat(question) if e["event"] == "action")

    def test_failure_has_evidence_and_no_ai_charge(self):
        events = self.chat("Why did the build fail?")
        answer = "".join(e["delta"] for e in events if e["event"] == "text")
        self.assertIn("DEMO", answer)
        self.assertIn("unexpected keyword argument", answer)
        self.assertGreaterEqual(sum(e["event"] == "source" for e in events), 4)
        self.assertEqual(events[-1]["usage"], {"input_tokens": 0, "output_tokens": 0})
        self.assertEqual(len(self.client.get(f"/api/conversations/{self.cid}").json()["turns"]), 1)

    def test_comment_only_changes_fixture_after_confirmation_once(self):
        card = self.proposal("Propose a Jira comment with the build failure evidence")
        backend = self.app.state.demo_backend
        self.assertEqual(backend.comments, [])
        url = f"/api/actions/{card['id']}/confirm"
        self.assertEqual(self.client.post(url).status_code, 403)
        result = self.client.post(url, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "completed")
        self.assertTrue(result.json()["result"]["simulated"])
        self.assertEqual(len(backend.comments), 1)
        self.assertEqual(self.client.post(url, headers=self.headers).status_code, 409)
        answer = "".join(e.get("delta", "") for e in self.chat("Show issues and comments"))
        self.assertIn("1 simulated Jira comments", answer)
        self.assertEqual(len(self.client.get("/api/audit").json()["entries"]), 2)

    def test_github_issue_and_jenkins_queue_are_simulated(self):
        for prompt in ("Create a sample GitHub issue", "Trigger the demo build"):
            card = self.proposal(prompt)
            result = self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()["result"]["simulated"])
        self.assertEqual(len(self.app.state.demo_backend.github_issues), 1)
        self.assertEqual(len(self.app.state.demo_backend.queued), 1)

    def test_cancellation_settings_and_scope_guards(self):
        card = self.proposal("Propose a Jira comment")
        result = self.client.post(f"/api/actions/{card['id']}/cancel", headers=self.headers)
        self.assertEqual(result.json()["status"], "cancelled")
        self.assertEqual(self.app.state.demo_backend.comments, [])
        self.assertEqual(self.client.put("/api/settings", headers=self.headers,
                                        json={"github": {"token": "real-token"}}).status_code, 409)
        self.assertEqual(self.store.config()["github"]["repos"], ["demo/sample-service"])
        import asyncio
        services = self.app.state.demo_backend.services(self.store.config())
        with self.assertRaises(ValueError):
            asyncio.run(services.read("github", "/repos/real/private"))

    def test_demo_login_never_available_in_live_mode(self):
        live = create_app(self.store, demo=False)
        with TestClient(live) as client:
            self.assertEqual(client.get("/api/mode").json(), {
                "demo": False, "hosted": False, "otp_enabled": False, "environment":"development", "dev_login": False})
            self.assertEqual(client.post("/api/demo/login").status_code, 404)
            self.assertEqual(client.get("/api/state").status_code, 401)

    def test_architecture_unknown_prompt_and_connection_test(self):
        answer = "".join(e.get("delta", "") for e in self.chat("Explain the repository architecture"))
        self.assertIn("POST /orders", answer)
        answer = "".join(e.get("delta", "") for e in self.chat("What's the weather?"))
        self.assertIn("Other questions require live mode", answer)
        result = self.client.post("/api/connections/ai/test", headers=self.headers).json()
        self.assertTrue(result["simulated"])
        self.assertTrue(self.client.get("/api/state").json()["demo"])
