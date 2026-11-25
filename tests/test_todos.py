"""Task persistence, validation and authenticated mutations."""
import tempfile
import unittest

from fastapi.testclient import TestClient
from test_app import create_app
from app.store import Store


class TodoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.client = TestClient(create_app(self.store))
        self.headers = {"X-CSRF-Token": self.client.post(
            "/api/login", json={"password": self.store.password}).json()["csrf"]}

    def tearDown(self):
        self.client.close()
        self.store.db.close()
        self.directory.cleanup()

    def test_lifecycle_and_reopening(self):
        result = self.client.post("/api/todos", headers=self.headers, json={"title": " Review PR "})
        self.assertEqual(result.status_code, 200)
        task_id = result.json()["id"]
        self.assertEqual(self.client.patch(f"/api/todos/{task_id}", headers=self.headers,
            json={"title": "Review tests", "completed": True}).status_code, 200)
        reopened = Store(self.directory.name)
        task = reopened.rows("SELECT * FROM todos")[0]
        self.assertEqual((task["title"], task["completed"]), ("Review tests", 1))
        reopened.db.close()
        self.assertEqual(self.client.patch(f"/api/todos/{task_id}", headers=self.headers,
            json={"completed": False}).status_code, 200)
        self.assertEqual(self.client.get("/api/todos").json()["tasks"][0]["completed"], 0)
        self.assertEqual(self.client.delete(f"/api/todos/{task_id}", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/api/todos").json()["tasks"], [])

    def test_validation_and_csrf(self):
        for title in ("", " ", "x" * 6001, 123):
            self.assertEqual(self.client.post("/api/todos", headers=self.headers,
                json={"title": title}).status_code, 400)
        self.assertEqual(self.client.post("/api/todos", json={"title": "Protected"}).status_code, 403)
        task_id = self.client.post("/api/todos", headers=self.headers, json={"title": "Keep"}).json()["id"]
        for payload in ({}, {"completed": "false"}, {"unknown": True}, {"title": ""}):
            self.assertEqual(self.client.patch(f"/api/todos/{task_id}", headers=self.headers,
                json=payload).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/todos/{task_id}").status_code, 403)
        self.assertEqual(self.client.patch("/api/todos/missing", headers=self.headers,
            json={"completed": True}).status_code, 400)
        self.assertEqual(self.client.get("/api/todos").json()["tasks"][0]["title"], "Keep")

    def test_multiline_text_is_preserved(self):
        text = "Release checklist\n- Read logs\n  - Check warnings\n\nFollow up with the PR owner."
        result = self.client.post("/api/todos", headers=self.headers, json={"title": text})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get("/api/todos").json()["tasks"][0]["title"], text)
        changed = text + "\n- Publish notes"
        self.client.patch("/api/todos/" + result.json()["id"], headers=self.headers, json={"title": changed})
        self.assertEqual(self.client.get("/api/todos").json()["tasks"][0]["title"], changed)

    def test_type_persists_without_changing_legacy_task_rows_and_invalid_type_is_rejected(self):
        self.store.execute("INSERT INTO todos VALUES (?,?,0,?,?)",("legacy","Legacy task",1,1))
        self.assertEqual(self.client.get("/api/todos").json()["tasks"][0]["type"],"task")
        ident=self.client.post("/api/todos",headers=self.headers,json={"title":"Investigate\n- logs","type":"bug"}).json()["id"]
        self.assertEqual(self.client.patch("/api/todos/"+ident,headers=self.headers,json={"type":"triage"}).status_code,200)
        reopened=Store(self.directory.name)
        self.assertEqual(reopened.rows("SELECT kind FROM todo_types WHERE id=?",(ident,))[0]["kind"],"triage")
        reopened.db.close()
        for invalid in ("unknown",None,[],True):
            self.assertEqual(self.client.patch("/api/todos/"+ident,headers=self.headers,json={"type":invalid}).status_code,400)
        self.assertEqual(self.client.get("/api/todos").json()["tasks"][0]["title"],"Investigate\n- logs")
        self.client.delete("/api/todos/"+ident,headers=self.headers)
        self.assertEqual(self.store.rows("SELECT * FROM todo_types"),[])
