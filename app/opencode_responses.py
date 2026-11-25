"""GPT function tools require Bedrock Responses, not Chat Completions."""
import json


def payload(args,ident,converted,stream):
    items=[]
    for row in converted:
        if row["role"]=="tool":
            items.append({"type":"function_call_output","call_id":row["tool_call_id"],"output":row["content"]})
            continue
        content=row.get("content")
        if isinstance(content,list):
            content=[{"type":"input_image","image_url":block["image_url"]["url"]} if block["type"]=="image_url"
                     else {"type":"input_text" if row["role"]=="user" else "output_text","text":block["text"]}
                     for block in content]
        if content:items.append({"role":row["role"],"content":content})
        for call in row.get("tool_calls",[]):
            items.append({"type":"function_call","call_id":call["id"],"name":call["function"]["name"],
                          "arguments":call["function"]["arguments"]})
    body={"model":ident,"input":items,"store":False,"stream":stream,
          "max_output_tokens":max(256,args["max_tokens"])}
    if args.get("tools"):
        body["tools"]=[{"type":"function","name":tool["name"],"description":tool.get("description",""),
                       "parameters":tool["input_schema"],"strict":False} for tool in args["tools"]]
    if args.get("tool_choice",{}).get("type")=="none":body["tool_choice"]="none"
    return body


def result(data,model,message):
    if data.get("status")!="completed":
        raise ValueError("The OpenCode GPT response did not complete. Retry with a smaller request.")
    text=[];calls=[]
    for item in data.get("output",[]):
        if item.get("type")=="message":
            text.extend(part["text"] for part in item.get("content",[]) if part.get("type")=="output_text")
        elif item.get("type")=="function_call":
            calls.append({"id":item["call_id"],"function":{"name":item["name"],"arguments":item["arguments"]}})
    usage=data.get("usage")
    if usage is not None:
        usage={"prompt_tokens":usage.get("input_tokens",0),"completion_tokens":usage.get("output_tokens",0),
               "prompt_tokens_details":usage.get("input_tokens_details") or {}}
    return message(model,"".join(text),calls,usage)


class Stream:
    def __init__(self,response,model,message):
        self.response,self.model,self.message=response,model,message
        self.final=None;self.done=False;self.text_stream=self.deltas()

    async def deltas(self):
        size=0;lines=[]
        async for line in self.response.aiter_lines():
            size+=len(line)
            if size>4_000_000:raise ValueError("The OpenCode GPT stream exceeded the supported size.")
            if line.startswith("data:"):lines.append(line[5:].lstrip())
            elif not line and lines:
                raw="\n".join(lines);lines=[]
                if raw=="[DONE]":continue
                try:event=json.loads(raw)
                except ValueError:raise ValueError("The OpenCode GPT stream returned invalid data.") from None
                if not isinstance(event,dict):raise ValueError("The OpenCode GPT stream returned invalid data.")
                kind=event.get("type")
                if kind in {"error","response.failed","response.incomplete"}:
                    raise ValueError("The OpenCode GPT response did not complete. Retry with a smaller request.")
                if kind=="response.output_text.delta":
                    delta=event.get("delta","")
                    if not isinstance(delta,str):raise ValueError("Invalid OpenCode GPT text delta.")
                    yield delta
                elif kind=="response.completed":
                    try:self.final=result(event["response"],self.model,self.message)
                    except (KeyError,TypeError,AttributeError):
                        raise ValueError("The OpenCode GPT response returned invalid data.") from None
        if self.final is None:raise ValueError("The OpenCode stream ended before the reply completed. Retry the request.")
        self.done=True

    async def get_final_message(self):
        if not self.done:
            async for _ in self.text_stream:pass
        return self.final
