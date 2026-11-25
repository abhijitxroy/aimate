"""Preview and recheck cleanup of managed objects; never scan arbitrary user files."""
import hashlib
import json
import time
from fastapi import Depends, HTTPException, Request


def preview(store):
    now=time.time()
    documents=store.rows("""SELECT d.id,d.name,length(d.encrypted) AS bytes FROM documents d
        WHERE NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id=d.conversation)
        AND NOT EXISTS (SELECT 1 FROM turns t WHERE instr(t.messages,d.id)>0)
        AND NOT EXISTS (SELECT 1 FROM conversation_revisions r WHERE r.conversation=d.conversation)
        AND NOT EXISTS (SELECT 1 FROM conversation_references r WHERE r.source=d.conversation)
        AND NOT EXISTS (SELECT 1 FROM actions a WHERE a.status IN ('pending','executing') AND instr(a.payload,d.id)>0)
        ORDER BY d.id""")
    caches=store.rows("SELECT id,length(encrypted) AS bytes FROM evidence_cache WHERE expires<=? ORDER BY id",(now,))
    files=[]
    root=store.directory.resolve()
    log=root/"requests.jsonl.1"
    if log.exists() and not log.is_symlink() and log.is_file() and log.resolve().parent==root:
        info=log.stat()
        if now-info.st_mtime>7*86400:
            files.append({"name":log.name,"bytes":info.st_size,"modified":info.st_mtime_ns})
    plan={"documents":documents,"expired_cache":caches,"logs":files}
    digest=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    return {**plan,"fingerprint":digest,"estimated_bytes":sum(item["bytes"] for entries in plan.values() for item in entries),
            "notice":"Only orphaned, unreferenced attachment text, expired evidence snapshots and a rotated diagnostic log older than seven days. Chats, Diary, tasks, vault, settings, keys, live database files and backups are protected. Deleting database rows does not immediately shrink the database file."}


def apply(store, fingerprint):
    with store.lock:
        current=preview(store)
        if current["fingerprint"]!=fingerprint:
            raise ValueError("Cleanup dependencies changed. Preview again before confirming.")
        removed={"documents":0,"expired_cache":0,"logs":0,"skipped_logs":0}
        with store.db:
            for table,key in (("documents","documents"),("evidence_cache","expired_cache")):
                for item in current[key]:
                    store.db.execute(f"DELETE FROM {table} WHERE id=?",(item["id"],))
                    removed[key]+=1
        root=store.directory.resolve()
        for item in current["logs"]:
            path=root/item["name"]
            # The preview uses a fixed owned filename, never a caller-supplied path.
            if path.name!="requests.jsonl.1" or path.is_symlink() or path.resolve().parent!=root:
                removed["skipped_logs"]+=1; continue
            try:
                if path.stat().st_mtime_ns!=item["modified"]:
                    removed["skipped_logs"]+=1; continue
                path.unlink()
                removed["logs"]+=1
            except OSError:
                removed["skipped_logs"]+=1
        return removed


def register(app,store,auth,config_lock,active_streams):
    def permitted(session):
        if session.get("role") not in {"admin","developer"}:
            raise HTTPException(403,"Administrator or developer access required.")
        if active_streams.get(session.get("grant") or "owner",0):
            raise HTTPException(409,"Wait for this workspace's answers to finish before cleanup.")

    @app.get("/api/maintenance")
    async def cleanup_preview(session=Depends(auth)):
        permitted(session)
        async with config_lock:
            plan=preview(store)
            session["cleanup_plan"]={"fingerprint":plan["fingerprint"],"expires":time.time()+300}
            return plan

    @app.post("/api/maintenance/cleanup")
    async def cleanup(request:Request,session=Depends(auth)):
        permitted(session)
        body=await request.json()
        plan=session.get("cleanup_plan")
        if (not isinstance(body,dict) or set(body)!={"fingerprint"} or not plan or
                plan["expires"]<=time.time() or body["fingerprint"]!=plan["fingerprint"]):
            raise ValueError("Preview cleanup again; the five-minute review has expired or is invalid.")
        async with config_lock:
            permitted(session)
            result=apply(store,plan["fingerprint"])
            session.pop("cleanup_plan",None)
            return {"removed":result}
