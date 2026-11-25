import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.store import Store
from test_app import create_app,fixture_config


class FeedbackReviewTests(unittest.TestCase):
    def test_review_evidence_redaction_task_idempotency_reopen_and_source_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.save_config(fixture_config())
            cid=store.new_conversation();store.save_turn(cid,[{"role":"user","content":"Test"},{"role":"assistant","content":[{"type":"text","text":"Answer"}]}])
            turn=store.rows("SELECT id FROM turns")[0]["id"]
            with TestClient(create_app(store)) as client:
                login=client.post("/api/login",json={"password":store.password}).json();headers={"X-CSRF-Token":login["csrf"]}
                ident=client.post("/api/feedback",headers=headers,json={"conversation":cid,"turn":turn,"rating":"negative","category":"accuracy","comment":"Needs a fix"}).json()["saved"]
                url=f"/api/feedback/{ident}/review"
                review={"state":"investigating","assessment":"confirmed_issue","reply":"","evidence":""}
                self.assertEqual(client.patch(url,headers=headers,json=review).status_code,400)
                secret=store.config()["github"]["token"];review.update(evidence="Reproduced in fixture",reply="Investigating "+secret)
                self.assertEqual(client.patch(url,headers=headers,json=review).status_code,200)
                self.assertNotIn(secret,client.get("/api/feedback/reviews").text)
                first=client.post(f"/api/feedback/{ident}/task",headers=headers).json()
                second=client.post(f"/api/feedback/{ident}/task",headers=headers).json()
                self.assertEqual(first["id"],second["id"]);self.assertTrue(second["existing"])
                self.assertEqual(store.rows("SELECT COUNT(*) AS n FROM todos")[0]["n"],1)
                self.assertEqual(store.rows("SELECT kind FROM todo_types")[0]["kind"],"bug")
                with store.db:
                    store.db.execute("DELETE FROM turns WHERE id=?",(turn,))
                review.update(state="resolved",reply="Fixed in the tested build")
                self.assertEqual(client.patch(url,headers=headers,json=review).status_code,200)
                self.assertEqual(client.patch("/api/feedback/unknown/review",headers=headers,json=review).status_code,400)
            store.db.close();store=Store(directory)
            self.assertEqual(store.rows("SELECT state FROM feedback_reviews")[0]["state"],"resolved")
            self.assertEqual(store.rows("SELECT reply FROM feedback_reviews")[0]["reply"],"Fixed in the tested build")
            store.db.close()

    def test_viewer_read_only_workspace_isolation_and_disabled_feature_preserves_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.execute("INSERT INTO feedback VALUES ('f','c',1,'positive','helpful','Useful',1,'admin')")
            app=create_app(store)
            auth=next(r.dependant.dependencies[0].call for r in app.routes if getattr(r,"path","") == "/api/feedback/reviews")
            app.dependency_overrides[auth]=lambda:{"role":"viewer"}
            with TestClient(app) as client:
                self.assertFalse(client.get("/api/feedback/reviews").json()["can_review"])
                self.assertEqual(client.patch("/api/feedback/f/review",json={"state":"closed","assessment":"helpful","reply":"","evidence":""}).status_code,403)
            with tempfile.TemporaryDirectory() as other:
                isolated=Store(other)
                with TestClient(create_app(isolated)) as client:
                    client.post("/api/login",json={"password":isolated.password})
                    self.assertEqual(client.get("/api/feedback/reviews").json()["entries"],[])
                isolated.db.close()
            with patch.dict("os.environ",{"AIMATE_FEEDBACK_REVIEW_ENABLED":"0"}):
                with TestClient(create_app(store)) as client:
                    client.post("/api/login",json={"password":store.password})
                    self.assertEqual(client.get("/api/feedback/reviews").status_code,404)
                    self.assertEqual(len(client.get("/api/feedback").json()["entries"]),1)
            store.db.close()
