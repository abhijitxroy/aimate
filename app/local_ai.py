"""Explicit, local-only fallback. Saved cloud credentials/settings stay intact."""
import ipaddress
from fastapi import Depends, Request
import httpx
from app.ollama_local import DEFAULT_MODEL, enabled, installed, model_name


def allowed(request,live_local):
    try:loopback=ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError,AttributeError):loopback=False
    return bool(enabled() and live_local and loopback and request.url.hostname in {"localhost","127.0.0.1","::1"})


def selection(body,request,live_local):
    value=body.get("local_ai",False)
    if type(value) is not bool:raise ValueError("Local AI choice must be true or false.")
    if not value:return None
    if not allowed(request,live_local):
        raise ValueError("Local AI is available only on this laptop's local development workspace.")
    return model_name(body.get("local_model",DEFAULT_MODEL))


class LocalStore:
    def __init__(self,store,model):self.store,self.model=store,model
    def __getattr__(self,name):return getattr(self.store,name)
    def source_config(self):return self.store.config()
    def config(self):
        cfg=self.source_config()
        return {**cfg,"_local_ai":True,"ai":{**cfg.get("ai",{}),"provider":"ollama",
            "model":self.model,"analysis_model":""}}
    def history(self,cid):
        from app.memory import readable_text
        text=readable_text(self.store.history(cid)).encode("utf-8")[-3000:].decode("utf-8",errors="ignore")
        return [{"role":"user","content":"Previous saved conversation excerpt; reference only, may be stale. Use saved-record tools for full details:\n"+text}] if text else []


def can_offer(exc,request,live_local):
    return allowed(request,live_local) and (
        isinstance(exc,httpx.HTTPError) or getattr(exc,"status_code",None) in {401,403,429,500,502,503,504})


def register(app,auth,live_local):
    @app.get("/api/local-ai/status")
    async def status(request:Request,session=Depends(auth)):
        if not allowed(request,live_local):
            return {"available":False,"models":[],"message":"Local AI is unavailable in this deployment."}
        try:
            async with httpx.AsyncClient(trust_env=False,follow_redirects=False) as client:
                models=await installed(client)
            return {"available":True,"models":models,"default":DEFAULT_MODEL,
                "message":"Ollama reachable. Choose an installed model; a local question verifies inference.",
                "notice":"Local inference uses no cloud AI credentials. Service reads still need network/VPN; saved context may be stale."}
        except ValueError as exc:
            return {"available":False,"models":[],"message":str(exc)}
