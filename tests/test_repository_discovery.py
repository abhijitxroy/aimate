"""Explicit new-repo reads cannot turn source links into authority or saved scope."""
import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from app.connectors import Services
from app.repository_discovery import Discovery, requested
from test_app import Store, fixture_config
from test_app import FakeAI, FakeStream, FakeBlock
from app.agent import run_turn, tools_for


class RepositoryDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(self.directory.name);self.store.save_config(fixture_config())
        self.config=self.store.config();self.requests=[];self.denied=False;self.revoked=False
        def remote(request):
            self.requests.append(request)
            if self.denied:return httpx.Response(404,json={"secret":"NEVER RETURN"})
            if request.url.path.endswith("/user"):return httpx.Response(200,json={"login":"synthetic-operator"})
            if request.url.path.endswith("/pulls/7"):return httpx.Response(200,json={"title":"Verified PR","body":"PR text"})
            return httpx.Response(200,json={"full_name":"team/new","default_branch":"main"})
        self.factory=lambda cfg:Services(cfg,httpx.MockTransport(remote))

    def tearDown(self):
        self.store.db.close();self.directory.cleanup()

    def reader(self,question="Read team/new PR 7"):
        def check():
            if self.revoked:raise ValueError("Access revoked")
        return Discovery(self.config,question,self.factory,check)

    def test_validated_temporary_reads_preserve_config_and_proposals(self):
        reader=self.reader()
        result=asyncio.run(reader.read({"repo":"team/new","path":"/repos/team/new/pulls/7"}))
        self.assertEqual(result["data"]["title"],"Verified PR")
        self.assertFalse(result["repository_access"]["saved"])
        self.assertEqual(self.store.config()["github"]["repos"],["team/repo"])
        self.assertEqual(self.store.rows("SELECT id FROM actions"),[])
        asyncio.run(reader.read({"repo":"team/new","path":"/repos/team/new/pulls/7"}))
        self.assertEqual(sum(r.url.path.endswith("/repos/team/new") for r in self.requests),1)
        self.assertTrue(all(r.method=="GET" for r in self.requests))
        self.assertNotIn("github-private-token",json.dumps(result))

    def test_repo_from_previous_evidence_or_foreign_host_is_not_authorized(self):
        for question in ("Inspect the issue","Read https://evil.example/team/new/pulls/7",
                         "Inspect this log\n\nUntrusted attachment manifest.\nhttps://github.example/team/new"):
            with self.assertRaisesRegex(ValueError,"current question"):
                asyncio.run(self.reader(question).read({"repo":"team/new"}))
        self.assertEqual(self.requests,[])
        self.assertEqual(requested("Read https://github.example/team/new/pull/7",self.config),{"team/new":"team/new"})
        self.assertEqual(requested("Read `team/new`",self.config),{"team/new":"team/new"})

    def test_cross_repo_url_traversal_and_unknown_arguments_are_rejected(self):
        for body in ({"repo":"team/new","path":"/repos/team/other/pulls/7"},
                     {"repo":"team/new","path":"https://evil.example/"},
                     {"repo":"team/new","path":"/repos/team/new/../other"},
                     {"repo":"team/new","token":"not allowed"},
                     {"repo":"team/repo"}):
            with self.assertRaises(ValueError):asyncio.run(self.reader().read(body))
        self.assertEqual(self.requests,[])

    def test_access_failures_disabled_module_and_revocation_do_not_broaden_scope(self):
        self.denied=True
        with self.assertRaises(ValueError):asyncio.run(self.reader().read({"repo":"team/new"}))
        self.assertEqual(self.store.config()["github"]["repos"],["team/repo"])
        self.requests=[]
        with patch.dict(os.environ,{"AIMATE_REPOSITORY_DISCOVERY_ENABLED":"0"}):
            with self.assertRaisesRegex(ValueError,"disabled"):asyncio.run(self.reader().read({"repo":"team/new"}))
        self.revoked=True
        with self.assertRaisesRegex(ValueError,"revoked"):asyncio.run(self.reader().read({"repo":"team/new"}))
        self.assertEqual(self.requests,[])

    def test_parser_bounds_new_repositories_and_does_not_accept_credentials(self):
        with self.assertRaisesRegex(ValueError,"five"):
            requested("Read "+" ".join("team/repo"+str(i) for i in range(6)),self.config)
        self.assertEqual(requested("Read https://operator:password@github.example/team/new",self.config),{})

    def test_anthropic_loop_records_verified_evidence_and_offers_review_without_saving_scope(self):
        class Stream(FakeStream):
            async def get_final_message(self):
                block=(FakeBlock(type="tool_use",id="newrepo",name="read_requested_repository",
                    input={"repo":"team/new","path":"/repos/team/new/pulls/7"}) if self.stage==0 else
                    FakeBlock(type="text",text="PR read. Adding it later needs confirmation."))
                return SimpleNamespace(content=[block],usage=SimpleNamespace(input_tokens=20,output_tokens=5))
        class AI(FakeAI):
            def stream(self,**kwargs):
                self.last=kwargs
                stream=Stream(self.stage);self.stage+=1;return stream
        cid=self.store.new_conversation()
        async def turn():
            return [event async for event in run_turn(self.store,cid,"Read team/new PR 7",
                client_factory=AI,services_factory=self.factory,model_mode="standard")]
        events=asyncio.run(turn())
        self.assertEqual(next(e["guidance"]["action"] for e in events if e["event"]=="repository_access"),"validate_repository")
        self.assertEqual(events[-1]["event"],"done")
        self.assertEqual(self.store.config()["github"]["repos"],["team/repo"])
        self.assertIn("Verified PR",json.dumps(self.store.history(cid)))
        with patch.dict(os.environ,{"AIMATE_REPOSITORY_DISCOVERY_ENABLED":"0"}):
            self.assertNotIn("read_requested_repository",{t["name"] for t in tools_for(self.config)})

    def test_responses_loop_uses_the_same_verified_scoped_read(self):
        from app.bedrock_gpt import Connection,PROVIDER,DEFAULT_MODEL
        cfg=self.store.config();cfg["ai"]={"provider":PROVIDER,"model":DEFAULT_MODEL,"region":"us-east-2",
            "api_key":"synthetic-bedrock-token","bedrock_mode":"advanced"};self.store.save_config(cfg)
        payloads=[]
        def remote(request):
            body=json.loads(request.content);payloads.append(body)
            output=([{"type":"function_call","call_id":"newrepo","name":"read_requested_repository",
                "arguments":json.dumps({"repo":"team/new","path":"/repos/team/new/pulls/7"})}] if len(payloads)==1 else
                [{"type":"function_call","call_id":"addrepo","name":"configure_repository",
                  "arguments":json.dumps({"repo":"team/new"})}] if len(payloads)==2 else
                [{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Verified PR read."}]}])
            events=[]
            if len(payloads)>2:events.append({"type":"response.output_text.delta","delta":"Verified PR read."})
            events.append({"type":"response.completed","response":{"model":body["model"],"output":output,
                "usage":{"input_tokens":10,"output_tokens":3}}})
            return httpx.Response(200,text="".join("data: "+json.dumps(e)+"\n\n" for e in events),
                headers={"content-type":"text/event-stream"})
        transport=httpx.MockTransport(remote)
        cid=self.store.new_conversation()
        async def turn():
            return [event async for event in run_turn(self.store,cid,"Read team/new PR 7",
                services_factory=self.factory,model_mode="standard")]
        with patch("app.bedrock_gpt.Connection",side_effect=lambda config,store=None:Connection(config,store,transport)):
            events=asyncio.run(turn())
        self.assertEqual(events[-1]["event"],"done")
        self.assertTrue(any(e["event"]=="repository_access" for e in events),repr(events))
        evidence=next(item for item in payloads[1]["input"] if item.get("type")=="function_call_output")
        self.assertIn("Verified PR",evidence["output"])
        self.assertEqual(self.store.config()["github"]["repos"],["team/repo"])
        actions=[e["action"] for e in events if e["event"]=="action"]
        self.assertTrue(actions,repr(events))
        self.assertEqual(actions[0]["status"],"pending")
