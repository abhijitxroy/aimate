"""Optional GPT adapter for Bedrock's OpenAI-compatible Responses endpoint."""
import copy
import hashlib
import json
import os
import re
import ssl
from types import SimpleNamespace

import httpx

PROVIDER = "bedrock-openai"
DEFAULT_MODEL = "us.openai.gpt-6.2-sol"
REGION = "us-east-2"
MODELS = [
    {"id": f"{route}.openai.{model}", "title": f"{title} · {route.upper()}"}
    for route in ("us", "global")
    for model, title in (("gpt-6.2-sol", "GPT-6.2 Sol"),
                         ("gpt-6.1-terra", "GPT-6.1 Terra"),
                         ("gpt-6.1-sol", "GPT-6.1 Sol"),
                         ("gpt-6-sol", "GPT-6 Sol"),
                         ("gpt-6-luna", "GPT-6 Luna"))
]


def enabled():
    return os.environ.get("AIMATE_BEDROCK_GPT_ENABLED", "1").lower() not in {"0", "false"}


def validate(ai):
    if not enabled():
        raise ValueError("GPT via Bedrock is disabled on this server.")
    ai.setdefault("region", REGION)
    if ai.get("bedrock_mode", "simple") == "simple":
        ai["region"] = REGION
    ai.update(bedrock_auth="bearer", bedrock_endpoint="runtime")
    ai["model"] = ai.get("model") or DEFAULT_MODEL
    for model in (ai["model"], ai.get("analysis_model")):
        if not model:
            continue
        if not re.fullmatch(r"(us|global)\.openai\.[a-z0-9][a-z0-9.-]{0,160}", model):
            raise ValueError("Use the exact us.openai or global.openai inference profile ID.")
        if model.split(".openai.", 1)[-1] in {"gpt-5.6-sol", "gpt-5.6-luna"}:
            raise ValueError("That profile is retired. Choose GPT-6.2 Sol, GPT-6.1 Sol or GPT-6 Luna.")


def register(app, auth):
    from fastapi import Depends

    @app.get("/api/bedrock/gpt/models")
    def catalog(session=Depends(auth)):
        return {"enabled": enabled(), "models": MODELS if enabled() else [],
                "message": "Setup presets; access is verified only by Save & test. No live model discovery was performed."}


class Connection:
    label = "GPT via Bedrock"

    def __init__(self, config, store=None, transport=None):
        self.ai = copy.deepcopy(config.get("ai", {}))
        validate(self.ai)
        region = self.ai["region"]
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-\d+", region):
            raise ValueError("Use an AWS region such as us-east-2.")
        self.url = f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1/responses"
        self.store, self.transport = store, transport
        self.messages = self

    @staticmethod
    def fingerprint(ai):
        return hashlib.sha256(json.dumps(
            [ai.get("provider"), ai.get("region", REGION), ai.get("api_key")]).encode()).hexdigest()

    def status(self):
        current = self.store.config().get("ai", {}) if self.store else self.ai
        return {"connected": bool(enabled() and current.get("api_key") and
                                  current.get("provider") == PROVIDER),
                "active": self.fingerprint(current)}

    async def models(self):
        # These are configured IDs, not a claim about account entitlement.
        return [{"slug": model, "display_name": model}
                for model in dict.fromkeys((self.ai["model"], self.ai.get("analysis_model")))
                if model]

    def client(self):
        return httpx.AsyncClient(transport=self.transport, timeout=90,
                                 verify=ssl.create_default_context(), follow_redirects=False)

    def token(self, expected_account=None):
        current = self.status()
        if (not current["connected"] or current["active"] != self.fingerprint(self.ai) or
                expected_account and current["active"] != expected_account):
            raise ValueError("The Bedrock key or connection changed. Check Settings and retry.")
        return self.ai["api_key"]

    @staticmethod
    def prepare(payload):
        result = copy.deepcopy(payload)
        if "tools" in result:
            tools = []
            for tool in result["tools"]:
                tools.extend(tool["tools"] if tool.get("type") == "namespace" else [tool])
            result["tools"] = tools
        if isinstance(result.get("input"), list):
            for item in result["input"]:
                if item.get("type") == "function_call":
                    item.pop("namespace", None)
        return result

    @staticmethod
    def check_status(response):
        if response.status_code == 200:
            return
        if response.status_code in {401, 403}:
            raise ValueError("Bedrock GPT access denied. Check the Bedrock token, model access and region.")
        if response.status_code in {400, 404}:
            raise ValueError("Bedrock GPT rejected this profile or request. Check the exact model ID and region; try the configured GPT-6.1 Sol profile if GPT-6.2 Sol is unavailable.")
        raise ValueError("Bedrock GPT is unavailable. Check service status and retry.")

    async def response_events(self, payload, expected_account=None):
        token = self.token(expected_account)
        async with self.client() as client:
            async with client.stream("POST", self.url, json=self.prepare(payload),
                                     headers={"Authorization": "Bearer " + token}) as response:
                self.check_status(response)
                data, size, completed = [], 0, False
                async for line in response.aiter_lines():
                    self.token(expected_account)
                    size += len(line)
                    if size > 4_000_000:
                        raise ValueError("Bedrock GPT response exceeded the local limit.")
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        raw = "\n".join(data)
                        data = []
                        if raw == "[DONE]":
                            continue
                        event = json.loads(raw)
                        from app.output_continuation import normalize_event
                        event = normalize_event(event)
                        kind = event.get("type")
                        if kind in {"error", "response.failed", "response.incomplete"}:
                            raise ValueError("Bedrock GPT did not complete this answer. Check model access and service status.")
                        if kind == "response.completed":
                            completed = True
                        yield event
                if not completed:
                    raise ValueError("Bedrock GPT stream stopped before completion; this answer was not saved.")

    async def create(self, model, max_tokens, messages, **kwargs):
        # Connection tests use the same metering wrapper as existing API providers.
        payload = {"model": model, "input": messages, "stream": False,
                   "store": False, "max_output_tokens": max(256, max_tokens)}
        token = self.token()
        async with self.client() as client:
            async with client.stream("POST", self.url, json=payload,
                                     headers={"Authorization": "Bearer " + token}) as response:
                self.check_status(response)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 4_000_000:
                        raise ValueError("Bedrock GPT response exceeded the local limit.")
                self.token()
                result = json.loads(content)
        if result.get("status") != "completed":
            raise ValueError("Bedrock GPT did not complete the connection test.")
        text = "".join(part.get("text", "") for item in result.get("output", [])
                       if item.get("type") == "message" for part in item.get("content", [])
                       if part.get("type") == "output_text")
        if not text:
            raise ValueError("Bedrock GPT returned no text. Check the profile and output limit.")
        return SimpleNamespace(model=result.get("model") or model,
                               usage=result.get("usage"),
                               content=[SimpleNamespace(type="text", text=text)])

    async def close(self):
        pass
