import json
import os
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from app.documents import save
from app.maintenance import preview,apply
from test_app import Store,create_app


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
    def tearDown(self):
        self.store.db.close();self.temp.cleanup()
    def document(self,cid,name):
        return save(self.store,cid,[{"name":name,"text":"owned attachment evidence","size":25,"kind":"text","notice":""}])[0]["id"]

    def test_only_unreferenced_orphans_expired_cache_and_old_rotated_log_are_removed(self):
        live=self.store.new_conversation()
        protected=self.document(live,"live.txt")
        orphan=self.document("deleted-chat","orphan.txt")
        referenced=self.document("old-chat","referenced.txt")
        revision=self.document("edited-chat","revision.txt")
        self.store.save_turn(live,[{"role":"user","content":"Saved reference "+referenced}])
        self.store.execute("INSERT INTO conversation_revisions(conversation,encrypted,created) VALUES (?,?,?)",
            ("edited-chat",self.store.cipher.encrypt(b"snapshot").decode(),time.time()))
        for ident,expires in (("expired",time.time()-1),("fresh",time.time()+300)):
            self.store.execute("INSERT INTO evidence_cache VALUES (?,?,?,?)",
                (ident,self.store.cipher.encrypt(b"{}").decode(),time.time(),expires))
        log=self.store.directory/"requests.jsonl.1";log.write_text("old diagnostic")
        os.utime(log,(time.time()-8*86400,time.time()-8*86400))
        backup=self.store.directory/"before-encryption.backup";backup.write_bytes(b"synthetic protected backup")
        plan=preview(self.store)
        self.assertEqual([r["id"] for r in plan["documents"]],[orphan])
        self.assertEqual(apply(self.store,plan["fingerprint"]),{"documents":1,"expired_cache":1,"logs":1,"skipped_logs":0})
        remaining={r["id"] for r in self.store.rows("SELECT id FROM documents")}
        self.assertEqual(remaining,{protected,referenced,revision})
        self.assertTrue(backup.exists());self.assertFalse(log.exists())
        self.assertEqual(self.store.rows("SELECT id FROM evidence_cache")[0]["id"],"fresh")
        self.assertEqual(len(self.store.history(live)),1)

    def test_changed_dependencies_reject_cleanup_before_any_delete(self):
        self.document("restored-chat","keep.txt")
        plan=preview(self.store)
        self.store.execute("INSERT INTO conversations VALUES (?,?,?)",("restored-chat","Restored",time.time()))
        with self.assertRaisesRegex(ValueError,"dependencies changed"):apply(self.store,plan["fingerprint"])
        self.assertEqual(self.store.rows("SELECT count(*) AS n FROM documents")[0]["n"],1)

    def test_http_review_expiry_and_viewer_access(self):
        with TestClient(create_app(self.store)) as client:
            csrf=client.post("/api/login",json={"password":self.store.password}).json()["csrf"]
            headers={"X-CSRF-Token":csrf}
            self.assertEqual(client.post("/api/maintenance/cleanup",headers=headers,json={"fingerprint":"not-reviewed"}).status_code,400)
            plan=client.get("/api/maintenance").json()
            self.assertEqual(client.post("/api/maintenance/cleanup",headers=headers,json={"fingerprint":plan["fingerprint"]}).status_code,200)
            self.assertEqual(client.post("/api/maintenance/cleanup",headers=headers,json={"fingerprint":plan["fingerprint"]}).status_code,400)
            grant=client.post("/api/access/grants",headers=headers,json={"name":"Read only","role":"viewer"}).json()
            client.post("/api/access/login",json={"role":"viewer","code":grant["code"]})
            self.assertEqual(client.get("/api/maintenance").status_code,403)
