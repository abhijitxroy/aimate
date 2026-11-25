"""Task priorities preserve legacy text, safety, disabled mode and persistence."""
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.store import Store
from test_app import create_app,fixture_config


class TodoPriorityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name);self.store.save_config(fixture_config())
        self.client=TestClient(create_app(self.store))
        session=self.client.post("/api/login",json={"password":self.store.password}).json()
        self.headers={"X-CSRF-Token":session["csrf"]}

    def tearDown(self):
        self.client.close();self.store.db.close();self.temp.cleanup()

    def add(self,body):
        return self.client.post("/api/todos",json=body,headers=self.headers)

    def test_legacy_defaults_and_priority_edit_preserve_multiline_task_and_restart(self):
        ident=self.add({"title":"First line\n- Keep notes","type":"bug"}).json()["id"]
        self.assertEqual(self.client.get("/api/todos").json()["tasks"][0]["priority"],"P2")
        self.assertEqual(self.client.patch("/api/todos/"+ident,headers=self.headers,
                                          json={"priority":"P0"}).status_code,200)
        reopened=Store(self.temp.name)
        self.assertEqual(reopened.rows("SELECT priority FROM todo_priorities WHERE id=?",(ident,))[0]["priority"],"P0")
        self.assertEqual(reopened.rows("SELECT title FROM todos")[0]["title"],"First line\n- Keep notes")
        reopened.db.close()
        self.client.delete("/api/todos/"+ident,headers=self.headers)
        self.assertFalse(self.store.rows("SELECT * FROM todo_priorities"))

    def test_invalid_priority_never_creates_or_partially_updates_task(self):
        for value in ("P4","p0",True,3,[],None):
            self.assertEqual(self.add({"title":"Reject","priority":value}).status_code,400)
        self.assertFalse(self.store.rows("SELECT * FROM todos"))
        ident=self.add({"title":"Keep this","priority":"P1"}).json()["id"]
        self.assertEqual(self.client.patch("/api/todos/"+ident,headers=self.headers,
            json={"title":"Wrong replacement","priority":"P9"}).status_code,400)
        self.assertEqual(self.store.rows("SELECT title FROM todos")[0]["title"],"Keep this")
        self.assertEqual(self.client.patch("/api/todos/"+ident,json={"priority":"P0"}).status_code,403)

    def test_disabled_priorities_keep_core_operations_and_saved_metadata(self):
        ident=self.add({"title":"Keep metadata","priority":"P0"}).json()["id"]
        with patch.dict(os.environ,{"AIMATE_TODO_PRIORITIES_ENABLED":"0"}):
            self.assertEqual(self.client.get("/api/todos").json()["priorities"],[])
            self.assertEqual(self.add({"title":"Core task"}).status_code,200)
            self.assertEqual(self.add({"title":"No priority writes","priority":"P1"}).status_code,400)
            self.assertEqual(self.client.patch("/api/todos/"+ident,headers=self.headers,
                                              json={"title":"Renamed core task"}).status_code,200)
        self.assertEqual(self.store.rows("SELECT priority FROM todo_priorities")[0]["priority"],"P0")

