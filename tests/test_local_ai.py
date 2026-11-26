"""Loopback-only inference, opt-in fallback, credential isolation and saved context."""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
import httpx
from fastapi.testclient import TestClient
from app.ollama_local import Client,DEFAULT_MODEL,payload,result
from app.local_ai import LocalStore
from test_app import Store,create_app,fixture_config,FakeAI


class LocalAITests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.store=Store(self.directory.name)
        self.store.save_config(fixture_config());self.requests=[];self.mode="answer";self.native_calls=0
        def remote(request):
            self.requests.append(request)
            self.assertEqual(request.url.host,"127.0.0.1")
            self.assertEqual(request.url.port,11434)
            self.assertNotIn("authorization",request.headers)
            if request.url.path=="/api/tags":
                return httpx.Response(200,json={"models":[{"name":DEFAULT_MODEL}]})
            if request.url.path=="/api/show":
                return httpx.Response(200,json={"template":"<think>\n{{ end }}\n{{- end }}" if self.mode=="legacy" else "",
                    "model_info":{"general.architecture":"qwen3"},"details":{"format":"gguf"},
                    "remote_host":"https://remote.example" if self.mode=="remote" else ""})
            body=json.loads(request.content);self.native_calls+=1
            self.assertNotIn("private-token",json.dumps(body))
            message={"role":"assistant","content":"Local answer."}
            if self.mode=="tool" and self.native_calls==1:
                message={"role":"assistant","content":"","tool_calls":[{"function":{"name":"api_read",
                    "arguments":{"service":"github","path":"/repos/team/repo/pulls/7"}}}]}
            final={"model":DEFAULT_MODEL,"message":message,"done":True,"done_reason":"stop",
                "prompt_eval_count":20,"eval_count":4}
            if self.mode=="length":final["done_reason"]="length"
            if not body["stream"]:return httpx.Response(200,json=final)
            values=[{"message":message,"done":False}]
            if self.mode=="legacy":
                final["message"]["content"]="<think>Unshown reasoning</think>\nLocal answer."
                if not body["stream"]:return httpx.Response(200,json=final)
                values=[{"message":{"content":"<thi"},"done":False},
                        {"message":{"content":"nk>Unshown reasoning</thi"},"done":False},
                        {"message":{"content":"nk>\nLocal answer."},"done":False}]
            if self.mode!="interrupted":values.append({**final,"message":{"content":""}})
            return httpx.Response(200,text="".join(json.dumps(v)+"\n" for v in values),
                headers={"content-type":"application/x-ndjson"})
        self.transport=httpx.MockTransport(remote)

    def tearDown(self):
        self.store.db.close();self.directory.cleanup()

    def args(self):
        return {"model":DEFAULT_MODEL,"max_tokens":80,"system":"Brief answer.",
            "messages":[{"role":"user","content":"Hello"}],"tools":[]}

    def test_native_create_stream_metering_and_unique_tool_ids(self):
        async def run():
            client=Client({"ai":{"model":DEFAULT_MODEL,"api_key":"ai-private-token"}},self.transport)
            try:
                value=await client.create(**self.args())
                self.assertEqual(value.content[0].text,"Local answer.")
                async with client.stream(**self.args()) as stream:
                    self.assertEqual("".join([part async for part in stream.text_stream]),"Local answer.")
                    self.assertEqual((await stream.get_final_message()).usage.input_tokens,20)
            finally:await client.close()
        asyncio.run(run())
        call={"function":{"name":"api_read","arguments":{"service":"github","path":"/repos/team/repo"}}}
        one=result(DEFAULT_MODEL,"",[call],{"done":True})
        two=result(DEFAULT_MODEL,"",[call],{"done":True})
        self.assertNotEqual(one.content[0].id,two.content[0].id)

    def test_prompt_limit_images_and_foreign_signature_state_are_not_silently_replayed(self):
        args=self.args();args["messages"]=[{"role":"user","content":"x"*24000}]
        self.assertEqual(payload(args,True)["messages"][-1]["content"],"x"*24000)
        args["messages"]=[{"role":"user","content":"x"*66000}]
        with self.assertRaisesRegex(ValueError,"after automatic context compaction"):payload(args,True)
        args["messages"]=[{"role":"user","content":[{"type":"image","source":{"data":"synthetic"}}]}]
        with self.assertRaisesRegex(ValueError,"text-only"):payload(args,True)
        args["messages"]=[{"role":"assistant","content":[{"type":"text","text":"Readable answer","vertex_signature":"SECRET FOREIGN STATE"}]}]
        self.assertNotIn("SECRET FOREIGN STATE",json.dumps(payload(args,True)))

    def test_incomplete_and_length_limited_local_replies_are_not_success(self):
        async def run():
            client=Client({"ai":{"model":DEFAULT_MODEL}},self.transport)
            try:
                for mode in ("interrupted","length"):
                    self.mode=mode
                    async with client.stream(**self.args()) as stream:
                        async for _ in stream.text_stream:pass
                        with self.assertRaises(ValueError):await stream.get_final_message()
            finally:await client.close()
        asyncio.run(run())

    def test_legacy_qwen_thought_filter_handles_fragmented_markers_and_keeps_total_usage(self):
        self.mode="legacy"
        async def run():
            client=Client({"ai":{"model":DEFAULT_MODEL}},self.transport)
            try:
                async with client.stream(**self.args()) as stream:
                    text="".join([part async for part in stream.text_stream])
                self.assertEqual(text.strip(),"Local answer.")
                body=json.loads(next(r.content for r in self.requests if r.url.path=="/api/chat"))
                self.assertEqual(body["messages"][-1],{"role":"user","content":"Hello"})
                self.assertEqual(body["options"]["num_thread"],4)
                self.assertEqual((await stream.get_final_message()).usage.output_tokens,4)
            finally:await client.close()
        asyncio.run(run())

    def test_local_store_uses_bounded_readable_history_without_changing_saved_data(self):
        cid=self.store.new_conversation()
        self.store.save_turn(cid,[{"role":"user","content":"Important PR 7"},
            {"role":"assistant","content":[{"type":"text","text":"Saved readable context "+("x"*6000)},
                {"type":"tool_use","id":"tool","name":"api_read","input":{"never":"REPLAY TOOL STATE"}}]}])
        before=self.store.config()
        local=LocalStore(self.store,DEFAULT_MODEL)
        self.assertEqual(local.config()["ai"]["provider"],"ollama")
        self.assertEqual(local.source_config(),before)
        self.assertNotIn("REPLAY TOOL STATE",json.dumps(local.history(cid)))
        self.assertLessEqual(len(local.history(cid)[0]["content"].encode()),3200)
        self.assertEqual(self.store.config(),before)
        self.assertIn("REPLAY TOOL STATE",json.dumps(self.store.history(cid)))

    def client(self,**kwargs):
        app=create_app(self.store,**kwargs)
        client=TestClient(app,base_url="http://127.0.0.1",client=("127.0.0.1",50000))
        csrf=client.post("/api/login",json={"password":self.store.password}).json()["csrf"]
        return client,{"x-csrf-token":csrf}

    def test_real_http_local_tool_loop_preserves_cloud_checks_and_records_zero_api_rates(self):
        from app.connectors import Services
        connector_requests=[]
        def connector(request):
            connector_requests.append(request)
            return httpx.Response(200,json={"title":"Scoped PR"})
        factory=lambda cfg:Services(cfg,httpx.MockTransport(connector))
        self.mode="tool";cid=self.store.new_conversation()
        before=self.store.config()
        self.store.save_connection_check("ai",before,{"status":"passed","checked_at":1,"model":"test-model"})
        native=Client
        with patch("app.ollama_local.Client",side_effect=lambda cfg: native(cfg,self.transport)),patch(
                "app.usage_meter.enforce_budget",side_effect=ValueError("Cloud budget")) as budget:
            client,headers=self.client(services_factory=factory)
            try:
                response=client.post("/api/chat",headers=headers,json={"conversation":cid,"question":"Read my PR",
                    "local_ai":True,"local_model":DEFAULT_MODEL})
                self.assertIn('"event": "done"',response.text)
                self.assertIn('"event": "local_status"',response.text)
                self.assertIn("Local answer",response.text)
                budget.assert_not_called()
                self.assertEqual(self.store.config(),before)
                self.assertEqual(self.store.connection_checks()["ai"]["model"],"test-model")
                self.assertEqual(self.store.rows("SELECT provider FROM usage_events")[0]["provider"],"ollama")
                rate=self.store.rows("SELECT * FROM usage_rates WHERE model=?",(DEFAULT_MODEL,))[0]
                self.assertEqual((rate["input"],rate["output"]),(0,0))
                self.assertTrue(all(r.method=="GET" for r in connector_requests))
                self.assertTrue(all(r.url.host=="github.example" for r in connector_requests))
                self.assertNotIn("private-token",response.text)
            finally:client.close()

    def test_cloud_failure_offers_fallback_but_does_not_invoke_local_inference(self):
        class Failed(FakeAI):
            def stream(self,**kwargs):raise httpx.ConnectError("Unreachable cloud")
        client,headers=self.client(client_factory=Failed)
        try:
            cid=self.store.new_conversation()
            response=client.post("/api/chat",headers=headers,json={"conversation":cid,"question":"Hello"})
            self.assertIn('"local_fallback": true',response.text)
            self.assertEqual(self.requests,[])
        finally:client.close()

    def test_large_current_request_continues_in_same_chat_without_changing_saved_text(self):
        question="Review PR 7 using the requested context:\n"+("context " * 3000)
        cid=self.store.new_conversation()
        self.store.save_turn(cid,[{"role":"user","content":"Earlier PR context."},
                                 {"role":"assistant","content":"Keep this saved answer."}])
        before=self.store.history(cid)
        native=Client
        with patch("app.ollama_local.Client",side_effect=lambda cfg:native(cfg,self.transport)):
            client,headers=self.client()
            try:
                response=client.post("/api/chat",headers=headers,json={
                    "conversation":cid,"question":question,"local_ai":True,"local_model":DEFAULT_MODEL})
                self.assertIn('"event": "done"',response.text)
                self.assertNotIn('"event": "error"',response.text)
                generated=[json.loads(r.content) for r in self.requests if r.url.path=="/api/chat"]
                self.assertTrue(generated)
                self.assertGreater(len(json.dumps(generated[0]).encode()),24000)
                self.assertIn(question,[r["content"] for r in generated[0]["messages"] if r["role"]=="user"])
                saved=self.store.history(cid)
                self.assertEqual(saved[:len(before)],before)
                self.assertIn(question,[r["content"] for r in saved if r["role"]=="user"])
            finally:client.close()

    def test_local_timeout_reports_error_cancels_work_and_does_not_save_a_turn(self):
        class Slow(httpx.AsyncByteStream):
            closed=False
            async def __aiter__(self):
                while True:
                    await asyncio.sleep(.02)
                    yield b'{"message":{"content":"<think>"},"done":false}\n'
            async def aclose(self):self.closed=True
        slow=Slow()
        def remote(request):
            if request.url.path=="/api/chat":return httpx.Response(200,stream=slow)
            if request.url.path=="/api/tags":
                return httpx.Response(200,json={"models":[{"name":DEFAULT_MODEL}]})
            return httpx.Response(200,json={"model_info":{"general.architecture":"qwen3"},"details":{"format":"gguf"}})
        native=Client
        with patch("app.ollama_local.Client",side_effect=lambda cfg:native(cfg,httpx.MockTransport(remote))),patch(
                "app.ollama_local.MAX_SECONDS",.2):
            client,headers=self.client()
            try:
                cid=self.store.new_conversation()
                response=client.post("/api/chat",headers=headers,json={"conversation":cid,"question":"Hello","local_ai":True})
                self.assertIn('"event": "local_status"',response.text)
                self.assertIn('"event": "error"',response.text)
                self.assertIn("2 minutes",response.text)
                self.assertNotIn('"event": "done"',response.text)
                self.assertTrue(slow.closed)
                self.assertEqual(self.store.rows("SELECT id FROM turns WHERE conversation=?",(cid,)),[])
            finally:client.close()

    def test_length_limited_reply_is_not_saved_but_reported_tokens_are_retained(self):
        self.mode="length";native=Client
        with patch("app.ollama_local.Client",side_effect=lambda cfg:native(cfg,self.transport)):
            client,headers=self.client()
            try:
                cid=self.store.new_conversation()
                response=client.post("/api/chat",headers=headers,json={"conversation":cid,"question":"Hello","local_ai":True})
                self.assertIn('"event": "error"',response.text)
                self.assertNotIn('"event": "done"',response.text)
                self.assertEqual(self.store.rows("SELECT id FROM turns WHERE conversation=?",(cid,)),[])
                self.assertEqual(json.loads(self.store.rows("SELECT tokens FROM usage_events")[0]["tokens"])["output_tokens"],4)
                self.assertEqual(self.store.rows("SELECT status FROM usage_calls")[0]["status"],"reported")
            finally:client.close()

    def test_loopback_csrf_opt_in_disabled_module_and_demo_boundaries(self):
        client,headers=self.client()
        try:
            cid=self.store.new_conversation()
            body={"conversation":cid,"question":"Hello","local_ai":True}
            self.assertEqual(client.post("/api/chat",json=body).status_code,403)
            with patch.dict(os.environ,{"AIMATE_LOCAL_AI_ENABLED":"0"}):
                self.assertEqual(client.post("/api/chat",headers=headers,json=body).status_code,400)
                self.assertFalse(client.get("/api/state").json()["local_ai"])
                self.assertEqual(client.get("/api/todos").status_code,200)
            body["local_ai"]="true"
            self.assertEqual(client.post("/api/chat",headers=headers,json=body).status_code,400)
        finally:client.close()
        for app in (create_app(self.store),create_app(self.store,demo=True)):
            with TestClient(app,base_url="http://127.0.0.1",client=("192.0.2.1",50000)) as remote:
                csrf=remote.post("/api/login",json={"password":self.store.password}).json()["csrf"]
                self.assertFalse(remote.get("/api/local-ai/status").json()["available"])
                self.assertEqual(remote.post("/api/chat",headers={"x-csrf-token":csrf},
                    json={"conversation":cid,"question":"Hello","local_ai":True}).status_code,400)

    def test_status_checks_models_only_and_missing_model_never_calls_generate(self):
        client,headers=self.client()
        try:
            with patch("app.local_ai.installed",new=AsyncMock(return_value=[DEFAULT_MODEL])):
                self.assertEqual(client.get("/api/local-ai/status").json()["models"],[DEFAULT_MODEL])
        finally:client.close()
        async def run():
            native=Client({"ai":{"model":"missing:small"}},self.transport)
            try:
                args=self.args();args["model"]="missing:small"
                with self.assertRaisesRegex(ValueError,"not installed"):await native.create(**args)
            finally:await native.close()
        asyncio.run(run());self.assertEqual(self.native_calls,0)

    def test_ollama_cloud_and_remote_aliases_never_receive_project_prompts(self):
        async def run():
            for name in ("qwen3:cloud","qwen3:4b"):
                self.mode="remote"
                client=Client({"ai":{"model":name}},self.transport)
                try:
                    args=self.args();args["model"]=name
                    with self.assertRaisesRegex(ValueError,"cloud|Remote"):await client.create(**args)
                finally:await client.close()
        asyncio.run(run());self.assertEqual(self.native_calls,0)
