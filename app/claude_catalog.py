"""Credential-scoped in-memory discovery; catalog presence is not invocation proof."""
import asyncio
import copy
import hashlib
import json
import os
import re
import time

from app.bedrock_models import discover_models, presets


def enabled():
    return os.environ.get("AIMATE_MANUAL_MODELS_ENABLED", "1") != "0"


def model_id(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"(?:(?:us|global|eu|apac|au)\.)?anthropic\.claude[a-zA-Z0-9._:-]{1,180}", value):
        raise ValueError("Choose a Claude model/profile from the model list.")
    return value


def scope(ai):
    fields = ["provider", "region", "bedrock_endpoint", "bedrock_auth",
              "api_key", "aws_access_key", "aws_secret_key", "aws_session_token"]
    values = {name: ai.get(name) for name in fields}
    if ai.get("bedrock_auth") == "iam":
        values["environment"] = {name: os.environ.get(name) for name in
                                 ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


class Catalog:
    def __init__(self, fetch=None, clock=time.monotonic):
        self.fetch = fetch or discover_models
        self.clock, self.entries, self.lock = clock, {}, asyncio.Lock()

    async def get(self, ai, force=False):
        base = {"models": [], "message": "Organization presets. Listing does not verify invocation access.",
                "presets": presets(ai.get("bedrock_endpoint", "runtime")), "manual_enabled": enabled()}
        ready = ai.get("provider") == "bedrock" and (
            bool(ai.get("api_key")) or ai.get("bedrock_auth") == "iam")
        if not ready or (os.environ.get("AIMATE_CLAUDE_CATALOG_ENABLED", "1") == "0" and not force):
            return base
        key = scope(ai)
        async with self.lock:
            entry = self.entries.get(key)
            if not force and entry and self.clock() - entry[0] < 300:
                return copy.deepcopy(entry[1])
            try:
                result = {**base, **await self.fetch(ai)}
            except Exception:
                result = {**base, "message": "Claude catalog unavailable. Use presets, check the saved connection/region and refresh models."}
            if key not in self.entries and len(self.entries) >= 8:
                self.entries.pop(next(iter(self.entries)))
            self.entries[key] = (self.clock(), copy.deepcopy(result))
            return result

    def choose(self, ai, value):
        if not enabled():
            raise ValueError("Direct model selection is disabled.")
        if ai.get("provider") != "bedrock":
            raise ValueError("Direct Claude selection requires the active Bedrock connection.")
        value = model_id(value)
        known = {row["id"] for row in presets(ai.get("bedrock_endpoint", "runtime"))}
        known.update(v for v in (ai.get("model"), ai.get("analysis_model")) if v)
        entry = self.entries.get(scope(ai))
        if entry:
            known.update(row["id"] for row in entry[1].get("models", []))
        if value not in known:
            raise ValueError("Refresh the Claude catalog, then choose this model again.")
        return value
