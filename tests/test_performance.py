"""Performance measurements use synthetic requests, not user prompts or models."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.performance import compare, observations, save_baseline, summarize
from test_app import Store, create_app, fixture_config


def record(duration, route="/api/chat", created=1, complete=True, status=200):
    return {"route":route,"duration_ms":duration,"created":created,"complete":complete,"status":status}


class PerformanceTests(unittest.TestCase):
    def test_percentiles_sections_traffic_and_incomplete_requests(self):
        data=summarize([record(i,created=i*60) for i in range(1,21)]+[
            record(900,complete=False,status=500),record(9,"/api/chatgpt/status"),
            record(8,"/api/todos/one"),record(10,"/api/chatty"),
            record(1,"/api/chat?secret=hidden"),record(float("nan")),None])
        chat=next(row for row in data["sections"] if row["section"]=="Chat")
        self.assertEqual((chat["p50_ms"],chat["p95_ms"]), (10,19))
        self.assertEqual((chat["errors"],chat["incomplete"]), (1,1))
        self.assertIsNotNone(chat["requests_per_minute"])
        self.assertEqual(data["ignored"],3)
        self.assertEqual({row["section"] for row in data["sections"]},{"Chat","Models","To-do","Other"})
        self.assertNotIn("secret",json.dumps(data))

    def test_baseline_changes_require_completed_samples_and_report_observations(self):
        before=summarize([record(200) for _ in range(5)])
        after=summarize([record(100) for _ in range(5)])
        self.assertEqual(compare(after,before)[0]["p95_change_percent"],-50)
        after=summarize([record(100) for _ in range(4)]+[record(5,complete=False)])
        self.assertIsNone(compare(after,before)[0]["p95_change_percent"])
        self.assertFalse(compare(after,before)[0]["comparable_sample"])

    def test_logs_are_bounded_malformed_and_linked_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root);log=directory/"requests.jsonl"
            log.write_text("\n".join([json.dumps(record(i)) for i in range(205)])+"\nbroken",encoding="utf-8")
            self.assertEqual(observations(directory)["requests"],200)
            log.write_bytes(b"x"*2_000_001)
            self.assertEqual(observations(directory)["requests"],0)
            log.unlink()
            try:log.symlink_to(directory/"outside.jsonl")
            except OSError:return
            (directory/"outside.jsonl").write_text(json.dumps(record(4)))
            self.assertEqual(observations(directory)["requests"],0)

    def test_http_permissions_csrf_server_measurements_and_restart(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);store.save_config(fixture_config())
            app=create_app(store)
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/performance").status_code,401)
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"]
                headers={"x-csrf-token":csrf}
                for _ in range(5):client.get("/api/todos")
                self.assertEqual(client.post("/api/performance/baselines",json={"label":"Before"}).status_code,403)
                for body in ({"label":"Before","p95_ms":1},{"label":"<script>"},{"label":fixture_config()["github"]["token"]}):
                    self.assertEqual(client.post("/api/performance/baselines",headers=headers,json=body).status_code,400)
                saved=client.post("/api/performance/baselines",headers=headers,json={"label":"Before cache"}).json()
                self.assertIn("id",saved)
                data=client.get("/api/performance",params={"baseline":saved["id"]}).json()
                self.assertEqual(data["baselines"][0]["label"],"Before cache")
                self.assertIn("resources",data["current"])
                self.assertNotIn("route",json.dumps(data))
                self.assertEqual(client.get("/api/performance?baseline=unknown").status_code,400)
            store.db.close()
            reopened=Store(root)
            self.assertEqual(reopened.rows("SELECT label FROM performance_baselines")[0]["label"],"Before cache")
            reopened.db.close()

    def test_disable_and_roles_leave_core_usable(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);store.save_config(fixture_config());app=create_app(store)
            with TestClient(app) as client:
                client.post("/api/login",json={"password":store.password})
                with patch.dict(os.environ,{"AIMATE_PERFORMANCE_ENABLED":"0"}):
                    self.assertEqual(client.get("/api/performance").status_code,404)
                    self.assertFalse(client.get("/api/state").json()["performance"])
                    self.assertEqual(client.get("/api/todos").status_code,200)
                grant=client.post("/api/access/grants",headers={"x-csrf-token":client.get("/api/state").json()["csrf"]},
                                  json={"name":"Perf viewer","role":"viewer","days":1})
                self.assertEqual(grant.status_code,200)
                from app.otp import code_for_counter
                other=TestClient(app)
                try:
                    login=other.post("/api/access/login",json={"role":"viewer","code":grant.json()["code"],
                        "otp":code_for_counter(grant.json()["authenticator_secret"],int(time.time()//30))})
                    self.assertEqual(login.status_code,200)
                    self.assertEqual(other.get("/api/performance").status_code,403)
                    self.assertEqual(other.get("/api/state").status_code,200)
                finally:other.close()
            store.db.close()

    def test_baseline_limit_preserves_existing_entries_and_token_snapshots(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);store.save_config(fixture_config())
            (Path(root)/"requests.jsonl").write_text(json.dumps(record(50)),encoding="utf-8")
            store.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?)",
                          ("test",time.time(),"test","model",json.dumps({"input_tokens":10,"output_tokens":2}),"chat"))
            first=save_baseline(store,Path(root),{"label":"Before"})
            body=json.loads(store.rows("SELECT body FROM performance_baselines WHERE id=?",(first["id"],))[0]["body"])
            self.assertEqual(body["reported_tokens_24h"]["input_tokens"],10)
            for i in range(24):save_baseline(store,Path(root),{"label":"Baseline "+str(i)})
            with self.assertRaisesRegex(ValueError,"25"):save_baseline(store,Path(root),{"label":"Extra"})
            self.assertEqual(store.rows("SELECT count(*) AS n FROM performance_baselines")[0]["n"],25)
            store.db.close()
