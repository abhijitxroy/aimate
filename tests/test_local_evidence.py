"""Desktop-local evidence stays scoped, read-only and available across provider loops."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.agent import run_turn, tools_for
from app.local_evidence import KEY, LocalEvidence, roots
from app.validation import validate_config
from test_app import Store, fixture_config, FakeAI, FakeBlock, FakeStream, create_app


class LocalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)/"repo";self.root.mkdir()
        self.cfg={**fixture_config(),KEY:[{"name":"project","path":str(self.root)}],
                  "_role":"admin","_local_access":True}
        self.reader=LocalEvidence(self.cfg)
        (self.root/"report.md").write_text("evidence\n"+"readable context\n"*900,encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def call(self, operation, **args):
        return self.reader.read_sync({"source":"project","operation":operation,**args})

    def git(self,*args):
        result=subprocess.run(["git","-C",str(self.root),*args],cwd=self.root,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              env={key:value for key,value in os.environ.items() if not key.startswith("GIT_")})
        self.assertEqual(result.returncode,0,"Fixture Git: "+result.stderr.decode(errors="replace"))
        return result.stdout.decode()

    def test_read_search_hash_paging_and_manifest_integrity(self):
        raw=(self.root/"report.md").read_bytes();digest=hashlib.sha256(raw).hexdigest()
        first=self.call("read",path="report.md")
        self.assertFalse(first["complete"]);self.assertEqual(first["sha256"],digest)
        text=first["text"];page=first
        while page["next_start"] is not None:
            page=self.call("read",path="report.md",start=page["next_start"]);text+=page["text"]
        self.assertEqual(text,raw.decode());self.assertTrue(page["complete"])
        self.assertTrue(self.call("search",path="report.md",query="EVIDENCE")["complete"] is False)
        self.assertFalse(self.call("search",path="report.md",query="not present")["found"])
        self.assertEqual(self.call("hash",path="report.md")["sha256"],digest)
        self.assertEqual(self.reader.read_sync({})["sources"],[{"name":"project"}])
        (self.root/"manifest.json").write_text(json.dumps({"files":[{"path":"report.md","sha256":digest}]}))
        self.assertTrue(self.call("verify_manifest",path="manifest.json")["all_matched"])
        (self.root/"report.md").write_text("changed",encoding="utf-8")
        self.assertFalse(self.call("verify_manifest",path="manifest.json")["all_matched"])

    def test_traversal_credentials_role_disable_and_revocation(self):
        for path in ("../secret","/absolute","C:/other","src/.env","src/credentials.json",
                     ".git/config",".data/app.sqlite3","a\\b","secrets/token"):
            with self.subTest(path=path),self.assertRaises(ValueError):
                self.call("read",path=path)
        for role in ("developer","viewer","reviewer"):
            self.assertNotIn("inspect_local_source",{t["name"] for t in tools_for({**self.cfg,"_role":role})})
        with patch.dict(os.environ,{"AIMATE_LOCAL_EVIDENCE_ENABLED":"0"}):
            self.assertNotIn("inspect_local_source",{t["name"] for t in tools_for(self.cfg)})
            with self.assertRaises(ValueError):self.call("list")
        reader=LocalEvidence(self.cfg,current_roots=lambda:[])
        with self.assertRaisesRegex(ValueError,"changed"):reader.read_sync({})
        self.assertNotIn("inspect_local_source",{t["name"] for t in tools_for({**self.cfg,"_local_access":False})})
        (self.root/".env").write_text("synthetic excluded")
        self.assertNotIn(".env",self.call("list")["entries"])

    def test_inventory_counts_full_snapshot_without_claiming_unique_builds(self):
        records=[{"job":"a","number":1,"result":"FAILURE"},{"job":"a","number":1,"result":"FAILURE"},
                 {"job":"b","number":1,"result":"SUCCESS"},{"job":"b","number":2}]
        (self.root/"inventory.json").write_text(json.dumps({"builds":records}),encoding="utf-8")
        result=self.call("inventory_summary",path="inventory.json")
        self.assertEqual(result["rows"],4)
        self.assertEqual(result["unique_exact_records"],3)
        self.assertEqual(result["duplicate_exact_records"],1)
        self.assertEqual(next(row["count"] for row in result["groups"] if row["value"]=="FAILURE"),2)
        self.assertEqual(result["missing_group_field"],1)
        self.assertTrue(result["complete_row_scan"])
        self.assertIn("not necessarily unique builds",result["notice"])
        (self.root/"bad.json").write_text(json.dumps({"unrelated":records}))
        with self.assertRaises(ValueError):self.call("inventory_summary",path="bad.json")

    def test_symlink_and_binary_restrictions(self):
        target=Path(self.directory.name)/"outside";target.write_text("outside")
        try:(self.root/"linked").symlink_to(target)
        except OSError:pass
        else:
            with self.assertRaisesRegex(ValueError,"Linked"):self.call("read",path="linked")
            self.assertNotIn("linked",self.call("list")["entries"])
        (self.root/"binary.bin").write_bytes(b"\0binary")
        with self.assertRaisesRegex(ValueError,"Binary"):self.call("read",path="binary.bin")
        self.assertEqual(self.call("hash",path="binary.bin")["bytes"],7)
        with self.assertRaises(ValueError):roots([{"name":"escape","path":str(Path(self.root.anchor))}])

    def test_git_diff_is_read_only_pages_cached_and_never_executes_filters(self):
        self.git("init","-q");self.git("config","user.name","Fixture");self.git("config","user.email","fixture@example.test")
        self.git("add","report.md");self.git("commit","-qm","fixture")
        old=self.git("rev-parse","HEAD").strip()
        self.git("config","core.fsmonitor","does-not-exist")
        self.git("config","diff.external","does-not-exist")
        (self.root/"report.md").write_text("new evidence\n")
        (self.root/".env").write_text("NEVER INCLUDED")
        status=self.call("git_status")
        self.assertIn("report.md",status["text"]);self.assertNotIn(".env",status["text"])
        diff=self.call("git_diff",ref=old)
        text=diff["text"];page=diff
        while page["next_start"] is not None:
            page=self.call("git_diff",ref=old,start=page["next_start"]);text+=page["text"]
        self.assertTrue("+new evidence" in text);self.assertNotIn("NEVER INCLUDED",diff["text"])
        before=(self.root/"report.md").read_bytes()
        snapshot=self.call("git_diff",ref=old)["text"]
        self.assertEqual(snapshot,diff["text"]);self.assertEqual(before,(self.root/"report.md").read_bytes())
        self.assertIn("evidence",self.call("git_show",ref=old,path="report.md")["text"])
        sub=self.root/"nested";sub.mkdir()
        reader=LocalEvidence({**self.cfg,KEY:[{"name":"nested","path":str(sub)}]})
        with self.assertRaisesRegex(ValueError,"repository root"):
            reader.read_sync({"source":"nested","operation":"git_status"})
        with self.assertRaises(ValueError):self.call("git_show",ref="HEAD; echo bad",path="report.md")

    def test_owner_routes_hide_paths_and_preserve_roots_across_settings(self):
        with tempfile.TemporaryDirectory() as data:
            store=Store(data);store.save_config(self.cfg)
            self.assertNotIn(KEY,store.public_config())
            validated=validate_config(fixture_config(),store.config())
            self.assertEqual(validated[KEY],self.cfg[KEY])
            with patch.dict(os.environ,{"AIMATE_DEV_LOGIN":"1"}):
                app=create_app(store=store,demo=False)
                route=next(route for route in app.routes if getattr(route,"path","")=="/api/local-evidence" and "GET" in route.methods)
                for role in ("developer","viewer","reviewer"):
                    with self.assertRaises(HTTPException) as denied:
                        route.endpoint(request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
                                       session={"role":role,"grant":"personal"})
                    self.assertEqual(denied.exception.status_code,403)
                with TestClient(app,base_url="http://127.0.0.1",client=("127.0.0.1",50000)) as client:
                    csrf=client.post("/api/dev/login").json()["csrf"]
                    headers={"x-csrf-token":csrf,"origin":"http://127.0.0.1"}
                    response=client.put("/api/local-evidence",json={"sources":self.cfg[KEY]},headers=headers)
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertEqual(client.get("/api/local-evidence").json()["sources"],self.cfg[KEY])
                    self.assertNotIn(KEY,client.get("/api/state").json()["config"])
                with patch.dict(os.environ,{"AIMATE_LOCAL_EVIDENCE_ENABLED":"0"}),TestClient(app,base_url="http://127.0.0.1",client=("127.0.0.1",50000)) as client:
                    client.post("/api/dev/login")
                    self.assertEqual(client.get("/api/local-evidence").status_code,403)
            store.db.close()

    def test_native_and_responses_read_local_sources_without_network(self):
        with tempfile.TemporaryDirectory() as data:
            store=Store(data);store.save_config(self.cfg);cid=store.new_conversation()
            class Stream(FakeStream):
                async def get_final_message(self):
                    blocks=([FakeBlock(type="tool_use",id="local",name="inspect_local_source",
                        input={"source":"project","operation":"hash","path":"report.md"})] if self.stage==0
                        else [FakeBlock(type="text",text="Hash verified from local bytes.")])
                    return SimpleNamespace(content=blocks,usage=SimpleNamespace(input_tokens=10,output_tokens=5))
            class AI(FakeAI):
                def stream(self,**kwargs):
                    result=Stream(self.stage);self.stage+=1;return result
            async def native():
                return [e async for e in run_turn(store,cid,"Hash local project/report.md",
                    client_factory=AI,model_mode="standard",local_access=True)]
            events=asyncio.run(native())
            self.assertTrue(any(e["event"]=="tool_done" and e["ok"] for e in events))
            from app.bedrock_gpt import Connection,PROVIDER,DEFAULT_MODEL
            cfg=store.config();cfg["ai"]={"provider":PROVIDER,"model":DEFAULT_MODEL,"region":"us-east-2",
                "api_key":"synthetic-bedrock","bedrock_mode":"advanced"};store.save_config(cfg)
            payloads=[]
            def remote(request):
                payloads.append(json.loads(request.content))
                output=([{"type":"function_call","call_id":"local","name":"inspect_local_source",
                    "arguments":json.dumps({"source":"project","operation":"hash","path":"report.md"})}]
                    if len(payloads)==1 else [{"type":"message","role":"assistant",
                    "content":[{"type":"output_text","text":"Local hash checked."}]}])
                return httpx.Response(200,text="data: "+json.dumps({"type":"response.completed",
                    "response":{"model":DEFAULT_MODEL,"output":output,"usage":{"input_tokens":10,"output_tokens":5}}})+"\n\n",
                    headers={"content-type":"text/event-stream"})
            transport=httpx.MockTransport(remote)
            async def responses():
                return [e async for e in run_turn(store,cid,"Hash local project/report.md",
                    model_mode="standard",local_access=True)]
            with patch("app.bedrock_gpt.Connection",side_effect=lambda cfg,store=None:Connection(cfg,store,transport)):
                events=asyncio.run(responses())
            self.assertTrue(any(e["event"]=="tool_done" and e["ok"] for e in events))
            result=next(item for item in payloads[1]["input"] if item.get("type")=="function_call_output")
            self.assertIn("sha256",result["output"]);store.db.close()
