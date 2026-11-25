import json
import asyncio
import tempfile
import unittest
from fastapi.testclient import TestClient
from test_app import Store, create_app, fixture_config, FakeAI
from app.investigation_workspace import context, evidence, save, source_scope


class InvestigationWorkspaceTests(unittest.TestCase):
    def test_actual_model_receives_bounded_checkpoint(self):
        from app.agent import run_turn
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.save_config(fixture_config());cid=store.new_conversation()
            save(store,cid,{"preset":"debug","target":"build-11","notes":"Need remaining pages","checked":[0]})
            seen=[]
            class Answer(FakeAI):
                def __init__(self,cfg):
                    super().__init__(cfg);self.stage=2
                def stream(self,**kwargs):
                    seen.append(kwargs["system"]);return super().stream(**kwargs)
            async def run():
                return [e async for e in run_turn(store,cid,"Continue",client_factory=Answer,
                    services_factory=lambda cfg:None,model_mode="standard")]
            asyncio.run(run())
            self.assertIn("Need remaining pages",seen[0])
            self.assertIn("not verified findings",seen[0])
            store.db.close()

    def test_restart_evidence_scope_coverage_redaction_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory); config = fixture_config(); store.save_config(config)
            cid = store.new_conversation()
            body = {"preset":"debug", "target":"Build #11", "notes":"Next page\n" + config["github"]["token"], "checked":[0]}
            save(store,cid,body)
            source=config["github"]["url"]+"/repos/"+config["github"]["repos"][0]+"/pulls/1"
            store.save_turn(cid, [
                {"role":"assistant","content":[{"type":"text","text":"Claimed https://example.com/fake"}]},
                {"role":"user","content":[
                    {"type":"tool_result","content":json.dumps({"source":source,"data":{"next_line":201}})},
                    {"type":"tool_result","is_error":True,"content":json.dumps({"source":source+"/failed","data":{}})},
                    {"type":"tool_result","content":"truncated JSON"}]}])
            store.db.close(); store = Store(directory)
            reference = context(store,cid,"Continue the investigation")
            self.assertIn("Next page",reference); self.assertIn("[redacted]",reference)
            self.assertNotIn(config["github"]["token"],reference)
            self.assertEqual(context(store,cid,"What is your name?"),"")
            sources=evidence(store,cid)
            self.assertEqual(len(sources),1); self.assertEqual(sources[0]["url"],source)
            self.assertEqual(sources[0]["coverage"],"More pages/ranges remain")
            cfg=store.config();cfg["github"]["repos"]=[];store.save_config(cfg)
            self.assertEqual(evidence(store,cid),[])
            for bad in ("https://[bad", "javascript:alert(1)", source+"?token=secret",source+"#fragment"):
                self.assertIsNone(source_scope(bad,config))
            with self.assertRaises(ValueError): save(store,cid,{**body,"checked":[True]})
            with self.assertRaises(ValueError): save(store,cid,{**body,"preset":"other"})
            with self.assertRaises(ValueError): save(store,cid,{**body,"notes":"x"*6001})
            store.db.close()

    def test_account_isolation_csrf_viewer_notes_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            body={"preset":"review","target":"owner-only","notes":"keep","checked":[0,1]}
            with TestClient(create_app(store)) as client:
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"]
                headers={"X-CSRF-Token":csrf}
                cid=client.post("/api/conversations",headers=headers,json={}).json()["id"]
                path=f"/api/conversations/{cid}/investigation"
                self.assertEqual(client.put(path,json=body).status_code,403)
                self.assertEqual(client.put(path,headers=headers,json=body).status_code,200)
                self.assertEqual(client.get(path).json()["record"]["target"],"owner-only")
                grant=client.post("/api/access/grants",headers=headers,json={"name":"Viewer","role":"viewer"}).json()
                csrf=client.post("/api/access/login",json={"role":"viewer","code":grant["code"]}).json()["csrf"]
                headers={"X-CSRF-Token":csrf}
                self.assertEqual(client.get(path).status_code,400)
                own=client.post("/api/conversations",headers=headers,json={}).json()["id"]
                self.assertEqual(client.put(f"/api/conversations/{own}/investigation",headers=headers,json=body).status_code,200)
                self.assertEqual(client.delete(f"/api/conversations/{own}",headers=headers).status_code,200)
                viewer=client.app.state.workspaces.select(grant["id"])[0]
                self.assertEqual(viewer.rows("SELECT * FROM investigation_records"),[])
                self.assertEqual(len(store.rows("SELECT * FROM investigation_records")),1)
            store.db.close()
