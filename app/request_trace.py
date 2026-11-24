"""Bounded request telemetry without prompts, headers, query strings or user IDs."""
import json
import os
from pathlib import Path
import secrets
import threading
import time
from fastapi import Depends, HTTPException


def append(directory, entry):
    directory=Path(directory).resolve()
    path=directory/"requests.jsonl"
    if path.is_symlink(): return
    if path.exists() and path.stat().st_size>1_000_000:
        older=directory/"requests.jsonl.1"
        if older.is_symlink(): return
        os.replace(path,older)
    with path.open("a",encoding="utf-8") as stream:
        stream.write(json.dumps(entry,separators=(",",":"))+"\n")
    if os.name!="nt": path.chmod(0o600)


def register(app, owner, store, auth):
    lock=threading.Lock()
    directory=owner.directory.resolve()

    @app.middleware("http")
    async def trace(request, call_next):
        ident=secrets.token_hex(8)
        started=time.perf_counter()
        status=500
        def finish(complete):
            route=getattr(request.scope.get("route"),"path","unmatched")
            entry={"id":ident,"created":time.time(),"method":request.method[:16],"route":route[:160],
                   "status":status,"duration_ms":round((time.perf_counter()-started)*1000,2),
                   "complete":complete}
            try:
                with lock: append(directory,entry)
            except OSError:
                pass  # telemetry must not break the user's request
        try:
            response=await call_next(request)
            status=response.status_code
        except BaseException:
            finish(False)
            raise
        response.headers["X-Request-ID"]=ident
        iterator=response.body_iterator
        async def body():
            complete=False
            try:
                async for chunk in iterator: yield chunk
                complete=True
            finally:
                finish(complete)
        response.body_iterator=body()
        return response

    @app.get("/api/diagnostics")
    def diagnostics(session=Depends(auth)):
        if session.get("role") not in {"admin","developer"}:
            raise HTTPException(403,"Administrator or developer access required.")
        records=[]
        path=directory/"requests.jsonl"
        if path.exists() and not path.is_symlink():
            with lock:
                for line in path.read_text(encoding="utf-8").splitlines()[-100:]:
                    try:
                        row=json.loads(line)
                        if isinstance(row,dict): records.append(row)
                    except ValueError: pass
        times=sorted(row["duration_ms"] for row in records if isinstance(row.get("duration_ms"),(int,float)))
        return {"recent_requests":records,
                "p50_ms":times[len(times)//2] if times else None,
                "p95_ms":times[min(len(times)-1,int(len(times)*.95))] if times else None,
                "saved_conversations":store.rows("SELECT count(*) AS n FROM conversations")[0]["n"],
                "notice":"Recent HTTP response timings, including streamed responses. Routes are templates; no prompts, query strings, credentials or account identifiers are logged."}
