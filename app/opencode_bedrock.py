"""OpenCode portal presets using the same fixed Bedrock gateways, without running a CLI."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import ssl
import httpx
import httpx2
from anthropic import AsyncAnthropic
from anthropic.types import Message

PROVIDER="opencode"
DEFAULT="bedrock-runtime-openai/us.openai.gpt-6.2-sol"
OPENAI_URL="https://bedrock-runtime.us-east-2.amazonaws.com/openai/v1"
ANTHROPIC_URL="https://bedrock-runtime.us-east-2.amazonaws.com/anthropic/v1"

class GatewayError(Exception):
    """Expose only the status code to the existing safe AI diagnostics."""
    def __init__(self,status):
        super().__init__("OpenCode gateway request failed.")
        self.status_code=status


def check_response(response):
    if not 200<=response.status_code<300:
        raise GatewayError(response.status_code)


def enabled():
    return os.environ.get("AIMATE_OPENCODE_ENABLED") != "0"


def setup():
    data=json.loads(Path(__file__).with_name("opencode_setup.json").read_text(encoding="utf-8"))
    for provider in data["provider"].values():
        if provider["options"] not in ({"apiKey":"{env:AWS_BEARER_TOKEN_BEDROCK}","baseURL":OPENAI_URL},
                                       {"apiKey":"{env:AWS_BEARER_TOKEN_BEDROCK}","baseURL":ANTHROPIC_URL}):
            raise ValueError("OpenCode presets must contain fixed AWS gateways and environment references only.")
    return data


def models():
    return [{"id":family+"/"+ident,"title":model["name"],"vision":bool(model.get("attachment")),
             "premium":any(word in ident for word in ("astra","fable"))}
            for family,provider in setup()["provider"].items() for ident,model in provider["models"].items()]


def resolve(model):
    if not isinstance(model,str) or model not in {item["id"] for item in models()}:
        raise ValueError("Choose an OpenCode model from the supplied portal catalog.")
    return model.split("/",1)


def validate(ai):
    if not enabled():
        raise ValueError("OpenCode is disabled on this server.")
    ai["region"]=ai.get("region") or "us-east-2"
    ai["model"]=ai.get("model") or DEFAULT
    if ai.get("region")!="us-east-2" or ai.get("bedrock_auth","bearer")!="bearer":
        raise ValueError("These OpenCode presets use us-east-2 and a Bedrock bearer key.")
    resolve(ai["model"])
    if ai.get("analysis_model"):
        resolve(ai["analysis_model"])


def register(app,auth):
    from fastapi import Depends

    @app.get("/api/opencode/models")
    def catalog(session=Depends(auth)):
        return {"enabled":enabled(),"models":models() if enabled() else [],
                "message":"Portal setup presets, not live entitlement discovery. Save & test verifies the selected model."}

    @app.get("/api/opencode/config")
    def configuration(session=Depends(auth)):
        if not enabled():
            raise ValueError("OpenCode is disabled on this server.")
        return setup()


def chat_messages(messages,system=""):
    result=[{"role":"system","content":system}] if system else []
    for message in messages:
        role,content=message["role"],message["content"]
        if isinstance(content,str):
            result.append({"role":role,"content":content});continue
        texts=[];images=[];calls=[];results=[]
        for block in content:
            kind=block.get("type")
            if kind=="text":texts.append(block.get("text",""))
            elif kind=="image":
                source=block["source"];images.append({"type":"image_url","image_url":{"url":"data:"+source["media_type"]+";base64,"+source["data"]}})
            elif kind=="tool_use":calls.append({"id":block["id"],"type":"function","function":{"name":block["name"],"arguments":json.dumps(block["input"])}})
            elif kind=="tool_result":results.append({"role":"tool","tool_call_id":block["tool_use_id"],"content":block.get("content","")})
        if texts or images or calls:
            row={"role":role,"content":[{"type":"text","text":"\n\n".join(texts)},*images] if images else "\n\n".join(texts)}
            if calls:row["tool_calls"]=calls
            result.append(row)
        result.extend(results)
    return result


def message(model,text,calls,usage):
    blocks=[{"type":"text","text":text}] if text else []
    for call in calls:
        try:arguments=json.loads(call["function"]["arguments"] or "{}")
        except (ValueError,KeyError):raise ValueError("The model returned invalid tool arguments.") from None
        if not isinstance(arguments,dict):raise ValueError("The model returned invalid tool arguments.")
        blocks.append({"type":"tool_use","id":call["id"],"name":call["function"]["name"],"input":arguments})
    incoming=None
    if usage is not None:
        prompt=usage.get("prompt_tokens",0);cached=(usage.get("prompt_tokens_details") or {}).get("cached_tokens",0)
        output=usage.get("completion_tokens",0)
        if any(type(n) is not int or n<0 for n in (prompt,cached,output)) or cached>prompt:
            raise ValueError("The gateway returned invalid usage counts.")
        incoming={"input_tokens":prompt-cached,"output_tokens":output,"cache_read_input_tokens":cached}
    try:
        result=Message.model_validate({"id":"opencode-reply","type":"message","role":"assistant","model":model,
                                      "content":blocks,"stop_reason":"tool_use" if calls else "end_turn",
                                      "stop_sequence":None,"usage":incoming or {"input_tokens":0,"output_tokens":0}})
    except ValueError:
        raise ValueError("The OpenCode gateway returned an invalid reply.") from None
    return result if incoming is not None else result.model_copy(update={"usage":None})


class Client:
    def __init__(self,config,transport=None,anthropic_transport=None):
        self.ai=dict(config["ai"]);validate(self.ai)
        if not self.ai.get("api_key"):raise ValueError("Add your Bedrock key in AiMate settings.")
        self.messages=self
        self.http=httpx.AsyncClient(headers={"Authorization":"Bearer "+self.ai["api_key"]},
                                   transport=transport,verify=ssl.create_default_context(),timeout=90,follow_redirects=False)
        # Anthropic's Python SDK appends /v1/messages itself.
        self.anthropic=AsyncAnthropic(api_key=self.ai["api_key"],base_url=ANTHROPIC_URL.removesuffix("/v1"),
            default_headers={"Authorization":"Bearer "+self.ai["api_key"]},
            http_client=httpx2.AsyncClient(transport=anthropic_transport,verify=ssl.create_default_context(),timeout=90,follow_redirects=False),
            max_retries=0)

    def payload(self,args,stream=False):
        family,ident=resolve(args["model"])
        converted=chat_messages(args["messages"],args.get("system",""))
        model=next(row for row in models() if row["id"]==args["model"])
        if not model["vision"] and any(isinstance(m.get("content"),list) and any(b.get("type")=="image_url" for b in m["content"]) for m in converted):
            raise ValueError("This GLM model is text-only. Choose a vision-capable OpenCode model for screenshots.")
        body={"model":ident,"messages":converted,"stream":stream}
        body["max_completion_tokens" if family=="bedrock-runtime-openai" else "max_tokens"]=args["max_tokens"]
        if args.get("tools"):
            body["tools"]=[{"type":"function","function":{"name":tool["name"],"description":tool.get("description",""),"parameters":tool["input_schema"]}} for tool in args["tools"]]
        if args.get("tool_choice",{}).get("type")=="none":body["tool_choice"]="none"
        if stream:body["stream_options"]={"include_usage":True}
        return body

    async def create(self,**args):
        family,ident=resolve(args["model"])
        if family=="bedrock-runtime-anthropic":
            result=await self.anthropic.messages.create(**{**args,"model":ident})
            return result.model_copy(update={"model":args["model"]})
        response=await self.http.post(OPENAI_URL+"/chat/completions",json=self.payload(args));check_response(response)
        if len(response.content)>2_000_000:
            raise ValueError("The OpenCode gateway reply exceeds the supported size.")
        try:
            data=response.json();choice=data["choices"][0]["message"]
            return message(args["model"],choice.get("content") or "",choice.get("tool_calls") or [],data.get("usage"))
        except (ValueError,KeyError,IndexError,TypeError,AttributeError):
            raise ValueError("The OpenCode gateway returned an invalid reply.") from None

    @asynccontextmanager
    async def stream(self,**args):
        family,ident=resolve(args["model"])
        if family=="bedrock-runtime-anthropic":
            async with self.anthropic.messages.stream(**{**args,"model":ident}) as stream:
                yield AnthropicStream(stream,args["model"])
        else:
            async with self.http.stream("POST",OPENAI_URL+"/chat/completions",json=self.payload(args,True)) as response:
                check_response(response);yield ChatStream(response,args["model"])

    async def close(self):
        await self.http.aclose();await self.anthropic.close()


class AnthropicStream:
    def __init__(self,source,model):
        self.source,self.model=source,model;self.text_stream=source.text_stream

    async def get_final_message(self):
        result=await self.source.get_final_message()
        return result.model_copy(update={"model":self.model})


class ChatStream:
    def __init__(self,response,model):
        self.response,self.model=response,model
        self.text="";self.calls={};self.usage=None;self.done=False;self.finished=False;self.text_stream=self.deltas()

    async def deltas(self):
        async for line in self.response.aiter_lines():
            if not line.startswith("data:"):continue
            raw=line[5:].strip()
            if raw=="[DONE]":break
            if len(raw)>250000:raise ValueError("Gateway stream event exceeds the supported size.")
            try:packet=json.loads(raw)
            except ValueError:raise ValueError("The OpenCode gateway returned an invalid stream.") from None
            if not isinstance(packet,dict):raise ValueError("The OpenCode gateway returned an invalid stream.")
            if packet.get("error"):raise ValueError("The OpenCode gateway rejected the stream. Check the key and selected model.")
            if packet.get("usage") is not None:self.usage=packet["usage"]
            for choice in packet.get("choices",[])[:1]:
                if choice.get("finish_reason")=="length":
                    raise ValueError("The OpenCode reply reached its output limit. Ask for a smaller section.")
                if choice.get("finish_reason") in {"stop","tool_calls"}:self.finished=True
                delta=choice.get("delta",{})
                text=delta.get("content") or ""
                if not isinstance(text,str) or len(self.text)+len(text)>1_000_000:raise ValueError("Gateway reply exceeds the supported size.")
                self.text+=text
                if text:yield text
                for item in delta.get("tool_calls",[]):
                    index=item.get("index",0)
                    if type(index) is not int or not 0<=index<64:raise ValueError("Invalid gateway tool index.")
                    target=self.calls.setdefault(index,{"id":"","function":{"name":"","arguments":""}})
                    if item.get("id"):target["id"]=item["id"]
                    for key in ("name","arguments"):
                        target["function"][key]+=item.get("function",{}).get(key,"")
                        if len(target["function"][key])>250000:raise ValueError("Gateway tool arguments exceed the supported size.")
        if not self.finished:raise ValueError("The OpenCode stream ended before the reply completed. Retry the request.")
        self.done=True

    async def get_final_message(self):
        if not self.done:
            async for _ in self.text_stream:pass
        return message(self.model,self.text,[self.calls[k] for k in sorted(self.calls)],self.usage)
