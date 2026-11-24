import base64
import io
import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from test_app import create_app, fixture_config, Store
from app.agent import tools_for
from app.attachments import image, pdf


class AccessAttachmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.app = create_app(self.store)
        self.admin = TestClient(self.app)
        self.headers = {"x-csrf-token": self.admin.post("/api/login", json={"password": self.store.password}).json()["csrf"]}

    def tearDown(self):
        self.admin.close()
        self.app.state.workspaces.close()
        self.store.db.close()
        self.directory.cleanup()

    def delegated(self, role):
        grant = self.admin.post("/api/access/grants", headers=self.headers, json={"role": role, "name": "Test account"}).json()
        client = TestClient(self.app)
        response = client.post("/api/access/login", json={"role": role, "code": grant["code"]})
        self.assertEqual(response.status_code, 200)
        return client, {"x-csrf-token": response.json()["csrf"]}, grant

    def test_viewer_cannot_escalate_but_can_manage_personal_records(self):
        client, headers, grant = self.delegated("viewer")
        try:
            state = client.get("/api/state").json()
            self.assertFalse(state["access"]["write"])
            self.assertFalse(state["config"]["allow_writes"])
            self.assertEqual(client.put("/api/settings", headers=headers, json=fixture_config()).status_code, 403)
            self.assertEqual(client.post("/api/access/grants", headers=headers, json={"role":"developer","name":"Upgrade"}).status_code, 403)
            self.assertEqual(client.get("/api/audit").status_code, 403)
            self.assertEqual(client.post("/api/actions/fake/confirm", headers=headers).status_code, 403)
            self.assertEqual(client.post("/api/todos", headers=headers, json={"title":"test"}).status_code, 200)
            self.assertEqual(client.post("/api/conversations", headers=headers).status_code, 200)
            self.assertEqual(client.post("/api/access/login", json={"role":"developer","code":grant["code"]}).status_code, 401)
            self.assertEqual(client.post("/api/access/login", json={"role":"admin","code":grant["code"]}).status_code, 401)
            self.admin.delete("/api/access/grants/"+grant["id"], headers=self.headers)
            self.assertEqual(client.get("/api/state").status_code, 401)
        finally:
            client.close()

    def test_developer_can_manage_personal_records_and_connections_but_not_owner_security(self):
        client, headers, _ = self.delegated("developer")
        try:
            self.assertTrue(client.get("/api/state").json()["access"]["write"])
            self.assertEqual(client.get("/api/audit").status_code, 200)
            self.assertEqual(client.put("/api/settings/github", headers=headers, json={}).status_code, 200)
            self.assertEqual(client.put("/api/settings/changes", headers=headers, json={"allow_writes":True}).status_code, 403)
            self.assertEqual(client.post("/api/auth/otp/setup", headers=headers, json={}).status_code, 403)
            self.assertEqual(client.post("/api/todos", headers=headers, json={"title":"task"}).status_code, 200)
            cfg = {**fixture_config(), "_role":"developer"}
            self.assertNotIn("configure_repository", {t["name"] for t in tools_for(cfg)})
            cfg.update(_role="viewer", allow_writes=False)
            self.assertNotIn("propose_action", {t["name"] for t in tools_for(cfg)})
        finally:
            client.close()

    def test_admin_changes_role_immediately_and_audits_it(self):
        client, headers, grant=self.delegated("developer")
        try:
            response=self.admin.patch("/api/access/grants/"+grant["id"],headers=self.headers,json={"role":"viewer"})
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.get("/api/state").json()["access"]["role"],"viewer")
            self.assertEqual(client.post("/api/todos",headers=headers,json={"title":"personal"}).status_code,200)
            self.assertEqual(client.patch("/api/access/grants/"+grant["id"],headers=headers,json={"role":"developer"}).status_code,403)
            self.assertEqual(self.admin.patch("/api/access/grants/"+grant["id"],headers=self.headers,json={"role":"admin"}).status_code,400)
            events=self.admin.get("/api/access/grants").json()["audit"]
            self.assertIn("role_changed",{entry["operation"] for entry in events})
            self.assertNotIn(grant["authenticator_secret"],json.dumps(events))
        finally:
            client.close()

    def test_developer_cannot_propose_or_confirm_admin_operations(self):
        from app.agent import propose
        from app.access import permits_operation
        import asyncio
        for operation in ("delete_issue","delete_file","merge_pull_request","abort_build","unknown"):
            self.assertFalse(permits_operation("developer",operation))
            self.assertTrue(permits_operation("admin",operation))
        config={**fixture_config(),"_role":"developer"}
        with self.assertRaisesRegex(ValueError,"Administrator"):
            asyncio.run(propose(self.store,config,None,"chat",{"service":"jira","operation":"delete_issue","payload":{"issue":"DEMO-1"}}))
        cid=self.store.new_conversation("Admin action")
        self.store.execute("INSERT INTO actions (id,conversation,service,operation,payload,preview,config_version,status,created) VALUES (?,?,?,?,?,?,?,?,?)",
                           ("admin-action",cid,"jira","delete_issue","{}","{}",self.store.config()["_version"],"pending",__import__("time").time()))
        client,headers,grant=self.delegated("developer")
        try:
            # A foreign action cannot even be retrieved; a personal destructive
            # action still requires Admin regardless of credentials.
            self.assertEqual(client.post("/api/actions/admin-action/confirm",headers=headers).status_code,400)
            personal=self.app.state.workspaces.select(grant["id"])[0]
            cid=personal.new_conversation("Personal action")
            personal.execute("INSERT INTO actions (id,conversation,service,operation,payload,preview,config_version,status,created) VALUES (?,?,?,?,?,?,?,?,?)",
                           ("admin-action",cid,"jira","delete_issue","{}","{}",personal.config()["_version"],"pending",__import__("time").time()))
            self.assertEqual(client.post("/api/actions/admin-action/confirm",headers=headers).status_code,403)
        finally:
            client.close()

    def test_image_validation_provider_blocks_and_encrypted_saved_previews(self):
        raw = io.BytesIO()
        Image.new("RGB", (60,40), "navy").save(raw, "PNG")
        item = {"name":"Screenshot.png", "data":base64.b64encode(raw.getvalue()).decode()}
        block, card = image(item)
        self.assertEqual(block["type"], "image")
        self.assertTrue(card["preview"].startswith("data:image/jpeg;base64,"))
        received = []
        async def answer(store, cid, question, **kwargs):
            received.extend(kwargs["images"])
            store.save_turn(cid, [{"role":"user","content":question},
                {"role":"assistant","content":[{"type":"text","text":"A navy screenshot."}]}])
            yield {"event":"done"}
        cid = self.admin.post("/api/conversations", headers=self.headers).json()["id"]
        with patch("app.main.run_turn", answer):
            response = self.admin.post("/api/chat", headers=self.headers,
                json={"conversation":cid,"question":"What is shown?","images":[item]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(received, [block])
        result = self.admin.get("/api/conversations/"+cid).json()["turns"][-1]
        self.assertEqual(result["attachment_previews"][0]["name"], "Screenshot.png")
        encrypted = self.store.rows("SELECT encrypted FROM attachment_previews")[0]["encrypted"]
        self.assertNotIn(card["preview"], encrypted)
        self.assertNotIn(item["data"], json.dumps(self.store.history(cid)))
        bad = {**item, "data":base64.b64encode(b"not an image").decode()}
        self.assertEqual(self.admin.post("/api/chat", headers=self.headers,
            json={"conversation":cid,"question":"read","images":[bad]}).status_code, 400)
        self.admin.delete("/api/conversations/"+cid, headers=self.headers)
        self.assertEqual(self.store.rows("SELECT * FROM attachment_previews"), [])

    def test_pdf_refuses_invalid_and_scanned_empty_documents(self):
        with self.assertRaises(ValueError):
            pdf({"name":"bad.pdf","data":base64.b64encode(b"bad").decode()})
        writer = PdfWriter()
        writer.add_blank_page(width=300,height=300)
        output = io.BytesIO()
        writer.write(output)
        with self.assertRaisesRegex(ValueError, "no readable text"):
            pdf({"name":"empty.pdf","data":base64.b64encode(output.getvalue()).decode()})
