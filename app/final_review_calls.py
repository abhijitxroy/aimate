"""Tool-free, metered calls; a CLI/tool brand is never executed as a reviewer."""
import copy
import asyncio

from app.connectors import scrub
from app.usage_meter import Call


async def call(store, profile, prompt, system, client_factory, chatgpt, access_check,
               *, max_tokens=8192, origin="Final PR review"):
    config = copy.deepcopy(store.config())
    config["ai"] = copy.deepcopy(profile["ai"])
    config["allow_writes"] = False
    access_check()
    from app.vault import redactions
    config["_vault_secrets"] = redactions(store)
    prompt = scrub(prompt, config)
    provider = config["ai"]["provider"]
    model = config["ai"]["model"]
    with Call(store, config, model, origin) as meter:
        if provider == "chatgpt":
            from app.chatgpt import response_events
            if not chatgpt:
                raise ValueError("ChatGPT is unavailable for this workspace.")
            response = None
            payload = {"model": model, "input": [{"role": "user", "content": prompt}],
                       "instructions": system, "store": False, "stream": True}
            async with asyncio.timeout(180):
                async for event in response_events(chatgpt, payload, config["ai"]["account"]):
                    access_check()
                    if event["type"] == "response.completed":
                        response = event["response"]
            if not response or response.get("status", "completed") != "completed":
                raise ValueError("The reviewer did not complete its response.")
            meter.complete(response)
            text = "".join(part.get("text", "") for item in response.get("output", [])
                           if item.get("type") == "message" for part in item.get("content", [])
                           if part.get("type") == "output_text")
            usage = response.get("usage") or {}
        else:
            client = client_factory(config)
            if asyncio.iscoroutine(client):
                client = await client
            try:
                args = {"model": model, "max_tokens": max_tokens, "system": system,
                        "messages": [{"role": "user", "content": prompt}]}
                if provider == "bedrock-openai":
                    args["messages"].insert(0, {"role": "system", "content": system})
                async with asyncio.timeout(180):
                    response = await client.messages.create(**args)
                access_check()
                meter.complete(response)
                if getattr(response, "stop_reason", None) in {"max_tokens", "tool_use", "refusal"}:
                    raise ValueError("The reviewer did not finish a tool-free report. Coverage remains incomplete.")
                text = "".join(block.text for block in response.content if block.type == "text")
                incoming = getattr(response, "usage", None)
                usage = incoming if isinstance(incoming, dict) else (
                    incoming.model_dump() if hasattr(incoming, "model_dump") else vars(incoming) if incoming else {})
            finally:
                await client.close()
    access_check()
    if not text.strip() or len(text) > 100_000:
        raise ValueError("The reviewer returned no usable bounded report.")
    return scrub(text, config), usage
