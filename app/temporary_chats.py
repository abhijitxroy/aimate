"""Optional temporary-chat lifecycle. Transcripts and attachments stay in RAM."""
import asyncio
from contextlib import suppress
import os
import re
import time


def enabled():
    return os.environ.get("AIMATE_TEMPORARY_CHATS_ENABLED") != "0"


def options(body):
    value = body.get("temporary")
    if value is None:
        return "legacy", ""
    if not enabled():
        raise ValueError("Temporary chat lifetimes are disabled on this server.")
    if not isinstance(value, dict) or set(value) != {"lifetime", "page"}:
        raise ValueError("Choose a temporary chat lifetime.")
    mode, page = value["lifetime"], value["page"]
    if not isinstance(mode,str) or mode not in {"session", "day"} or not isinstance(page, str) or not re.fullmatch(r"[a-f0-9-]{32,36}", page):
        raise ValueError("Choose Session or One day and a valid page session.")
    return mode, page


def prune(session, now=None):
    now = time.time() if now is None else now
    chats = session.get("private_chats", {})
    for ident, chat in list(chats.items()):
        if chat.closed or chat.expires <= now:
            chat.close()
            chats.pop(ident, None)


def close_session(session):
    for chat in list(session.get("private_chats", {}).values()):
        chat.close()
    session.get("private_chats", {}).clear()


async def sweep(sessions):
    while True:
        now = time.time()
        for token, session in list(sessions.items()):
            if session["created"] + 12 * 3600 <= now:
                close_session(session)
                sessions.pop(token, None)
            else:
                prune(session, now)
        await asyncio.sleep(60)


async def stop(task, sessions):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    for session in sessions.values():
        close_session(session)


def register(app, auth):
    from fastapi import Depends, Request

    @app.post("/api/conversations/temporary-close")
    async def close_page(request: Request, session=Depends(auth)):
        if not enabled():
            return {"closed": 0}
        body = await request.json()
        page = body.get("page") if isinstance(body, dict) else None
        if not isinstance(page, str) or not re.fullmatch(r"[a-f0-9-]{32,36}", page):
            raise ValueError("Invalid page session.")
        closed = 0
        for ident, chat in list(session["private_chats"].items()):
            if chat.lifetime == "session" and chat.page == page:
                chat.close()
                session["private_chats"].pop(ident, None)
                closed += 1
        return {"closed": closed}
