import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from test_app import Store, create_app, fixture_config, FakeAI
from app.vault import read, redactions
from app.connectors import scrub
from app.agent import run_turn, tools_for


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.app=create_app(self.store)
        self.client=TestClient(self.app)
        self.headers={"x-csrf-token":self.client.post("/api/login",json={"password":self.store.password}).json()["csrf"]}

    def tearDown(self):
        self.client.close();self.store.db.close();self.directory.cleanup()

    def test_vault_encryption_ai_opt_in_and_redaction(self):
        secret="a-unique-vault-private-value"
        result=self.client.post("/api/vault",headers=self.headers,json={"name":"Test secret","value":secret})
        self.assertEqual(result.status_code,200)
        ident=result.json()["id"]
        self.assertNotIn(secret,json.dumps(self.store.rows("SELECT * FROM vault_entries")))
        self.assertNotIn(secret,json.dumps(self.client.get("/api/vault").json()))
        self.assertEqual(self.client.post(f"/api/vault/{ident}/reveal",headers=self.headers).json()["value"],secret)
        with self.assertRaises(ValueError):read(self.store,"Test secret",ai=True)
        self.client.patch(f"/api/vault/{ident}",headers=self.headers,json={"name":"Test secret","value":secret,"ai_access":True})
        self.assertEqual(read(self.store,"Test secret",ai=True),secret)
        config={**fixture_config(),"_vault_secrets":redactions(self.store)}
        self.assertEqual(scrub("Secret "+secret,config),"Secret [redacted]")
        self.assertNotIn("read_vault_entry",{tool["name"] for tool in tools_for({**config,"_role":"viewer","allow_writes":False})})

    def test_private_transcript_is_session_only_no_search_index_or_preview_persistence(self):
        cid=self.client.post("/api/conversations",headers=self.headers,json={"private":True}).json()["id"]
        async def answer(store,cid,question,**kwargs):
            self.assertTrue(store.config()["_private"])
            self.assertEqual({t["name"] for t in tools_for(store.config())},{"api_read"})
            store.save_turn(cid,[{"role":"user","content":question},{"role":"assistant","content":[{"type":"text","text":"Private reply"}]}],{"model":"test"})
            store.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",(question,cid))
            yield {"event":"done"}
        with patch("app.main.run_turn",answer):
            result=self.client.post("/api/chat",headers=self.headers,json={"conversation":cid,"question":"uniquely-private-question"})
        self.assertEqual(result.status_code,200)
        self.assertEqual(len(self.client.get("/api/conversations/"+cid).json()["turns"]),1)
        for table in ("conversations","turns","memory_index","attachment_previews"):
            self.assertNotIn("uniquely-private-question",json.dumps(self.store.rows("SELECT * FROM "+table)))
        other=TestClient(self.app)
        other.post("/api/login",json={"password":self.store.password})
        self.assertEqual(other.get("/api/conversations/"+cid).status_code,400)
        other.close()
        self.client.post("/api/logout",headers=self.headers)
        self.headers={"x-csrf-token":self.client.post("/api/login",json={"password":self.store.password}).json()["csrf"]}
        self.assertEqual(self.client.get("/api/conversations/"+cid).status_code,400)

    def test_feedback_validates_saved_turn_and_scrubs_credentials(self):
        cid=self.store.new_conversation("Feedback")
        self.store.save_turn(cid,[{"role":"user","content":"hello"},{"role":"assistant","content":[{"type":"text","text":"hi"}]}])
        turn=self.store.rows("SELECT id FROM turns")[0]["id"]
        payload={"conversation":cid,"turn":turn,"rating":"negative","category":"accuracy","comment":"Wrong result github-private-token"}
        response=self.client.post("/api/feedback",headers=self.headers,json=payload)
        self.assertEqual(response.status_code,200)
        self.assertNotIn("github-private-token",self.client.get("/api/feedback").text)
        self.assertEqual(self.client.post("/api/feedback",headers=self.headers,json={**payload,"turn":999}).status_code,400)
        self.assertEqual(self.client.post("/api/feedback",headers=self.headers,json={**payload,"rating":"bad"}).status_code,400)
