"""Optional loopback-only Ollama inference; never downloads models or reads credentials."""
import json
import os
import re
import secrets
from types import SimpleNamespace
import httpx
from app.local_prompt_budget import MAX_PROMPT_BYTES, fit, size

URL="http://127.0.0.1:11434"
DEFAULT_MODEL="qwen3:4b"
MAX_RESPONSE_BYTES=1_000_000


def enabled():
    return os.environ.get("AIMATE_LOCAL_AI_ENABLED") != "0"


def model_name(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}",value):
        raise ValueError("Choose an installed local model name.")
    return value


def messages(rows):
    output=[];calls={}
    for row in rows:
        content=row.get("content")
        if isinstance(content,str):
            output.append({"role":row["role"],"content":content});continue
        text=[];uses=[];results=[]
        for block in content or []:
            kind=block.get("type")
            if kind=="image":
                raise ValueError("This local fallback is text-only. Remove images or use a cloud vision model.")
            if kind=="text":text.append(block.get("text",""))
            elif kind=="tool_use":
                calls[block["id"]]=block["name"]
                uses.append({"function":{"name":block["name"],"arguments":block["input"]}})
            elif kind=="tool_result":
                results.append({"role":"tool","tool_name":calls.get(block["tool_use_id"],"unknown"),
                    "content":str(block.get("content",""))})
            elif kind=="responses":
                # Foreign provider state is evidence, never a native Ollama signature.
                for item in block.get("items",[]):
                    if item.get("type")=="function_call_output":
                        text.append("Earlier tool evidence: "+str(item.get("output","")))
        if text or uses:
            converted={"role":row["role"],"content":"\n\n".join(text)}
            if uses:converted["tool_calls"]=uses
            output.append(converted)
        output.extend(results)
    return output


def payload(args,stream):
    model=model_name(args["model"])
    rows=[{"role":"system","content":args.get("system","")},*messages(args["messages"])]
    tools=[] if args.get("tool_choice",{}).get("type")=="none" else [
        {"type":"function","function":{"name":t["name"],"description":t.get("description",""),
            "parameters":t["input_schema"]}} for t in args.get("tools",[])]
    result={"model":model,"messages":rows,"stream":stream,"think":False,
        "options":{"num_ctx":32768,"num_predict":min(4096,max(1,args.get("max_tokens",4096)))}}
    if tools:result["tools"]=tools
    result=fit(result)
    if size(result)>MAX_PROMPT_BYTES:
        raise ValueError("The local request still exceeds 64 KB after automatic context compaction. Your question and saved chat were kept intact. Attach long text as a document and ask about a section, or choose a cloud model.")
    return result


class Block:
    def __init__(self,**value):
        self.value=value
        for key,item in value.items():setattr(self,key,item)
    def model_dump(self,**kwargs):return self.value


def result(model,text,calls,final):
    if not final or final.get("done") is not True:
        raise ValueError("Local inference ended before completion; the reply was not saved.")
    if final.get("done_reason")=="length":
        raise ValueError("The local reply reached its output limit; narrow the request before retrying.")
    blocks=[Block(type="text",text=text)] if text else []
    nonce=secrets.token_hex(8)
    if len(calls)>32:raise ValueError("Local model returned too many tool calls.")
    for index,call in enumerate(calls):
        function=call.get("function",{})
        name,arguments=function.get("name"),function.get("arguments")
        if not isinstance(name,str) or not isinstance(arguments,dict):
            raise ValueError("Local model returned invalid tool arguments.")
        blocks.append(Block(type="tool_use",id="local-"+nonce+"-"+str(index),name=name,input=arguments))
    counts={key:final.get(source) for key,source in
        (("input_tokens","prompt_eval_count"),("output_tokens","eval_count"))}
    usage=SimpleNamespace(**counts) if all(type(n) is int and n>=0 for n in counts.values()) else None
    return SimpleNamespace(model=model,content=blocks,usage=usage)


async def installed(http):
    try:
        response=await http.get(URL+"/api/tags",timeout=3)
        if response.status_code!=200:
            raise ValueError("Ollama is not ready. Start Ollama on this laptop.")
        if len(response.content)>200_000:
            raise ValueError("Ollama returned an oversized model list.")
        data=response.json()
        names=[model_name(row["name"]) for row in data["models"]
               if not any(marker in str(row.get("name","")).lower() for marker in ("-cloud",":cloud"))]
        return names[:100]
    except httpx.HTTPError:
        raise ValueError("Ollama is not reachable on this laptop. Start it, then check local access.") from None
    except (KeyError,TypeError):
        raise ValueError("Ollama returned an invalid model list.") from None


class Client:
    def __init__(self,config,transport=None):
        if not enabled():raise ValueError("Local AI is disabled.")
        self.model=model_name(config.get("ai",{}).get("model",DEFAULT_MODEL))
        self.http=httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,timeout=180)
        self.messages=self
        self.verified=set()
        self.legacy_thinking=set()

    async def verify(self,model):
        if any(marker in model.lower() for marker in ("-cloud",":cloud")):
            raise ValueError("Ollama cloud models cannot be used as an offline fallback. Choose downloaded local weights.")
        if model not in self.verified:
            if model not in await installed(self.http):
                raise ValueError("Local model "+model+" is not installed. Run: ollama pull "+model)
            response=await self.http.post(URL+"/api/show",json={"model":model})
            if response.status_code!=200 or len(response.content)>200_000:
                raise ValueError("Local model metadata is unavailable.")
            data=response.json()
            if (data.get("remote_host") or data.get("remote_model") or
                    data.get("details",{}).get("format")!="gguf" or
                    not data.get("model_info",{}).get("general.architecture")):
                raise ValueError("Choose a downloaded local GGUF model. Remote/cloud models cannot receive an offline request.")
            if model.startswith("qwen3:"):
                template=data.get("template","")
                if isinstance(template,str) and template.rstrip().endswith("<think>\n{{ end }}\n{{- end }}"):
                    self.legacy_thinking.add(model)
            self.verified.add(model)

    async def create(self,**args):
        body=payload(args,False);await self.verify(body["model"])
        try:response=await self.http.post(URL+"/api/chat",json=body)
        except httpx.HTTPError:raise ValueError("Local inference failed. Check Ollama and retry.") from None
        if response.status_code!=200 or len(response.content)>MAX_RESPONSE_BYTES:
            raise ValueError("Ollama rejected this request. Check the installed model and available memory.")
        data=response.json();message=data.get("message",{});text=message.get("content","")
        if body["model"] in self.legacy_thinking:
            if "</think>" not in text and not message.get("tool_calls"):
                raise ValueError("The local model did not separate its reply from reasoning. Retry a narrower question.")
            text=text.split("</think>",1)[1].lstrip() if "</think>" in text else ""
        return result(body["model"],text,message.get("tool_calls",[]),data)

    def stream(self,**args):return Stream(self,args)
    async def close(self):await self.http.aclose()


class Stream:
    def __init__(self,owner,args):
        self.owner,self.args=owner,args;self.text="";self.calls=[];self.final=None;self.total=0;self.thought_buffer=""
    async def __aenter__(self):
        self.body=payload(self.args,True);await self.owner.verify(self.body["model"])
        self.thinking=self.body["model"] in self.owner.legacy_thinking
        self.context=self.owner.http.stream("POST",URL+"/api/chat",json=self.body)
        try:self.response=await self.context.__aenter__()
        except httpx.HTTPError:raise ValueError("Local inference failed. Check Ollama and retry.") from None
        if self.response.status_code!=200:
            await self.context.__aexit__(None,None,None)
            raise ValueError("Ollama rejected this request. Check the installed model and available memory.")
        return self
    @property
    def text_stream(self):
        async def chunks():
            try:
                async for line in self.response.aiter_lines():
                    self.total+=len(line.encode("utf-8"))
                    if self.total>MAX_RESPONSE_BYTES:raise ValueError("Local reply exceeded the 1 MB response limit.")
                    if not line:continue
                    data=json.loads(line)
                    if "error" in data:raise ValueError("Local inference failed. Check available memory and retry.")
                    message=data.get("message",{});text=message.get("content","")
                    if not isinstance(text,str) or not isinstance(message.get("tool_calls",[]),list):
                        raise ValueError("Ollama returned invalid reply data.")
                    self.calls.extend(message.get("tool_calls",[]))
                    if self.thinking:
                        self.thought_buffer+=text
                        if "</think>" in self.thought_buffer:
                            text=self.thought_buffer.split("</think>",1)[1].lstrip()
                            self.thinking=False;self.thought_buffer=""
                        else:text=""
                    if text:self.text+=text;yield text
                    if data.get("done"):
                        self.final=data;break
            except httpx.HTTPError:raise ValueError("Local inference was interrupted; the reply was not saved.") from None
        return chunks()
    async def get_final_message(self):
        if self.thinking and not self.calls:
            raise ValueError("The local model did not separate its reply from reasoning. Retry a narrower question.")
        return result(self.body["model"],self.text,self.calls,self.final)
    def usage_snapshot(self):
        if not self.final:return None
        counts={key:self.final.get(source) for key,source in
            (("input_tokens","prompt_eval_count"),("output_tokens","eval_count"))}
        if not all(type(n) is int and n>=0 for n in counts.values()):return None
        return SimpleNamespace(model=self.body["model"],usage=SimpleNamespace(**counts))
    async def __aexit__(self,*args):return await self.context.__aexit__(*args)
