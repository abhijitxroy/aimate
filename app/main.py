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
    connection_locks = {service: asyncio.Lock() for service in SERVICES}
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
                "groups": store.rows("SELECT * FROM conversation_groups ORDER BY created"),
                "conversations": store.rows("SELECT c.*,l.group_id,COALESCE(f.pinned,0) AS pinned FROM conversations c LEFT JOIN conversation_locations l ON l.conversation=c.id LEFT JOIN conversation_flags f ON f.conversation=c.id ORDER BY pinned DESC,c.created DESC")}

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

    @app.get("/api/bedrock/models")
    async def bedrock_models(discover: bool = False, session=Depends(auth)):
        from app.bedrock_models import presets, discover_models
        ai = store.config().get("ai", {})
        result = {"models": [], "message": "Organization presets. Refresh models to list the saved account and region. Access is verified only by Save & test."}
        if discover:
            if demo or ai.get("provider") != "bedrock":
                raise HTTPException(409, "Save a live Bedrock connection before refreshing models.")
            result = await discover_models(ai)
        return {**result, "presets": presets(ai.get("bedrock_endpoint", "runtime"))}

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
        async with connection_locks[service]:
            report = scrub(await check_connection(service, cfg, services_factory(cfg), client_factory, chatgpt), cfg)
            if store.connection_fingerprint(cfg, service) == store.connection_fingerprint(store.config(), service):
                store.save_connection_check(service, cfg, report)
            else:
                return {"ok": False, "status": "unchecked", "message": "Settings changed during this check. Checking the current saved connection is required."}
        return report

    @app.post("/api/connections/sync")
    async def sync_connections(session=Depends(auth)):
        # Read-only service checks. Never perform an automatic billable AI test.
        if demo:
            return {"connection_checks": store.connection_checks()}
        async def update(service):
            async with connection_locks[service]:
                cfg = store.config()
                section = cfg.get(service, {})
                if not section.get("url"):
                    return
                if service in {"jira", "jenkins"} and not section.get("token"):
                    return
                if service == "github" and not section.get("repos"):
                    return
                previous = store.connection_checks().get(service, {})
                if previous.get("checked_at") and not previous.get("stale"):
                    return
                report = scrub(await check_connection(service, cfg, services_factory(cfg), client_factory, chatgpt), cfg)
                if store.connection_fingerprint(cfg, service) == store.connection_fingerprint(store.config(), service):
                    store.save_connection_check(service, cfg, report)
        await asyncio.gather(*(update(service) for service in ("github", "jira", "jenkins")))
        return {"connection_checks": store.connection_checks()}

    @app.post("/api/conversations")
    async def create_conversation(request: Request, session=Depends(auth)):
        body = await request.json() if await request.body() else {}
        if not isinstance(body, dict):
            raise ValueError("Expected conversation options.")
        group_id = body.get("group_id")
        async with config_lock:
            if group_id is not None:
                store.require_group(group_id)
            return {"id": store.new_conversation(group_id=group_id)}

    @app.post("/api/groups")
    async def create_group(request: Request, session=Depends(auth)):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected group details.")
        async with config_lock:
            return {"id": store.create_group(body.get("name"), body.get("kind", "group"), body.get("parent"))}

    @app.get("/api/knowledge")
    def knowledge(session=Depends(auth)):
        return {"records": store.rows("SELECT * FROM knowledge ORDER BY updated DESC")}

    @app.get("/api/usage")
    def usage(days: int = 30, offset: int = 0, session=Depends(auth)):
        from app.usage import report
        return report(store, days, offset)

    @app.post("/api/usage/rates")
    async def usage_rate(request: Request, session=Depends(auth)):
        from app.usage import save_rate
        body = await request.json()
        async with config_lock:
            return save_rate(store, body)

    @app.post("/api/knowledge")
    async def add_knowledge(request: Request, session=Depends(auth)):
        from app.memory import save_record
        body = await request.json()
        async with config_lock:
            return save_record(store, body)

    @app.patch("/api/knowledge/{record_id}")
    async def update_knowledge(record_id: str, request: Request, session=Depends(auth)):
        from app.memory import save_record
        body = await request.json()
        async with config_lock:
            return save_record(store, body, record_id)

    @app.delete("/api/knowledge/{record_id}")
    async def delete_knowledge(record_id: str, session=Depends(auth)):
        async with config_lock:
            if not store.rows("SELECT id FROM knowledge WHERE id=?", (record_id,)):
                raise ValueError("Record not found.")
            store.execute("DELETE FROM knowledge WHERE id=?", (record_id,))
            return {"deleted": record_id}

    @app.post("/api/conversations/{cid}/continue")
    async def continue_conversation(cid: str, session=Depends(auth)):
        async with config_lock:
            store.require_conversation(cid)
            title = store.rows("SELECT title FROM conversations WHERE id=?", (cid,))[0]["title"]
            new_id = store.new_conversation("Continue · " + title, store.conversation_group(cid))
            store.execute("INSERT INTO conversation_references VALUES (?,?)", (new_id, cid))
            return {"id": new_id}

    @app.patch("/api/groups/{gid}")
    async def rename_group(gid: str, request: Request, session=Depends(auth)):
        store.require_group(gid)
        body = await request.json()
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError("Use a group name with 1–80 characters.")
        async with config_lock:
            store.require_group(gid)
            parent = store.rows("SELECT parent FROM conversation_groups WHERE id=?", (gid,))[0]["parent"]
            if "parent" in body:
                parent = body["parent"]
                if parent is not None:
                    store.require_group(parent)
                groups = {g["id"]: g for g in store.rows("SELECT id,parent FROM conversation_groups")}
                ancestor, depth = parent, 1
                while ancestor:
                    if ancestor == gid:
                        raise ValueError("A group cannot be moved inside itself or one of its subgroups.")
                    depth += 1
                    ancestor = groups[ancestor]["parent"]
                def subtree_depth(ident):
                    children = [g["id"] for g in groups.values() if g["parent"] == ident]
                    return 1 + max((subtree_depth(child) for child in children), default=0)
                if depth + subtree_depth(gid) - 1 > 8:
                    raise ValueError("Use at most eight levels of groups.")
            if store.rows("SELECT id FROM conversation_groups WHERE parent IS ? AND lower(name)=lower(?) AND id<>?",
                          (parent, name.strip(), gid)):
                raise ValueError("A group with that name already exists here.")
            store.execute("UPDATE conversation_groups SET name=?,parent=? WHERE id=?", (name.strip(), parent, gid))
        return {"id": gid, "name": name.strip(), "parent": parent}

    @app.delete("/api/groups/{gid}")
    async def delete_group(gid: str, session=Depends(auth)):
        async with config_lock:
            store.require_group(gid)
            if store.rows("SELECT id FROM conversation_groups WHERE parent=?", (gid,)) or store.rows(
                    "SELECT conversation FROM conversation_locations WHERE group_id=?", (gid,)) or store.rows(
                    "SELECT id FROM knowledge WHERE group_id=?", (gid,)):
                raise HTTPException(409, "Move its chats and records and remove empty subgroups before deleting this group.")
            store.execute("DELETE FROM conversation_groups WHERE id=?", (gid,))
            return {"deleted": gid}

    @app.get("/api/conversations/{cid}")
    def conversation(cid: str, session=Depends(auth)):
        store.require_conversation(cid)
        turns = store.rows("SELECT t.id,t.messages,t.created,u.metadata FROM turns t LEFT JOIN turn_usage u ON u.turn=t.id WHERE conversation=? ORDER BY t.id", (cid,))
        return {"id": cid, "group_id": store.conversation_group(cid), "title": store.rows("SELECT title FROM conversations WHERE id=?", (cid,))[0]["title"], "turns": [{"id": t["id"], "messages": json.loads(t["messages"]), "created": t["created"],
                                    "usage": json.loads(t["metadata"]) if t["metadata"] else None} for t in turns],
                "actions": [public_action(store.action(r["id"])) for r in store.rows("SELECT id FROM actions WHERE conversation=? ORDER BY created", (cid,))]}

    @app.patch("/api/conversations/{cid}")
    async def rename_conversation(cid: str, request: Request, session=Depends(auth)):
        store.require_conversation(cid)
        body = await request.json()
        if not isinstance(body, dict) or not body or set(body) - {"title", "group_id", "pinned"}:
            raise ValueError("Provide a title or a group to move this chat to.")
        title = body.get("title")
        if "title" in body and (not isinstance(title, str) or not title.strip() or len(title.strip()) > 100):
            raise ValueError("Use a conversation name with 1–100 characters.")
        if body.get("group_id") is not None:
            store.require_group(body["group_id"])
        if "pinned" in body and not isinstance(body["pinned"], bool):
            raise ValueError("Pinned must be true or false.")
        async with config_lock:
            store.require_conversation(cid)
            if "title" in body:
                store.execute("UPDATE conversations SET title=? WHERE id=?", (title.strip(), cid))
            if "group_id" in body:
                store.move_conversation(cid, body["group_id"])
            if "pinned" in body:
                store.execute("INSERT OR REPLACE INTO conversation_flags VALUES (?,?)", (cid, int(body["pinned"])))
        return {"id": cid, "title": store.rows("SELECT title FROM conversations WHERE id=?", (cid,))[0]["title"],
                "group_id": store.conversation_group(cid)}

    @app.delete("/api/conversations/{cid}")
    async def delete_conversation(cid: str, session=Depends(auth)):
        async with config_lock:
            store.require_conversation(cid)
            if (chat_locks.get(cid) and chat_locks[cid].locked()) or store.rows(
                    "SELECT id FROM actions WHERE conversation=? AND status='executing'", (cid,)):
                raise HTTPException(409, "Wait until the current answer or action finishes before deleting.")
            with store.lock, store.db:
                store.db.execute("DELETE FROM turn_usage WHERE turn IN (SELECT id FROM turns WHERE conversation=?)", (cid,))
                store.db.execute("DELETE FROM turns WHERE conversation=?", (cid,))
                store.db.execute("DELETE FROM actions WHERE conversation=?", (cid,))
                store.db.execute("DELETE FROM conversation_locations WHERE conversation=?", (cid,))
                store.db.execute("DELETE FROM conversation_flags WHERE conversation=?", (cid,))
                store.db.execute("DELETE FROM conversation_references WHERE conversation=? OR source=?", (cid, cid))
                store.db.execute("DELETE FROM memory_index WHERE conversation=?", (cid,))
                store.db.execute("DELETE FROM conversation_revisions WHERE conversation=?", (cid,))
                store.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
            chat_locks.pop(cid, None)
            return {"deleted": cid}

    @app.post("/api/conversations/{cid}/edit")
    async def edit_message(cid: str, request: Request, session=Depends(auth)):
        private = session.get("private_chats", {}).get(cid)
        if not private:
            store.require_conversation(cid)
        if chat_locks.get(cid) and chat_locks[cid].locked():
            raise HTTPException(409, "Wait until the current answer finishes before editing")
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected an edited message")
        if chat_locks.get(cid) and chat_locks[cid].locked():
            raise HTTPException(409, "Wait until the current answer finishes before editing")
        turn_id, question = body.get("turn_id"), body.get("question")
        if isinstance(turn_id, bool) or not isinstance(turn_id, int) or turn_id < 1:
            raise ValueError("Choose a saved message to edit")
        if not isinstance(question, str) or not question.strip() or len(question) > 30_000:
            raise ValueError("Question must have 1–30,000 characters")
        if private:
            selected = next((i for i, turn in enumerate(private.turns) if turn["id"] == turn_id), None)
            if selected is None:
                raise HTTPException(404, "Message not found in this conversation")
            private.turns = private.turns[:selected]
            return {"id": cid}
        selected = store.rows("SELECT id,created FROM turns WHERE conversation=? AND id=?", (cid, turn_id))
        if not selected:
            raise HTTPException(404, "Message not found in this conversation")
        # Keep the chat identity and preserve superseded context without branching.
        with store.lock, store.db:
            if store.db.execute("SELECT id FROM actions WHERE conversation=? AND status='executing'", (cid,)).fetchone():
                raise HTTPException(409, "Wait until the current action finishes before editing")
            replaced = [dict(row) for row in store.db.execute(
                "SELECT t.*,u.metadata,p.encrypted AS attachment_preview FROM turns t "
                "LEFT JOIN turn_usage u ON u.turn=t.id LEFT JOIN attachment_previews p ON p.turn=t.id "
                "WHERE t.conversation=? AND t.id>=? ORDER BY t.id", (cid, turn_id))]
            encrypted = store.cipher.encrypt(json.dumps(replaced).encode()).decode()
            store.db.execute("INSERT INTO conversation_revisions(id,conversation,encrypted,created) VALUES (?,?,?,?)",
                             (replaced[-1]["id"], cid, encrypted, time.time()))
            for table, column in (("turn_usage", "turn"), ("attachment_previews", "turn"), ("memory_index", "turn")):
                store.db.execute(f"DELETE FROM {table} WHERE {column} IN "
                                 "(SELECT id FROM turns WHERE conversation=? AND id>=?)", (cid, turn_id))
            store.db.execute("DELETE FROM turns WHERE conversation=? AND id>=?", (cid, turn_id))
            store.db.execute("UPDATE actions SET status='cancelled' WHERE conversation=? AND status='pending' AND created>=?",
                             (cid, selected[0]["created"]))
        return {"id": cid}

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
            turn_config = store.config()
            selected_model = turn_config.get("ai", {}).get("analysis_model") if model_mode == "analysis" else turn_config.get("ai", {}).get("model")
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
                    if event["event"] == "model":
                        selected_model = event["model"]
                    if not demo and event["event"] == "done" and event.get("model"):
                        store.record_ai_activity(turn_config, event["model"])
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not demo and getattr(exc, "status_code", None) in {401, 403, 404}:
                    store.record_ai_activity(turn_config, selected_model, ok=False, message=ai_error(exc))
                message = ai_error(exc)
                if getattr(exc, "status_code", None) is not None:
                    reference = secrets.token_hex(6)
                    store.execute("INSERT INTO ai_failures VALUES (?,?,?,?,?)",
                                  (reference, cid, exc.status_code, message, time.time()))
                    message += " Reference: " + reference
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
            settings_change = action["service"] == "settings" and action["operation"] == "update_github_repositories"
            if (not settings_change and not config.get("allow_writes")) or config.get("_version") != action["config_version"]:
                raise HTTPException(409, "Settings changed; review a new proposal")
            if settings_change:
                if demo:
                    raise HTTPException(409, "Demo connections cannot be changed.")
                from app.repository_settings import prepare_repository
                candidate, preview = await prepare_repository(config, action["payload"], services_factory)
                if preview["after"] != action["preview"]["after"]:
                    raise HTTPException(409, "Proposal changed; ask for a new one")
                store.save_config(candidate)
                result = {"repositories": candidate["github"]["repos"], "message": "Saved GitHub sources. Repository access verified."}
                store.execute("UPDATE actions SET status='completed',result=? WHERE id=? AND status='pending'", (json.dumps(result), aid))
                store.execute("INSERT INTO audit (action,status,result,created) VALUES (?,?,?,?)",
                              (aid, "completed", json.dumps(result), time.time()))
                return public_action(store.action(aid))
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
