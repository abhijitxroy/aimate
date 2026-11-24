"""Archive persistence and attachment display metadata without external calls."""
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from test_app import create_app, fixture_config
from app.store import Store


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.client = TestClient(create_app(self.store))
        self.headers = {"X-CSRF-Token": self.client.post(
            "/api/login", json={"password": self.store.password}).json()["csrf"]}
        self.group = self.store.create_group("Project")
        self.cid = self.store.new_conversation("Investigation", self.group)
        self.store.save_turn(self.cid, [{"role": "user", "content": "Keep this context"}])

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def test_archive_restore_preserves_history_pin_and_group_after_restart(self):
        before = self.store.history(self.cid)
        endpoint = f"/api/conversations/{self.cid}"
        response = self.client.patch(endpoint, headers=self.headers,
                                     json={"archived": True, "pinned": True})
        self.assertEqual(response.status_code, 200)
        row = self.client.get("/api/state").json()["conversations"][0]
        self.assertEqual((row["archived"], row["pinned"], row["group_id"]),
                         (1, 1, self.group))
        reopened = Store(self.directory.name)
        self.assertEqual(reopened.history(self.cid), before)
        self.assertEqual(reopened.rows("SELECT archived FROM conversation_archives")[0]["archived"], 1)
        reopened.db.close()
        self.assertEqual(self.client.get(endpoint).status_code, 200)
        self.assertEqual(self.client.patch(endpoint, headers=self.headers,
                                          json={"archived": False}).status_code, 200)
        self.assertEqual(self.client.get("/api/state").json()["conversations"][0]["archived"], 0)
        self.assertEqual(self.store.history(self.cid), before)
        self.assertEqual(self.client.patch(endpoint, json={"archived": True}).status_code, 403)
        self.assertEqual(self.client.patch(endpoint, headers=self.headers,
                                          json={"archived": "false"}).status_code, 400)
        self.client.delete(endpoint, headers=self.headers)
        self.assertEqual(self.store.rows("SELECT * FROM conversation_archives"), [])

    def test_attachment_metadata_keeps_full_model_context_and_usage(self):
        received = []

        async def answer(store, cid, question, **kwargs):
            received.append(question)
            store.save_turn(cid, [
                {"role": "user", "content": question},
                {"role": "assistant", "content": [{"type": "text", "text": "Read the file."}]}],
                {"model": "test-model", "usage": {"input_tokens": 10, "output_tokens": 3}})
            yield {"event": "done"}

        question = "Explain this\nAttached file: demo.txt\nline one\nline two"
        payload = {"conversation": self.cid, "question": question,
                   "display_question": "Explain this",
                   "attachments": [{"name": "demo.txt", "size": 17}]}
        with patch("app.main.run_turn", answer):
            response = self.client.post("/api/chat", headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(received, [question])
        turn = self.client.get(f"/api/conversations/{self.cid}").json()["turns"][-1]
        self.assertEqual(turn["messages"][0]["content"], question)
        self.assertEqual(turn["usage"]["display_question"], "Explain this")
        self.assertEqual(turn["usage"]["attachments"], payload["attachments"])
        self.assertEqual(turn["usage"]["usage"]["input_tokens"], 10)
        invalid = dict(payload, attachments=[{"name": "demo.txt", "size": -1}])
        self.assertEqual(self.client.post("/api/chat", headers=self.headers, json=invalid).status_code, 400)

    def test_custom_icon_persists_and_can_return_to_automatic(self):
        endpoint = f"/api/conversations/{self.cid}"
        before = self.store.history(self.cid)
        self.assertEqual(self.client.patch(endpoint, headers=self.headers, json={"icon": "🚀"}).status_code, 200)
        reopened = Store(self.directory.name)
        self.assertEqual(reopened.rows("SELECT icon FROM conversation_icons")[0]["icon"], "🚀")
        reopened.db.close()
        self.assertEqual(self.client.get("/api/state").json()["conversations"][0]["icon"], "🚀")
        self.assertEqual(self.store.history(self.cid), before)
        self.assertEqual(self.client.patch(endpoint, headers=self.headers, json={"icon": "text"}).status_code, 400)
        self.assertEqual(self.client.patch(endpoint, headers=self.headers, json={"icon": "CI"}).status_code, 200)
        self.assertEqual(self.client.get("/api/state").json()["conversations"][0]["icon"], "CI")
        self.assertEqual(self.client.patch(endpoint, headers=self.headers, json={"icon": None}).status_code, 200)
        self.assertIsNone(self.client.get("/api/state").json()["conversations"][0]["icon"])

    def test_saved_history_search_includes_archived_unicode_and_visible_messages(self):
        self.store.save_turn(self.cid, [
            {"role": "user", "content": "Investigate ONEAPICI-8437"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "School 🌸\nBuild #11 completed successfully."},
                {"type": "tool_use", "name": "read", "input": {"private": "hidden-tool-marker"}}]},
            {"role": "user", "content": [{"type": "tool_result", "content": "hidden-result-marker"}]}])
        self.client.patch(f"/api/conversations/{self.cid}", headers=self.headers, json={"archived": True})
        for query in ("oneapici-8437", "build successfully", "🌸", "Investigation"):
            response = self.client.get("/api/history/search", params={"q": query})
            self.assertEqual(response.status_code, 200)
            found = response.json()["results"]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["id"], self.cid)
            self.assertTrue(found[0]["archived"])
            self.assertEqual(found[0]["area"], "Project")
        self.assertEqual(self.client.get("/api/history/search", params={"q": "hidden-tool-marker"}).json()["results"], [])
        self.assertEqual(self.client.get("/api/history/search", params={"q": "hidden-result-marker"}).json()["results"], [])
        self.assertEqual(self.client.get("/api/history/search", params={"q": ""}).json()["results"], [])
        self.assertEqual(self.client.get("/api/history/search", params={"q": "x" * 201}).status_code, 400)
        self.client.post("/api/logout", headers=self.headers)
        self.assertEqual(self.client.get("/api/history/search", params={"q": "build"}).status_code, 401)
