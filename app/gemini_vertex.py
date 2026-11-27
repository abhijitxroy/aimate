"""Optional Vertex AI adapter. Fixed Google endpoints; no CLI or local execution."""
from contextlib import asynccontextmanager
import asyncio
import json
import os
import re
import secrets
import ssl
import time

import httpx
import jwt
from anthropic.types import Message
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

TOKEN_URL = "https://oauth2.googleapis.com/token"
MODELS = [
    ("gemini-4-hydrogen", "Gemini 4 Hydrogen"),
    ("gemini-4-carbon", "Gemini 4 Carbon"),
    ("gemini-4-neon", "Gemini 4 Neon"),
    ("gemini-4-argon", "Gemini 4 Argon"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash"),
    ("gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview"),
]


def enabled():
    return os.environ.get("AIMATE_GEMINI_ENABLED") != "0"


def credentials(text):
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("type") != "service_account":
            raise ValueError()
        project = data["project_id"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", project):
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9._-]+@" + re.escape(project) + r"\.iam\.gserviceaccount\.com", data["client_email"]):
            raise ValueError()
        if data.get("token_uri") != TOKEN_URL or data.get("universe_domain", "googleapis.com") != "googleapis.com":
            raise ValueError()
        key = load_pem_private_key(data["private_key"].encode(), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("Use a complete Google service-account JSON with a valid RSA private key and Google token endpoint.") from None


def validate(ai):
    if not enabled():
        raise ValueError("Gemini is disabled on this server.")
    ai["gcp_location"] = ai.get("gcp_location") or "global"
    if not re.fullmatch(r"global|[a-z]+-[a-z]+\d+", ai["gcp_location"]):
        raise ValueError("Use global or a Google Cloud location such as us-central1.")
    ai["model"] = ai.get("model") or MODELS[0][0]
    for model in (ai["model"], ai.get("analysis_model", "")):
        if model and not re.fullmatch(r"gemini-[a-z0-9][a-z0-9.-]{0,99}", model):
            raise ValueError("Use an exact Gemini model ID, not a URL.")
    if ai.get("gcp_credentials"):
        data = credentials(ai["gcp_credentials"])
        ai["gcp_project"] = ai.get("gcp_project") or data["project_id"]
    if ai.get("gcp_project") and not re.fullmatch(r"[a-z][a-z0-9-]{4,61}[a-z0-9]", ai["gcp_project"]):
        raise ValueError("Use a valid Google Cloud project ID.")


class VertexError(Exception):
    def __init__(self, status, authentication=False):
        super().__init__("Vertex AI request failed.")
        self.status_code = status
        self.public_message = (
            "Google Cloud credentials are expired, revoked or invalid. Generate replacement credentials and update Gemini settings."
            if authentication else {
                400: "Gemini rejected the request. Check the model and saved tool context; try Continue in new chat.",
                401: "Google Cloud authentication expired. Update the service-account JSON.",
                403: "Gemini access denied. Check Vertex AI permissions, project, location and allowed model.",
                404: "Gemini model was not found. Check its exact ID, project and location.",
                429: "Google Cloud quota or rate limit reached. Wait before retrying.",
            }.get(status, "Cannot reach Gemini. Check Google Cloud access, VPN/proxy and network."))


def contents(messages, model, context=None):
    output = []
    calls = {}
    for row in messages:
        blocks = row["content"] if isinstance(row["content"], list) else [{"type": "text", "text": row["content"]}]
        saved = next((b for b in blocks if b.get("vertex_model") == model and b.get("vertex_parts")
                      and (context is None or b.get("vertex_context") == context)), None)
        for block in blocks:
            if block.get("type") == "tool_use":
                calls[block["id"]] = (block["name"], block.get("vertex_call_id"), bool(saved))
        if saved:
            parts = saved["vertex_parts"]
        else:
            parts = []
            for block in blocks:
                kind = block.get("type")
                if kind == "text":
                    parts.append({"text": block.get("text", "")})
                elif kind == "image":
                    source = block["source"]
                    parts.append({"inlineData": {"mimeType": source["media_type"], "data": source["data"]}})
                elif kind == "tool_use":
                    parts.append({"text": "Previous tool call: " + block["name"] + " " + json.dumps(block["input"])})
                elif kind == "tool_result":
                    name, call_id, signed = calls.get(block["tool_use_id"], ("unknown", None, False))
                    if signed:
                        response = {"name": name, "response": {"result": block.get("content", "")}}
                        if call_id:
                            response["id"] = call_id
                        parts.append({"functionResponse": response})
                    else:
                        parts.append({"text": "Previous tool result: " + block.get("content", "")})
        if not parts:
            continue
        role = "model" if row["role"] == "assistant" else "user"
        if output and output[-1]["role"] == role:
            output[-1]["parts"].extend(parts)
        else:
            output.append({"role": role, "parts": parts})
    return output


def payload(params, context=None):
    result = {"contents": contents(params["messages"], params["model"], context),
              "generationConfig": {"maxOutputTokens": max(256, params.get("max_tokens", 4096))}}
    if params.get("system"):
        result["systemInstruction"] = {"parts": [{"text": params["system"]}]}
    if params.get("tools"):
        result["tools"] = [{"functionDeclarations": [
            {"name": t["name"], "description": t.get("description", ""), "parametersJsonSchema": t["input_schema"]}
            for t in params["tools"]]}]
        result["toolConfig"] = {"functionCallingConfig": {
            "mode": "NONE" if params.get("tool_choice", {}).get("type") == "none" else "AUTO"}}
    return result


def message(model, parts, usage, reason, context=None):
    if reason not in {"STOP", "MAX_TOKENS"}:
        raise ValueError("Gemini returned no usable answer or blocked the request. Try a narrower question.")
    blocks = []
    for part in parts:
        if part.get("thought"):
            continue
        if "text" in part:
            blocks.append({"type": "text", "text": part["text"]})
        if "functionCall" in part:
            call = part["functionCall"]
            if not isinstance(call.get("args", {}), dict) or not isinstance(call.get("name"), str):
                raise ValueError("Gemini returned invalid function arguments.")
            blocks.append({"type": "tool_use", "name": call["name"], "input": call.get("args", {}),
                           "id": call.get("id") or secrets.token_hex(12), "vertex_call_id": call.get("id")})
    if not blocks and reason == "MAX_TOKENS":
        blocks = [{"type": "text", "text": ""}]
    if not blocks:
        raise ValueError("Gemini returned no answer. Retry with a narrower question.")
    # Opaque provider parts/signatures stay with their own model, never cross-provider.
    blocks[0].update(vertex_model=model, vertex_parts=parts, vertex_context=context)
    incoming = {"input_tokens": 0, "output_tokens": 0}
    if usage is not None:
        prompt, cached = usage.get("promptTokenCount", 0), usage.get("cachedContentTokenCount", 0)
        output, thoughts = usage.get("candidatesTokenCount", 0), usage.get("thoughtsTokenCount", 0)
        if any(type(n) is not int or n < 0 for n in (prompt, cached, output, thoughts)) or cached > prompt:
            raise ValueError("Gemini returned invalid usage counts.")
        incoming = {"input_tokens": prompt - cached, "output_tokens": output + thoughts, "cache_read_input_tokens": cached}
    try:
        result = Message.model_validate({"id": "gemini-reply", "type": "message", "role": "assistant", "model": model,
            "content": blocks, "stop_reason": "max_tokens" if reason == "MAX_TOKENS" else
                "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn",
            "stop_sequence": None, "usage": incoming})
    except (ValueError, TypeError):
        raise ValueError("Gemini returned an invalid answer format.") from None
    if usage is None:
        result.usage = None
    return result


class Client:
    def __init__(self, config, transport=None):
        self.ai = dict(config["ai"])
        validate(self.ai)
        if not self.ai.get("gcp_credentials"):
            raise ValueError("Add the Google service-account JSON in Gemini settings.")
        self.credentials = credentials(self.ai["gcp_credentials"])
        self.http = httpx.AsyncClient(transport=transport, timeout=90, follow_redirects=False,
                                     verify=ssl.create_default_context())
        self.messages = self
        self.token = ""
        self.expires = 0
        self.lock = asyncio.Lock()

    async def access_token(self):
        if not enabled():
            raise ValueError("Gemini is disabled on this server.")
        async with self.lock:
            if self.token and self.expires > time.time() + 60:
                return self.token
            now = int(time.time())
            assertion = jwt.encode({"iss": self.credentials["client_email"],
                "scope": "https://www.googleapis.com/auth/cloud-platform", "aud": TOKEN_URL,
                "iat": now, "exp": now + 3600}, self.credentials["private_key"], algorithm="RS256",
                headers={"kid": self.credentials.get("private_key_id", "")})
            try:
                response = await self.http.post(TOKEN_URL, data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
            except httpx.HTTPError:
                raise VertexError(0) from None
            if response.status_code != 200:
                raise VertexError(response.status_code, authentication=True)
            try:
                data = response.json()
                token, ttl = data["access_token"], data["expires_in"]
                if not isinstance(token, str) or not token or type(ttl) is not int or ttl <= 0:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise ValueError("Google Cloud returned an invalid authentication response.") from None
            self.token, self.expires = token, time.time() + min(ttl, 3600)
            return self.token

    def url(self, model, streaming=False):
        selected = {**self.ai, "model": model, "gcp_credentials": ""}
        validate(selected)
        location = self.ai["gcp_location"]
        host = "aiplatform.googleapis.com" if location == "global" else location + "-aiplatform.googleapis.com"
        project = self.ai.get("gcp_project") or self.credentials["project_id"]
        return f"https://{host}/v1/projects/{project}/locations/{location}/publishers/google/models/{model}:" + (
            "streamGenerateContent?alt=sse" if streaming else "generateContent")

    def context(self, model):
        return "/".join((self.ai.get("gcp_project") or self.credentials["project_id"], self.ai["gcp_location"], model))

    async def create(self, **params):
        token = await self.access_token()
        try:
            response = await self.http.post(self.url(params["model"]), headers={
                "Authorization": "Bearer " + token}, json=payload(params, self.context(params["model"])))
        except httpx.HTTPError:
            raise VertexError(0) from None
        if response.status_code != 200:
            raise VertexError(response.status_code)
        try:
            data = response.json()
            candidate = data.get("candidates", [])[0]
            return message(params["model"], candidate["content"]["parts"], data.get("usageMetadata"), candidate.get("finishReason"), self.context(params["model"]))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ValueError("Gemini returned an incomplete response.") from None

    @asynccontextmanager
    async def stream(self, **params):
        token = await self.access_token()
        try:
            async with self.http.stream("POST", self.url(params["model"], True), headers={
                    "Authorization": "Bearer " + token}, json=payload(params, self.context(params["model"]))) as response:
                if response.status_code != 200:
                    raise VertexError(response.status_code)
                yield Stream(response, params["model"], self.context(params["model"]))
        except httpx.HTTPError:
            raise VertexError(0) from None

    async def close(self):
        self.token = ""
        await self.http.aclose()


class Stream:
    def __init__(self, response, model, context=None):
        self.response, self.model = response, model
        self.parts, self.usage, self.reason = [], None, None
        self.complete = False
        self.context = context

    @property
    def text_stream(self):
        return self.read()

    async def read(self):
        size = 0
        async for line in self.response.aiter_lines():
            size += len(line)
            if size > 2_000_000:
                raise ValueError("Gemini response exceeded the supported stream limit.")
            if not line.startswith("data:"):
                continue
            try:
                data = json.loads(line[5:].strip())
                if "error" in data:
                    raise VertexError(data["error"].get("code", 500))
                if data.get("usageMetadata") is not None:
                    self.usage = data["usageMetadata"]
                for candidate in data.get("candidates", [])[:1]:
                    self.reason = candidate.get("finishReason") or self.reason
                    for part in candidate.get("content", {}).get("parts", []):
                        self.parts.append(part)
                        if "text" in part and not part.get("thought"):
                            yield part["text"]
            except (json.JSONDecodeError, TypeError, AttributeError):
                raise ValueError("Gemini returned invalid streaming data.") from None
        self.complete = bool(self.reason)

    async def get_final_message(self):
        if not self.complete:
            raise ValueError("Gemini stream ended before completion. Retry; partial output was not saved.")
        return message(self.model, self.parts, self.usage, self.reason, self.context)


def register(app, auth):
    from fastapi import Depends

    @app.get("/api/gemini/models")
    def catalog(session=Depends(auth)):
        return {"enabled": enabled(), "models": [{"id": ident, "title": title} for ident, title in MODELS] if enabled() else [],
                "message": "Tokengen presets verified 25 November 2026. Save & test verifies your selected model's live access."}
