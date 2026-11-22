import asyncio
import hmac
import json
import os
import getpass
import re
import secrets
import time
import httpx
import logging
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent import ai_client, ai_error, public_action, run_turn
from app.connectors import Services, plan_fingerprint, scrub, valid_base
from app.store import Store
from app.validation import validate_config
from app.connection_checks import SERVICES, check_connection
from app.model_routing import MODES


class OAuthLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access log otherwise includes the authorization code and state.
        return "/auth/callback" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(OAuthLogFilter())

def create_app(store=None, services_factory=Services, client_factory=ai_client, demo=None, chatgpt_transport=None):
    public_url = os.environ.get("APP_PUBLIC_URL", "").strip().rstrip("/")
    if public_url:
        parsed_public = urlsplit(public_url)
        if (parsed_public.scheme != "https" or not parsed_public.hostname or
                parsed_public.username or parsed_public.password or parsed_public.path or
                parsed_public.query or parsed_public.fragment):
            raise ValueError("APP_PUBLIC_URL must be an HTTPS origin, e.g. https://aimate.example.com")
        if len(os.environ.get("APP_PASSWORD", "")) < 12:
            raise ValueError("Hosted mode requires APP_PASSWORD with at least 12 characters")
    demo = os.environ.get("AIMATE_DEMO", "").lower() in {"1", "true"} if demo is None else demo
    store = store or Store(os.environ.get("AIMATE_DEMO_DATA_DIR", ".demo-data") if demo else None)
    backend = None
    if demo:
        from app.demo import DemoBackend, demo_config
        backend = DemoBackend()
        store.save_config(demo_config())
        services_factory = backend.services
    app = FastAPI(title="AiMate", docs_url=None, redoc_url=None)
    allowed_hosts = ["127.0.0.1", "localhost", "[::1]", "testserver"]
    if public_url:
        allowed_hosts.append(parsed_public.hostname)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.state.store = store
    app.state.demo_backend = backend
    from app.chatgpt import ChatGPT
    chatgpt = ChatGPT(store, transport=chatgpt_transport)
    app.state.chatgpt = chatgpt
    sessions, attempts, chat_limits, chat_locks = {}, {}, {}, {}
    config_lock = asyncio.Lock()
    # A process dying during a write leaves its outcome uncertain; never auto-replay it.
    store.execute("UPDATE actions SET status='unknown' WHERE status='executing'")
    static = Path(__file__).parent / "static"

    @app.middleware("http")
    async def browser_boundary(request, call_next):
        oauth_callback = (request.method == "GET" and request.url.path == "/auth/callback"
                          and not public_url and not demo and request.url.hostname == "127.0.0.1")
        # A redirect chain keeps Sec-Fetch-Site: cross-site on the final document.
        # The public entry HTML is safe to navigate to; authenticated APIs remain
        # protected by the origin boundary, session and CSRF checks.
        entry_navigation = (request.method == "GET" and request.url.path == "/"
                            and request.headers.get("sec-fetch-mode") == "navigate"
                            and request.headers.get("sec-fetch-dest") == "document")
        origin = request.headers.get("origin")
        if origin and not oauth_callback:
            host = request.headers.get("host", "")
            if origin != (public_url or "http://" + host):
                return Response("Cross-origin requests are refused", status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site" and not (oauth_callback or entry_navigation):
            return Response("Cross-site requests are refused", status_code=403)
        if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 250_000:
            return Response("Request too large", status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        response.headers["Cache-Control"] = "no-store"
        return response

    def auth(request: Request):
        token = request.cookies.get("project_session", "")
        session = sessions.get(token)
        if not session or time.time() - session["created"] > 12 * 3600:
            sessions.pop(token, None)
            raise HTTPException(401, "Sign in first")
        if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
                request.headers.get("x-csrf-token", "").encode(), session["csrf"].encode()):
            raise HTTPException(403, "Refresh the page and retry (CSRF token)")
        return session

    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        return Response(json.dumps({"detail": str(exc)}), status_code=400, media_type="application/json")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/api/mode")
    def mode():
        return {"demo": bool(demo), "hosted": bool(public_url)}

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    def issue_session(response):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[token] = {"csrf": csrf, "created": time.time(), "token": token}
        response.set_cookie("project_session", token, httponly=True, secure=bool(public_url),
                            samesite="strict", max_age=12 * 3600, path="/")
        return {"csrf": csrf}

    @app.post("/api/demo/login")
    def demo_login(response: Response):
        if not demo:
            raise HTTPException(404, "Demo mode is disabled")
        return issue_session(response)

    @app.post("/api/login")
    async def login(request: Request, response: Response):
        ip = request.client.host if request.client else "local"
        now = time.time()
        recent = [t for t in attempts.get(ip, []) if now - t < 60]
        if len(recent) >= 8:
            raise HTTPException(429, "Too many attempts; wait one minute")
        attempts[ip] = recent + [now]
        body = await request.json()
        password = body.get("password", "") if isinstance(body, dict) else ""
        if not isinstance(password, str) or not hmac.compare_digest(password.encode(), store.password.encode()):
            raise HTTPException(401, "Incorrect local app password")
        return issue_session(response)

    @app.post("/api/logout")
    def logout(response: Response, session=Depends(auth)):
        sessions.pop(session["token"], None)
        response.delete_cookie("project_session")
        return {"ok": True}

    @app.get("/api/state")
    def state(session=Depends(auth)):
        return {"csrf": session["csrf"], "config": store.public_config(), "demo": bool(demo),
                "connection_checks": store.connection_checks(),
                "connection_defaults": {"jenkins": {"username": getpass.getuser() if not public_url and not demo else "",
                                                      "url": os.environ.get("JENKINS_URL", "")}},
                "chatgpt": {**chatgpt.status(), "available": not demo and not public_url},
                "conversations": store.rows("SELECT * FROM conversations ORDER BY created DESC")}

    def require_local_chatgpt():
        if demo or public_url:
            raise HTTPException(409, "ChatGPT sign-in is supported in local live mode. Hosted apps need a separate OpenAI registration.")

    @app.post("/api/chatgpt/start")
    async def start_chatgpt(request: Request, session=Depends(auth)):
        require_local_chatgpt()
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a ChatGPT account selection")
        origin = str(request.base_url).rstrip("/")
        return {"url": chatgpt.start(origin, session["token"], body.get("account"))}

    @app.get("/auth/callback")
    async def chatgpt_callback(request: Request):
        require_local_chatgpt()
        try:
            params = dict(request.query_params)
            if any(len(request.query_params.getlist(key)) != 1 for key in params):
                raise ValueError("Duplicate callback parameters")
            await chatgpt.callback(params,
                lambda token: token in sessions and time.time() - sessions[token]["created"] < 12 * 3600,
                str(request.base_url).rstrip("/"))
            store.execute("DELETE FROM connection_checks WHERE service='ai'")
        except (ValueError, httpx.HTTPError) as exc:
            # OAuth codes/tokens never appear in redirects or diagnostics.
            return RedirectResponse("/?chatgpt=failed", status_code=303)
        return RedirectResponse("/?chatgpt=connected", status_code=303)

    @app.get("/api/chatgpt/models")
    async def chatgpt_models(session=Depends(auth)):
        require_local_chatgpt()
        return {"models": await chatgpt.models()}

    @app.post("/api/chatgpt/disconnect")
    async def disconnect_chatgpt(session=Depends(auth)):
        require_local_chatgpt()
        store.execute("DELETE FROM connection_checks WHERE service='ai'")
        return await chatgpt.disconnect()

    @app.put("/api/settings")
    async def settings(request: Request, session=Depends(auth)):
        if demo:
            raise HTTPException(409, "Demo uses fixed fictional connections. Restart without AIMATE_DEMO for real connections.")
        async with config_lock:
            old = store.config()
            config = validate_config(await request.json(), old)
            if config.get("ai", {}).get("provider") == "chatgpt":
                require_local_chatgpt()
            if config != {k: v for k, v in old.items() if k != "_version"}:
                store.save_config(config)
        return {"config": store.public_config()}

    @app.put("/api/settings/{service}")
    async def section_settings(service: str, request: Request, session=Depends(auth)):
        if demo:
            raise HTTPException(409, "Demo connections cannot be changed.")
        if service not in SERVICES | {"changes"}:
            raise HTTPException(404, "Unknown connection")
        async with config_lock:
            old = store.config()
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Connection settings must be an object")
            merged = {**old, **({"allow_writes": body.get("allow_writes")} if service == "changes" else {service: {**old.get(service, {}), **body} if service in {"ai", "github", "jenkins"} else body})}
            config = validate_config(merged, old)
            if service == "ai" and config["ai"].get("provider") == "chatgpt":
                require_local_chatgpt()
            if config != {k: v for k, v in old.items() if k != "_version"}:
                store.save_config(config)
        return {"config": store.public_config()}

    @app.post("/api/connections/{service}/test")
    async def connection_test(service: str, session=Depends(auth)):
        if service not in SERVICES:
            raise HTTPException(404, "Unknown connection")
        if demo:
            if service not in {"ai", "github", "jira", "jenkins"}:
                raise HTTPException(404, "Unknown demo connection")
            return {"ok": True, "status": "simulated", "message": "Offline simulation only; no real connection was tested", "simulated": True}
        cfg = store.config()
        if service == "ai" and cfg.get("ai", {}).get("provider") == "chatgpt":
            require_local_chatgpt()
        report = scrub(await check_connection(service, cfg, services_factory(cfg), client_factory, chatgpt), cfg)
        store.save_connection_check(service, cfg, report)
        return report

    @app.post("/api/conversations")
    def create_conversation(session=Depends(auth)):
        return {"id": store.new_conversation()}

    @app.get("/api/conversations/{cid}")
    def conversation(cid: str, session=Depends(auth)):
        store.require_conversation(cid)
        turns = store.rows("SELECT t.id,t.messages,t.created,u.metadata FROM turns t LEFT JOIN turn_usage u ON u.turn=t.id WHERE conversation=? ORDER BY t.id", (cid,))
        return {"id": cid, "turns": [{"id": t["id"], "messages": json.loads(t["messages"]), "created": t["created"],
                                    "usage": json.loads(t["metadata"]) if t["metadata"] else None} for t in turns],
                "actions": [public_action(store.action(r["id"])) for r in store.rows("SELECT id FROM actions WHERE conversation=? ORDER BY created", (cid,))]}

    @app.post("/api/conversations/{cid}/edit")
    async def edit_message(cid: str, request: Request, session=Depends(auth)):
        store.require_conversation(cid)
        if chat_locks.get(cid) and chat_locks[cid].locked():
            raise HTTPException(409, "Wait until the current answer finishes before editing")
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected an edited message")
        turn_id, question = body.get("turn_id"), body.get("question")
        if isinstance(turn_id, bool) or not isinstance(turn_id, int) or turn_id < 1:
            raise ValueError("Choose a saved message to edit")
        if not isinstance(question, str) or not question.strip() or len(question) > 30_000:
            raise ValueError("Question must have 1–30,000 characters")
        selected = store.rows("SELECT id FROM turns WHERE conversation=? AND id=?", (cid, turn_id))
        if not selected:
            raise HTTPException(404, "Message not found in this conversation")
        # Preserve the original conversation and its reviewed actions as a separate version.
        edited = store.new_conversation(question.strip())
        for turn in store.rows("SELECT t.messages,u.metadata FROM turns t LEFT JOIN turn_usage u ON u.turn=t.id WHERE conversation=? AND t.id<? ORDER BY t.id", (cid, turn_id)):
            store.save_turn(edited, json.loads(turn["messages"]), json.loads(turn["metadata"]) if turn["metadata"] else None)
        return {"id": edited}

    @app.post("/api/chat")
    async def chat(request: Request, session=Depends(auth)):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a question object")
        cid, question = body.get("conversation"), body.get("question")
        store.require_conversation(cid)
        if not isinstance(question, str) or not question.strip() or len(question) > 30_000:
            raise ValueError("Question must have 1–30,000 characters")
        now = time.time()
        model_mode = body.get("model_mode", "auto")
        if not isinstance(model_mode, str) or model_mode not in MODES:
            raise ValueError("Choose Auto, Standard or Analysis")
        recent = [t for t in chat_limits.get(session["token"], []) if now - t < 60]
        if len(recent) >= 10:
            raise HTTPException(429, "At most 10 questions per minute")
        chat_limits[session["token"]] = recent + [now]
        lock = chat_locks.setdefault(cid, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "This conversation is already answering")
        await lock.acquire()

        async def events():
            try:
                if demo:
                    from app.demo import run_demo_turn
                    turn = run_demo_turn(store, cid, question, backend=backend)
                else:
                    if store.config().get("ai", {}).get("provider") == "chatgpt":
                        require_local_chatgpt()
                    turn = run_turn(store, cid, question, client_factory=client_factory,
                                    services_factory=services_factory, chatgpt=chatgpt, model_mode=model_mode)
                async for event in turn:
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                message = ai_error(exc)
                yield "data: " + json.dumps({"event": "error", "message": scrub(message, store.config())}) + "\n\n"
            finally:
                lock.release()
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/actions/{aid}/{decision}")
    async def decide(aid: str, decision: str, session=Depends(auth)):
        if decision not in {"confirm", "cancel"}:
            raise ValueError("Choose confirm or cancel")
        async with config_lock:
            action = store.action(aid)
            if action["status"] != "pending":
                raise HTTPException(409, "Proposal has already been handled; do not replay it")
            if decision == "cancel":
                store.execute("UPDATE actions SET status='cancelled' WHERE id=? AND status='pending'", (aid,))
                return public_action(store.action(aid))
            if time.time() - action["created"] > 1800:
                store.execute("UPDATE actions SET status='expired' WHERE id=?", (aid,))
                raise HTTPException(409, "Proposal expired; ask for a new one")
            config = store.config()
            if not config.get("allow_writes") or config.get("_version") != action["config_version"]:
                raise HTTPException(409, "Settings changed; review a new proposal")
            services = services_factory(config)
            original = services.plan(action["service"], action["operation"], action["payload"])
            # Recheck default branch and file SHA immediately before execution.
            plan = await services.prepare(action["service"], action["operation"], action["payload"])
            if plan_fingerprint({k: v for k, v in plan.items() if k != "preview"}) != plan_fingerprint(original):
                raise HTTPException(409, "Proposal changed; ask for a new one")
            claimed = store.execute("UPDATE actions SET status='executing' WHERE id=? AND status='pending'", (aid,))
            if claimed.rowcount != 1:
                raise HTTPException(409, "Proposal already claimed")
            store.execute("INSERT INTO audit (action,status,created) VALUES (?,'confirmed',?)", (aid, time.time()))
            try:
                result = await services.execute(plan)
                status = "completed"
            except BaseException as exc:
                # HTTP/transport failure may occur after a remote write; be conservative.
                result = {"message": str(exc) if isinstance(exc, ValueError) else "Write outcome uncertain. Inspect the target system before trying again."}
                status = "unknown"
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
            finally:
                if "status" in locals():
                    result = scrub(result, config)
                    store.execute("UPDATE actions SET status=?,result=? WHERE id=?", (status, json.dumps(result), aid))
                    store.execute("INSERT INTO audit (action,status,result,created) VALUES (?,?,?,?)",
                                  (aid, status, json.dumps(result), time.time()))
            return public_action(store.action(aid))

    @app.get("/api/audit")
    def audit(session=Depends(auth)):
        return {"entries": store.rows("SELECT * FROM audit ORDER BY id DESC LIMIT 100")}

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


app = create_app()
