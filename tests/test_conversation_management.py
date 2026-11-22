"""Conversation names and deletion preserve other chats and completed audit records."""
import tempfile
import unittest

from fastapi.testclient import TestClient

from test_app import create_app, fixture_config
from app.store import Store


class ConversationManagementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.client = TestClient(create_app(self.store))
        self.headers = {"X-CSRF-Token": self.client.post("/api/login", json={"password": self.store.password}).json()["csrf"]}
        self.cid = self.store.new_conversation("Original")
        self.store.save_turn(self.cid, [{"role": "user", "content": "Question"},
                                       {"role": "assistant", "content": [{"type": "text", "text": "**Answer**"}]}],
                             {"model": "test-model", "usage": {"input_tokens": 10, "output_tokens": 5}})

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def test_rename_persists_without_changing_messages(self):
        before = self.client.get(f"/api/conversations/{self.cid}").json()["turns"]
        result = self.client.patch(f"/api/conversations/{self.cid}", headers=self.headers, json={"title": " New title "})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get(f"/api/conversations/{self.cid}").json()["title"], "New title")
        self.assertEqual(self.client.get(f"/api/conversations/{self.cid}").json()["turns"], before)
        self.assertEqual(self.client.get("/api/state").json()["conversations"][0]["title"], "New title")

    def test_rename_rejects_invalid_names_and_requires_csrf(self):
        for title in ("", " ", "x" * 101, 123):
            self.assertEqual(self.client.patch(f"/api/conversations/{self.cid}", headers=self.headers,
                                              json={"title": title}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/conversations/{self.cid}", json={"title": "New"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/conversations/{self.cid}").status_code, 403)

    def test_delete_removes_chat_data_but_preserves_other_chats_and_audit(self):
        other = self.store.new_conversation("Keep me")
        self.store.save_turn(other, [{"role": "user", "content": "Keep this"}])
        self.store.execute("INSERT INTO audit(action,status,result,created) VALUES ('previous-action','completed','{}',1)")
        result = self.client.delete(f"/api/conversations/{self.cid}", headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get(f"/api/conversations/{self.cid}").status_code, 400)
        self.assertEqual(self.store.rows("SELECT * FROM turn_usage"), [])
        self.assertEqual(len(self.store.history(other)), 1)
        self.assertEqual(len(self.client.get("/api/audit").json()["entries"]), 1)
        self.assertEqual(self.client.delete(f"/api/conversations/{self.cid}", headers=self.headers).status_code, 400)

    def test_delete_refuses_running_action(self):
        self.store.execute("INSERT INTO actions(id,conversation,status) VALUES ('running',?,'executing')", (self.cid,))
        self.assertEqual(self.client.delete(f"/api/conversations/{self.cid}", headers=self.headers).status_code, 409)
        self.assertTrue(self.store.history(self.cid))
