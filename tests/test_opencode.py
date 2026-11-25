"""Fixed OpenCode routes, tool protocol and safe shared credentials; no external inference."""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx
import httpx2
from fastapi.testclient import TestClient
from app.opencode_bedrock import Client, DEFAULT, models, setup, message, portable_history
from app.agent import ai_error, run_turn
from app.store import Store
from app.validation import validate_config
from test_app import create_app, fixture_config


class OpenCodeTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(self.directory.name)
        self.config=fixture_config()
        self.config["ai"]={"provider":"opencode","model":DEFAULT,"region":"us-east-2",
                           "api_key":"synthetic-shared-key","bedrock_auth":"bearer"}
        self.store.save_config(self.config)
        self.requests=[];self.mode="answer"
        self.transport=httpx.MockTransport(self.handle)

    def tearDown(self):
        self.store.db.close();self.directory.cleanup()

    def handle(self,request):
        self.requests.append(request)
        self.assertEqual(request.url.host,"bedrock-runtime.us-east-2.amazonaws.com")
        self.assertEqual(request.headers["authorization"],"Bearer synthetic-shared-key")
        body=json.loads(request.content)
        self.assertNotIn("synthetic-shared-key",json.dumps(body))
        if self.mode=="denied":
            return httpx.Response(403,json={"error":"synthetic-shared-key"})
        if request.url.path=="/openai/v1/responses":
            self.assertFalse(body["store"])
            self.assertNotIn("reasoning",json.dumps(body["input"]))
            output=[{"type":"message","content":[{"type":"output_text","text":"Gateway replied."}]}]
            if self.mode=="read" and len(self.requests)==1:
                self.assertTrue(all(tool["type"]=="function" for tool in body["tools"]))
                output=[{"type":"function_call","call_id":"read1","name":"api_read",
                         "arguments":'{"service":"github","path":"/repos/team/repo/pulls/1"}'}]
            data={"status":"completed","model":body["model"],"output":output,
                  "usage":{"input_tokens":12,"output_tokens":3,"input_tokens_details":{"cached_tokens":4}}}
            if not body["stream"]:return httpx.Response(200,json=data)
            packets=[{"type":"response.output_text.delta","delta":"Gateway replied."}] if output[0]["type"]=="message" else []
            if self.mode!="truncated":packets.append({"type":"response.completed","response":data})
            return httpx.Response(200,headers={"content-type":"text/event-stream"},
                text="".join("data: "+json.dumps(p)+"\n\n" for p in packets))
        if request.url.path=="/anthropic/v1/messages":
            if body.get("stream"):
                packets=[
                    ("message_start",{"type":"message_start","message":{"id":"claude","type":"message","role":"assistant",
                     "model":body["model"],"content":[],"stop_reason":None,"stop_sequence":None,
                     "usage":{"input_tokens":4,"output_tokens":0}}}),
                    ("content_block_start",{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}),
                    ("content_block_delta",{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Claude streamed."}}),
                    ("content_block_stop",{"type":"content_block_stop","index":0}),
                    ("message_delta",{"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":None},"usage":{"output_tokens":2}}),
                    ("message_stop",{"type":"message_stop"})]
                return httpx.Response(200,headers={"content-type":"text/event-stream"},
                    text="".join("event: "+kind+"\ndata: "+json.dumps(packet)+"\n\n" for kind,packet in packets))
            return httpx.Response(200,json={"id":"claude","type":"message","role":"assistant",
                "model":body["model"],"content":[{"type":"text","text":"Claude replied."}],
                "stop_reason":"end_turn","stop_sequence":None,"usage":{"input_tokens":4,"output_tokens":2}})
        self.assertEqual(request.url.path,"/openai/v1/chat/completions")
        if ".openai." in body["model"] and body.get("tools"):
            return httpx.Response(400,json={"error":{"message":"Function tools require /v1/responses."}})
        usage={"prompt_tokens":12,"completion_tokens":3,"prompt_tokens_details":{"cached_tokens":4}}
        if not body["stream"]:
            return httpx.Response(200,json={"choices":[{"message":{"content":"Gateway replied."}}],
                                           "usage":usage})
        packets=[{"choices":[{"delta":{"content":"Gateway replied."},"finish_reason":None}]}]
        if self.mode=="read" and len(self.requests)==1:
            self.assertTrue(body["tools"])
            packets=[{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"read1","type":"function",
                "function":{"name":"api_read","arguments":'{"service":"github","path":"/repos/team/repo/pulls/1"}'}}]},
                "finish_reason":"tool_calls"}]}]
        else:
            packets.append({"choices":[{"delta":{},"finish_reason":"stop"}]})
        if self.mode=="truncated":packets=packets[:1]
        packets.append({"choices":[],"usage":usage})
        return httpx.Response(200,headers={"content-type":"text/event-stream"},
            text="".join("data: "+json.dumps(p)+"\n\n" for p in packets)+"data: [DONE]\n\n")

    def test_config_only_contains_environment_reference_and_exact_supplied_models(self):
        config=setup()
        self.assertEqual(len(config["provider"]),4)
        self.assertGreater(len(models()),30)
        for provider in config["provider"].values():
            self.assertEqual(provider["options"]["apiKey"],"{env:AWS_BEARER_TOKEN_BEDROCK}")
        with TestClient(create_app(self.store,demo=False)) as client:
            self.assertEqual(client.get("/api/opencode/config").status_code,401)
            client.post("/api/login",json={"password":self.store.password})
            self.assertEqual(client.get("/api/opencode/config").json(),config)
            self.assertEqual(client.get("/api/opencode/models").json()["models"],models())

    def test_shared_key_preserved_only_between_bedrock_providers(self):
        for provider in ("bedrock","bedrock-openai","opencode"):
            old={**self.config,"ai":{**self.config["ai"],"provider":provider}}
            raw={**self.config,"ai":{**self.config["ai"],"api_key":""}}
            self.assertEqual(validate_config(raw,old)["ai"]["api_key"],"synthetic-shared-key")
        old={**self.config,"ai":{"provider":"anthropic","api_key":"other-key"}}
        raw={**self.config,"ai":{**self.config["ai"],"api_key":""}}
        self.assertEqual(validate_config(raw,old)["ai"]["api_key"],"")
        raw["ai"]["model"]="https://example.com/unsafe"
        with self.assertRaises(ValueError):validate_config(raw,self.config)
        with patch.dict(os.environ,{"AIMATE_OPENCODE_ENABLED":"0"}):
            with self.assertRaises(ValueError):Client(self.config)
            with TestClient(create_app(self.store,demo=False)) as client:
                client.post("/api/login",json={"password":self.store.password})
                self.assertFalse(client.get("/api/opencode/models").json()["enabled"])

    def test_all_four_families_and_usage_are_translated(self):
        async def run():
            def sdk_handle(request):
                response=self.handle(request)
                return httpx2.Response(response.status_code,content=response.content,headers=dict(response.headers))
            client=Client(self.config,self.transport,httpx2.MockTransport(sdk_handle))
            try:
                for family in setup()["provider"]:
                    model=next(row["id"] for row in models() if row["id"].startswith(family+"/"))
                    result=await client.create(model=model,max_tokens=16,messages=[{"role":"user","content":"Hi"}])
                    self.assertEqual(result.model,model)
                    self.assertTrue(result.content[0].text)
                    if "anthropic" not in family:
                        self.assertEqual(result.usage.input_tokens,8)
                        self.assertEqual(result.usage.cache_read_input_tokens,4)
            finally:await client.close()
        asyncio.run(run())
        self.assertIsNone(message(DEFAULT,"No usage",[],None).usage)

    def test_claude_stream_uses_single_v1_and_requested_profile(self):
        async def run():
            def sdk_handle(request):
                response=self.handle(request)
                return httpx2.Response(response.status_code,content=response.content,headers=dict(response.headers))
            client=Client(self.config,self.transport,httpx2.MockTransport(sdk_handle))
            model="bedrock-runtime-anthropic/us.anthropic.claude-sonnet-5-5"
            try:
                async with client.stream(model=model,max_tokens=16,messages=[{"role":"user","content":"Hi"}]) as stream:
                    text="".join([part async for part in stream.text_stream])
                    result=await stream.get_final_message()
                self.assertEqual(text,"Claude streamed.")
                self.assertEqual(result.model,model)
                self.assertEqual(result.usage.output_tokens,2)
            finally:await client.close()
        asyncio.run(run())

    def test_tool_fragments_cached_usage_and_unreported_usage(self):
        packets=[
            {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"read1","function":{"name":"api_read","arguments":'{"service":'}}]}}]},
            {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":'"github","path":"/repos/team/repo"}'}}]},"finish_reason":"tool_calls"}]},
            {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":2,"prompt_tokens_details":{"cached_tokens":3}}}]
        async def run():
            def handle(request):
                return httpx.Response(200,headers={"content-type":"text/event-stream"},
                    text="".join("data: "+json.dumps(p)+"\n\n" for p in packets)+"data: [DONE]\n\n")
            client=Client(self.config,httpx.MockTransport(handle))
            try:
                model="bedrock-runtime-kimi/us.moonshotai.kimi-k3.1"
                async with client.stream(model=model,max_tokens=16,messages=[{"role":"user","content":"Read"}]) as stream:
                    result=await stream.get_final_message()
                self.assertEqual(result.content[0].input["service"],"github")
                self.assertEqual(result.usage.input_tokens,6)
                self.assertEqual(result.usage.cache_read_input_tokens,3)
            finally:await client.close()
        asyncio.run(run())

    def test_streamed_read_evidence_keeps_existing_scopes_and_history(self):
        self.mode="read"
        class Services:
            def __init__(self,config):pass
            async def read(self,service,path,params=None):
                return {"source":"https://api.github.com"+path,"data":{"title":"Synthetic PR"}}
        cid=self.store.new_conversation()
        async def run():
            return [event async for event in run_turn(self.store,cid,"Read PR 1",
                client_factory=lambda c:Client(c,self.transport),services_factory=Services)]
        events=asyncio.run(run())
        self.assertEqual(events[-1]["event"],"done")
        self.assertTrue(any(event["event"]=="source" for event in events))
        self.assertTrue(self.store.history(cid))
        self.assertEqual(len(self.requests),2)
        second=json.loads(self.requests[1].content)
        self.assertTrue(any(row.get("type")=="function_call_output" and "Synthetic PR" in row["output"] for row in second["input"]))
        self.assertFalse(self.store.rows("SELECT * FROM actions"))
        self.assertNotIn("synthetic-shared-key",json.dumps(events))
        self.assertEqual(self.store.rows("SELECT provider FROM usage_events")[0]["provider"],"opencode")

    def test_gpt_responses_preserve_portable_calls_images_and_ignore_old_reasoning(self):
        old=[{"role":"assistant","content":[{"type":"thinking","thinking":"old signed reasoning","signature":"old-signature"},
             {"type":"responses","items":[{"type":"reasoning","encrypted_content":"opaque"},
              {"type":"function_call","call_id":"old1","name":"api_read","arguments":'{"service":"github","path":"/repos/team/repo"}'}]}]},
             {"role":"user","content":[{"type":"tool_result","tool_use_id":"old1","content":"Historical evidence"}]},
             {"role":"user","content":[{"type":"text","text":"Read this"},
              {"type":"image","source":{"media_type":"image/png","data":"synthetic"}}]}]
        client=Client(self.config,self.transport)
        async def run():
            try:
                body=client.payload({"model":DEFAULT,"max_tokens":4096,"messages":portable_history(old),
                    "tools":[{"name":"api_read","input_schema":{"type":"object"}}]},True)
                self.assertEqual(body["max_output_tokens"],4096)
                self.assertFalse(body["store"])
                call=next(row for row in body["input"] if row.get("type")=="function_call")
                output=next(row for row in body["input"] if row.get("type")=="function_call_output")
                self.assertEqual(call["call_id"],output["call_id"])
                self.assertNotIn("old-signature",json.dumps(body))
                self.assertNotIn("opaque",json.dumps(body))
                self.assertTrue(any(isinstance(row.get("content"),list) and
                    any(part.get("type")=="input_image" for part in row["content"]) for row in body["input"]))
            finally:await client.close()
        asyncio.run(run())

    def test_errors_truncation_and_text_only_images_do_not_leak(self):
        async def run():
            client=Client(self.config,self.transport)
            try:
                self.mode="denied"
                try:await client.create(model=DEFAULT,max_tokens=16,messages=[{"role":"user","content":"Hi"}])
                except Exception as exc:
                    self.assertIn("access denied",ai_error(exc))
                    self.assertNotIn("synthetic-shared-key",ai_error(exc))
                self.mode="truncated"
                with self.assertRaisesRegex(ValueError,"ended before"):
                    async with client.stream(model=DEFAULT,max_tokens=16,messages=[{"role":"user","content":"Hi"}]) as stream:
                        async for _ in stream.text_stream:pass
                glm=next(row["id"] for row in models() if not row["vision"])
                before=len(self.requests)
                with self.assertRaisesRegex(ValueError,"text-only"):
                    await client.create(model=glm,max_tokens=16,messages=[{"role":"user","content":[
                        {"type":"image","source":{"media_type":"image/png","data":"synthetic"}}]}])
                self.assertEqual(len(self.requests),before)
            finally:await client.close()
        asyncio.run(run())
