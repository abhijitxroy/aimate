"""Isolation tests use fictional credentials and never call external services."""
import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient
from test_app import create_app, fixture_config, Store


class PersonalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.app = create_app(self.store)
        self.admin = TestClient(self.app)
        self.headers = {"x-csrf-token": self.admin.post("/api/login", json={"password":self.store.password}).json()["csrf"]}
        self.users = []

    def user(self, name, role="viewer"):
        grant = self.admin.post("/api/access/grants", headers=self.headers,
                                json={"name":name,"role":role}).json()
        client = TestClient(self.app)
        login = client.post("/api/access/login", json={"role":role,"code":grant["code"]})
        self.assertEqual(login.status_code,200)
        headers = {"x-csrf-token":login.json()["csrf"]}
        self.users.append(client)
        return client, headers, grant

    def tearDown(self):
        for client in self.users:
            client.close()
        self.admin.close()
        self.app.state.workspaces.close()
        self.store.db.close()
        self.directory.cleanup()

    def test_personal_credentials_never_inherit_owner_and_survive_restart(self):
        user, headers, grant = self.user("Alice")
        state = user.get("/api/state").json()
        self.assertTrue(state["workspace"]["personal"])
        self.assertTrue(state["access"]["configure_connections"])
        self.assertFalse(state["access"]["configure"])
        self.assertNotIn("github",state["config"])
        config = fixture_config()
        config["allow_writes"] = False
        config["github"]["token"] = "alice-personal-token"
        self.assertEqual(user.put("/api/settings",headers=headers,json=config).status_code,200)
        personal = self.app.state.workspaces.select(grant["id"])[0]
        self.assertEqual(personal.config()["github"]["token"],"alice-personal-token")
        self.assertEqual(self.store.config()["github"]["token"],"github-private-token")
        self.assertNotIn("alice-personal-token",json.dumps(user.get("/api/state").json()))
        self.assertNotIn("alice-personal-token",(personal.directory/"app.sqlite3").read_bytes().decode(errors="ignore"))
        self.app.state.workspaces.close()
        restarted = create_app(self.store)
        client = TestClient(restarted)
        try:
            self.assertEqual(client.post("/api/access/login",json={"role":"viewer","code":grant["code"]}).status_code,200)
            self.assertTrue(client.get("/api/state").json()["config"]["github"]["token_configured"])
            self.assertEqual(restarted.state.workspaces.select(grant["id"])[0].config()["github"]["token"],"alice-personal-token")
        finally:
            client.close()
            restarted.state.workspaces.close()
            # Closed old stores must not be closed again in teardown.
            self.app.state.workspaces.entries = {"owner":self.app.state.workspaces.entries["owner"]}

    def test_chats_search_diary_tasks_groups_usage_and_actions_are_private(self):
        alice, ah, ag = self.user("Alice","developer")
        bob, bh, _ = self.user("Bob")
        owner_cid = self.store.new_conversation("Owner secret")
        cid = alice.post("/api/conversations",headers=ah).json()["id"]
        personal = self.app.state.workspaces.select(ag["id"])[0]
        personal.save_turn(cid,[{"role":"user","content":"unique project evidence"},
                                {"role":"assistant","content":"Alice confidential answer"}])
        task = alice.post("/api/todos",headers=ah,json={"title":"Alice task"}).json()["id"]
        group = alice.post("/api/groups",headers=ah,json={"name":"Alice group"}).json()["id"]
        personal.execute("INSERT INTO knowledge VALUES (?,?,?,?,?)",("alice-note","note","private value",None,1))
        personal.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?)",
                         ("alice-usage",__import__("time").time(),"test","test-model",'{"input_tokens":10}',"test"))
        for client in (bob,self.admin):
            state = client.get("/api/state").json()
            self.assertNotIn(cid,{c["id"] for c in state["conversations"]})
            self.assertNotIn(group,{g["id"] for g in state["groups"]})
            self.assertEqual(client.get("/api/conversations/"+cid).status_code,400)
            self.assertEqual(client.get("/api/history/search",params={"q":"confidential"}).json()["results"],[])
            self.assertEqual(client.get("/api/todos").json()["tasks"],[])
            self.assertEqual(client.get("/api/knowledge").json()["records"],[])
            self.assertEqual(client.get("/api/usage").json()["totals"]["requests"],0)
        self.assertEqual(alice.get("/api/conversations/"+owner_cid).status_code,400)
        self.assertEqual(bob.patch("/api/todos/"+task,headers=bh,json={"completed":True}).status_code,400)
        self.assertEqual(alice.get("/api/history/search",params={"q":"confidential"}).json()["results"][0]["id"],cid)
        self.admin.patch("/api/access/grants/"+ag["id"],headers=self.headers,json={"role":"viewer"})
        self.assertEqual(alice.get("/api/conversations/"+cid).status_code,200)
        self.admin.delete("/api/access/grants/"+ag["id"],headers=self.headers)
        self.assertEqual(alice.get("/api/state").status_code,401)

    def test_execution_switch_cannot_be_enabled_by_personal_config(self):
        user, headers, grant = self.user("Developer","developer")
        config = self.store.config()
        config["allow_writes"] = False
        self.store.save_config(config)
        personal = self.app.state.workspaces.select(grant["id"])[0]
        personal.save_config({**fixture_config(),"allow_writes":True})
        self.assertFalse(user.get("/api/state").json()["access"]["write"])
        self.assertEqual(user.put("/api/settings/changes",headers=headers,json={"allow_writes":True}).status_code,403)
        self.assertEqual(user.put("/api/settings",headers=headers,json=fixture_config()).status_code,403)
        version = personal.config()["_version"]
        self.store.save_config({**fixture_config(),"allow_writes":True})
        self.assertTrue(user.get("/api/state").json()["access"]["write"])
        self.assertNotEqual(personal.config()["_version"],version)

    def test_personal_bedrock_cannot_fall_back_to_server_aws_credentials(self):
        user, headers, _ = self.user("AWS user")
        response = user.put("/api/settings/ai",headers=headers,json={
            "provider":"bedrock","model":"test-model","region":"us-east-2",
            "bedrock_mode":"advanced","bedrock_auth":"iam"})
        self.assertEqual(response.status_code,400)
        self.assertIn("your own AWS",response.json()["detail"])

    def test_chatgpt_accounts_are_personal_too(self):
        user, _, grant = self.user("ChatGPT user")
        root = self.app.state.chatgpt
        root.save({"host_id":"owner-test","active":"owner","accounts":{
            "owner":{"email":"owner@example.test","access_token":"owner-fake-token","scopes":[]}}})
        self.assertFalse(user.get("/api/state").json()["chatgpt"]["connected"])
        personal = self.app.state.workspaces.select(grant["id"])[1]
        personal.save({"host_id":"personal-test","active":"personal","accounts":{
            "personal":{"email":"personal@example.test","access_token":"personal-fake-token","scopes":[]}}})
        state = user.get("/api/state").json()["chatgpt"]
        self.assertTrue(state["connected"])
        self.assertEqual(state["accounts"][0]["email"],"personal@example.test")
        self.assertEqual(self.admin.get("/api/state").json()["chatgpt"]["accounts"][0]["email"],"owner@example.test")

    def test_concurrent_streams_keep_their_own_storage(self):
        alice, ah, ag = self.user("Alice")
        bob, bh, bg = self.user("Bob")
        ac = alice.post("/api/conversations",headers=ah).json()["id"]
        bc = bob.post("/api/conversations",headers=bh).json()["id"]
        async def answer(store,cid,question,**kwargs):
            await asyncio.sleep(0.03)
            store.save_turn(cid,[{"role":"user","content":question},
                                 {"role":"assistant","content":"reply "+question}])
            yield {"event":"done"}
        def send(client,headers,cid,text):
            return client.post("/api/chat",headers=headers,json={"conversation":cid,"question":text})
        with patch("app.main.run_turn",answer), ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(send,alice,ah,ac,"alice-only")
            b = pool.submit(send,bob,bh,bc,"bob-only")
            self.assertNotIn('"event": "error"',a.result().text)
            self.assertNotIn('"event": "error"',b.result().text)
        for grant,cid,own,other in ((ag,ac,"alice-only","bob-only"),(bg,bc,"bob-only","alice-only")):
            history = json.dumps(self.app.state.workspaces.select(grant["id"])[0].history(cid))
            self.assertIn(own,history)
            self.assertNotIn(other,history)
