"""Ask-bar source settings use saved credentials and reviewed, validated changes."""
import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from test_app import create_app, fixture_config, FakeAI, FakeStream, FakeBlock
from app.agent import tools_for, run_turn
from app.connectors import Services
from app.repository_settings import propose_repository, repository_name
from app.store import Store


class RepositorySettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        config = fixture_config()
        config["allow_writes"] = False
        self.store.save_config(config)
        self.denied = False
        self.requests = []

        def remote(request):
            self.requests.append(request)
            if self.denied:
                return httpx.Response(403, json={"secret": "PRIVATE UPSTREAM BODY"})
            if request.url.path.endswith("/user"):
                return httpx.Response(200, json={"login": "operator"})
            return httpx.Response(200, json={"default_branch": "main", "permissions": {"push": False}})

        transport = httpx.MockTransport(remote)
        self.factory = lambda cfg: Services(cfg, transport)
        self.client = TestClient(create_app(self.store, services_factory=self.factory))
        self.headers = {"X-CSRF-Token": self.client.post("/api/login", json={"password": self.store.password}).json()["csrf"]}
        self.cid = self.store.new_conversation()

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def proposal(self, **args):
        return asyncio.run(propose_repository(self.store, self.store.config(), self.cid, args, self.factory))

    def test_read_mode_can_validate_then_confirm_without_remote_writes(self):
        names = {tool["name"] for tool in tools_for(self.store.config())}
        self.assertIn("configure_repository", names)
        self.assertNotIn("propose_action", names)
        card = self.proposal(repo="team/new-repo")
        self.assertEqual(self.store.config()["github"]["repos"], ["team/repo"])
        self.assertNotIn("github-private-token", json.dumps(card))
        response = self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "completed")
        self.assertEqual(self.store.config()["github"]["repos"], ["team/repo", "team/new-repo"])
        self.assertEqual(self.store.config()["github"]["token"], "github-private-token")
        self.assertTrue(all(r.method == "GET" for r in self.requests))
        self.assertEqual(self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.headers).status_code, 409)

    def test_replace_preserves_other_settings(self):
        card = self.proposal(repo="team/new-repo", replace="team/repo")
        self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.headers).raise_for_status()
        self.assertEqual(self.store.config()["github"]["repos"], ["team/new-repo"])
        self.assertEqual(self.store.config()["jira"]["token"], "jira-private-token")

    def test_retry_reuses_pending_card_but_rechecks_access(self):
        first = self.proposal(repo="team/new-repo")
        count = len(self.requests)
        second = self.proposal(repo="https://github.example/team/new-repo")
        self.assertEqual(first["id"], second["id"])
        self.assertGreater(len(self.requests), count)
        self.assertEqual(len(self.store.rows("SELECT id FROM actions")), 1)
        self.denied = True
        with self.assertRaises(ValueError):
            self.proposal(repo="team/new-repo")
        self.assertEqual(self.store.config()["github"]["repos"], ["team/repo"])

    def test_bad_ai_request_is_recorded_without_credentials_and_does_not_mark_connection_failed(self):
        import anthropic
        class RejectAI:
            def __init__(self, cfg):
                self.messages = self
            def stream(self, **kwargs):
                response = httpx.Response(400, request=httpx.Request("POST", "https://bedrock.example"))
                raise anthropic.BadRequestError("PRIVATE BODY", response=response,
                                               body={"Message": "prompt is too long PRIVATE BODY"})
            async def close(self):
                pass
        self.store.save_connection_check("ai", self.store.config(),
                                         {"status": "passed", "checked_at": 1, "message": "Connected"})
        with TestClient(create_app(self.store, client_factory=RejectAI)) as client:
            csrf = client.post("/api/login", json={"password": self.store.password}).json()["csrf"]
            result = client.post("/api/chat", headers={"X-CSRF-Token": csrf},
                                 json={"conversation": self.cid, "question": "Add a repository"})
        self.assertIn("context limit", result.text)
        failures = self.store.rows("SELECT * FROM ai_failures")
        self.assertEqual(len(failures), 1)
        self.assertIn(failures[0]["id"], result.text)
        self.assertNotIn("PRIVATE BODY", result.text + json.dumps(failures))
        self.assertEqual(self.store.connection_checks()["ai"]["status"], "passed")

    def test_ask_bar_tool_produces_review_card(self):
        class RepositoryStream(FakeStream):
            async def get_final_message(self):
                block = (FakeBlock(type="tool_use", id="repo1", name="configure_repository", input={"repo": "team/new-repo"})
                         if self.stage == 0 else FakeBlock(type="text", text="Access checked. Confirm the card to add it."))
                return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=100, output_tokens=20))

        class RepositoryAI(FakeAI):
            def stream(self, **kwargs):
                stream = RepositoryStream(self.stage)
                self.stage += 1
                return stream

        async def collect():
            return [event async for event in run_turn(self.store, self.cid, "Add team/new-repo to my sources",
                     client_factory=RepositoryAI, services_factory=self.factory)]

        events = asyncio.run(collect())
        self.assertEqual(next(e["action"]["status"] for e in events if e["event"] == "action"), "pending")
        self.assertEqual(self.store.config()["github"]["repos"], ["team/repo"])
        self.assertEqual(events[-1]["event"], "done")

    def test_denied_access_creates_no_proposal(self):
        self.denied = True
        with self.assertRaisesRegex(ValueError, "Repository was not added"):
            self.proposal(repo="team/denied")
        self.assertEqual(self.store.rows("SELECT * FROM actions"), [])
        self.assertEqual(self.store.config()["github"]["repos"], ["team/repo"])

    def test_confirmation_rechecks_access(self):
        card = self.proposal(repo="team/new-repo")
        self.denied = True
        response = self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("PRIVATE UPSTREAM BODY", response.text)
        self.assertEqual(self.store.config()["github"]["repos"], ["team/repo"])

    def test_changed_settings_and_cancel_prevent_save(self):
        card = self.proposal(repo="team/new-repo")
        config = self.store.config()
        config["github"]["token"] = "new-saved-token"
        self.store.save_config(config)
        self.assertEqual(self.client.post(f"/api/actions/{card['id']}/confirm", headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(f"/api/actions/{card['id']}/cancel", headers=self.headers).json()["status"], "cancelled")
        self.assertEqual(self.store.config()["github"]["repos"], ["team/repo"])

    def test_duplicates_invalid_names_and_other_hosts_are_rejected(self):
        for args in ({"repo": "TEAM/REPO"}, {"repo": "../repo"}, {"repo": "team/repo/pull/1"},
                     {"repo": "https://other.example/team/repo"}, {"repo": "team/new", "replace": "team/missing"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.proposal(**args)
        self.assertEqual(self.requests, [])
        config = self.store.config()
        config["github"]["url"] = "https://api.github.com"
        self.assertEqual(repository_name("https://github.com/abhijitxroy/aimate", config), "abhijitxroy/aimate")
