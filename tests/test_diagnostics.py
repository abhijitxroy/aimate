import json
import logging
import tempfile
import unittest
from fastapi.testclient import TestClient
from test_app import Store,create_app
from app.main import OAuthLogFilter
from app.request_trace import append


class DiagnosticTests(unittest.TestCase):
    def test_request_ids_redaction_and_bounded_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with TestClient(create_app(store)) as client:
                login=client.post("/api/login",json={"password":store.password})
                self.assertEqual(len(login.headers["X-Request-ID"]),16)
                response=client.get("/api/history/search",params={"q":"private-search-marker"})
                self.assertEqual(response.status_code,200)
                trace=store.directory/"requests.jsonl"
                content=trace.read_text()
                self.assertNotIn(store.password,content)
                self.assertNotIn("private-search-marker",content)
                rows=[json.loads(line) for line in content.splitlines()]
                self.assertTrue(all(set(row)=={"id","created","method","route","status","duration_ms","complete"} for row in rows))
                trace.write_text("x"*1_000_001)
                append(store.directory,{"synthetic":"record"})
                self.assertTrue((store.directory/"requests.jsonl.1").exists())
                self.assertLess(trace.stat().st_size,100)
            store.db.close()
        self.assertFalse(OAuthLogFilter().filter(logging.LogRecord("uvicorn.access",20,"",0,"raw query",(),None)))

    def test_personal_viewer_is_denied_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with TestClient(create_app(store)) as client:
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"]
                self.assertEqual(client.get("/api/diagnostics").status_code,200)
                issued=client.post("/api/access/grants",headers={"X-CSRF-Token":csrf},json={"name":"Viewer","role":"viewer"}).json()
                login=client.post("/api/access/login",json={"role":"viewer","code":issued["code"]}).json()
                self.assertEqual(client.get("/api/diagnostics").status_code,403)
                headers={"X-CSRF-Token":login["csrf"]}
                self.assertEqual(client.post("/api/attachments/document",headers=headers,
                    json={"name":"note.txt","data":"aGVsbG8="}).status_code,200)
                self.assertEqual(client.post("/api/usage/budget",headers=headers,
                    json={"monthly_usd":10,"mode":"warn"}).status_code,200)
                self.assertFalse(store.rows("SELECT body FROM usage_preferences"))
            store.db.close()
