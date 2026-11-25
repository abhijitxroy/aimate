"""Temporary content never enters a saved workspace or another login session."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.private_chat import PrivateChat
from app.temporary_chats import prune
from test_app import Store, create_app, fixture_config


class TemporaryChatTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.app=create_app(self.store)
        self.client=TestClient(self.app)
        self.headers={"x-csrf-token":self.client.post("/api/login",json={"password":self.store.password}).json()["csrf"]}
        self.page="a"*32

    def tearDown(self):
        self.client.close();self.store.db.close();self.directory.cleanup()

    def create(self,lifetime="session",page=None):
        return self.client.post("/api/conversations",headers=self.headers,json={
            "private":True,"temporary":{"lifetime":lifetime,"page":page or self.page}})

    def test_page_close_discards_only_its_session_chats_and_requires_csrf(self):
        first=self.create().json()["id"]
        second=self.create(page="b"*32).json()["id"]
        day=self.create("day").json()["id"]
        self.assertEqual(self.client.post("/api/conversations/temporary-close",json={"page":self.page}).status_code,403)
        closed=self.client.post("/api/conversations/temporary-close",headers=self.headers,json={"page":self.page})
        self.assertEqual(closed.json(),{"closed":1})
        self.assertEqual(self.client.get("/api/conversations/"+first).status_code,400)
        self.assertEqual(self.client.get("/api/conversations/"+second).status_code,200)
        self.assertEqual(self.client.get("/api/conversations/"+day).status_code,200)
        self.assertEqual(len(self.store.rows("SELECT * FROM conversations")),0)

    def test_day_expiry_prunes_content_and_stops_future_saves(self):
        chat=PrivateChat(self.store,"private-synthetic","day",self.page)
        chat.save_turn(chat.ident,[{"role":"user","content":"temporary secret"}])
        chat.documents["doc"]={"text":"temporary file"}
        session={"private_chats":{chat.ident:chat}}
        prune(session,chat.expires+1)
        self.assertEqual(session["private_chats"],{})
        self.assertEqual(chat.turns,[])
        self.assertEqual(chat.documents,{})
        with self.assertRaises(ValueError):chat.save_turn(chat.ident,[{"role":"user","content":"late"}])
        with self.assertRaises(ValueError):chat.history(chat.ident)
        self.assertEqual(self.store.rows("SELECT * FROM turns"),[])

    def test_private_http_content_is_not_saved_searchable_or_shared(self):
        ident=self.create("day").json()["id"]
        async def answer(store,cid,question,**kwargs):
            store.save_turn(cid,[{"role":"user","content":question}])
            yield {"event":"done"}
        with patch("app.main.run_turn",answer):
            self.client.post("/api/chat",headers=self.headers,json={"conversation":ident,"question":"temporary unique sentinel"})
        result=self.client.get("/api/conversations/"+ident).json()
        self.assertEqual(len(result["turns"]),1)
        self.assertEqual(result["temporary"],"day")
        for table in ("turns","memory_index","documents","conversation_briefs"):
            self.assertEqual(self.store.rows("SELECT * FROM "+table),[])
        other=TestClient(self.app)
        try:
            header={"x-csrf-token":other.post("/api/login",json={"password":self.store.password}).json()["csrf"]}
            self.assertEqual(other.get("/api/conversations/"+ident).status_code,400)
            self.assertEqual(other.post("/api/conversations/temporary-close",headers=header,json={"page":self.page}).json(),{"closed":0})
        finally:other.close()
        self.client.post("/api/logout",headers=self.headers)
        self.client.post("/api/login",json={"password":self.store.password})
        self.assertEqual(self.client.get("/api/conversations/"+ident).status_code,400)

    def test_invalid_options_disabled_module_and_legacy_private_mode(self):
        for body in ({"lifetime":"forever","page":self.page},{"lifetime":"day","page":"../unsafe"},
                     {"lifetime":["day"],"page":self.page}):
            response=self.client.post("/api/conversations",headers=self.headers,json={"private":True,"temporary":body})
            self.assertEqual(response.status_code,400)
        for value in ("true",1,{}):
            self.assertEqual(self.client.post("/api/conversations",headers=self.headers,json={"private":value}).status_code,400)
        with patch.dict(os.environ,{"AIMATE_TEMPORARY_CHATS_ENABLED":"0"}):
            self.assertEqual(self.create().status_code,400)
            self.assertFalse(self.client.get("/api/state").json()["temporary_chats"])
            legacy=self.client.post("/api/conversations",headers=self.headers,json={"private":True})
            self.assertEqual(legacy.status_code,200)
            self.assertEqual(legacy.json()["temporary"],"legacy")

    def test_development_reload_reuses_session_without_extending_authority(self):
        with patch.dict(os.environ,{"AIMATE_DEV_LOGIN":"1"}):
            client=TestClient(self.app,base_url="http://127.0.0.1",client=("127.0.0.1",50000))
            try:
                first=client.post("/api/dev/login").json()["csrf"]
                token=client.cookies.get("project_session")
                created=client.post("/api/conversations",headers={"x-csrf-token":first},
                    json={"private":True,"temporary":{"lifetime":"day","page":self.page}}).json()["id"]
                self.assertEqual(client.post("/api/dev/login").json()["csrf"],first)
                self.assertEqual(client.cookies.get("project_session"),token)
                self.assertEqual(client.get("/api/conversations/"+created).status_code,200)
                with patch("app.main.time.time",return_value=time.time()+12*3600+1):
                    new=client.post("/api/dev/login").json()["csrf"]
                    self.assertNotEqual(new,first)
            finally:client.close()
