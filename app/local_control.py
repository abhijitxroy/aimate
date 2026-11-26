"""Optional, session-owned local cancellation and explicit Ollama memory release."""
import asyncio
import os
import re
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, HTTPException, Request

from app.ollama_local import Client, URL, model_name


class Controls:
    def __init__(self):
        self.runs = {}
        self.unloading = set()

    def reserve(self, token, conversation, model, ident=None):
        ident = ident or secrets.token_hex(16)
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9-]{16,80}", ident):
            raise ValueError("Invalid local request ID.")
        if model in self.unloading:
            raise HTTPException(409, "This local model is unloading. Retry when it finishes.")
        key = (token, conversation, ident)
        if key in self.runs:
            raise HTTPException(409, "This local request is already running.")
        entry = {"model": model, "task": None, "cancel": False, "done": asyncio.Event()}
        self.runs[key] = entry
        return key, entry

    @asynccontextmanager
    async def running(self, handle):
        try:
            self.begin(handle)
            yield
        finally:
            self.finish(handle)

    def begin(self, handle):
        _, entry = handle
        entry["task"] = asyncio.current_task()
        if entry["cancel"]:
            raise asyncio.CancelledError

    def finish(self, handle):
        key, entry = handle
        self.runs.pop(key, None)
        entry["done"].set()

    async def stop(self, token, conversation, ident):
        entry = self.runs.get((token, conversation, ident))
        if entry:
            if not entry["cancel"] and entry["task"]:
                entry["task"].cancel()
            entry["cancel"] = True
            if entry["task"]:
                try:
                    await asyncio.wait_for(entry["done"].wait(), 5)
                except TimeoutError:
                    raise HTTPException(409, "Local cancellation is still finishing. Retry unload shortly.") from None

    async def unload(self, model):
        model = model_name(model)
        if model in self.unloading or any(row["model"] == model for row in self.runs.values()):
            raise HTTPException(409, "Another local chat is using this model. Stop it before unloading.")
        self.unloading.add(model)
        client = Client({"ai": {"model": model}})
        try:
            await client.verify(model)
            response = await client.http.post(URL + "/api/generate",
                json={"model": model, "keep_alive": 0}, timeout=10)
            response.raise_for_status()
            state = await client.http.get(URL + "/api/ps", timeout=3)
            state.raise_for_status()
            models = state.json().get("models")
            if not isinstance(models, list):
                raise ValueError("Ollama did not confirm its loaded-model state. Check local access.")
            if any(row.get("name") == model or row.get("model") == model
                   for row in models):
                raise HTTPException(409, "Ollama still has the model loaded. Another application may be using it.")
        except httpx.HTTPError:
            raise ValueError("Cannot unload the local model. Check Ollama and retry.") from None
        finally:
            await client.close()
            self.unloading.discard(model)


def register(app, auth, live_local):
    if os.environ.get("AIMATE_LOCAL_CONTROL_ENABLED") == "0":
        return None
    controls = Controls()

    @app.post("/api/local-ai/stop")
    async def stop(request: Request, session=Depends(auth)):
        from app.local_ai import allowed
        if not allowed(request, live_local):
            raise HTTPException(403, "Local controls are available only on this laptop.")
        body = await request.json()
        if not isinstance(body, dict) or type(body.get("unload", False)) is not bool:
            raise ValueError("Invalid local stop request.")
        if body.get("conversation") is not None:
            cid, ident = body["conversation"], body.get("request_id")
            if not isinstance(cid, str) or not isinstance(ident, str):
                raise ValueError("Provide the local conversation and request ID.")
            await controls.stop(session["token"], cid, ident)
        if body.get("unload"):
            await controls.unload(body.get("model"))
        return {"message": "Stopped. Local model unloaded." if body.get("unload") else "Local request stopped."}

    return controls
