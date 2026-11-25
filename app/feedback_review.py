"""Workspace-scoped feedback review; no automatic model calls or remote writes."""
import os
import secrets
import time
import math
from fastapi import Depends, HTTPException, Request

STATES=("new","investigating","planned","resolved","closed")
ASSESSMENTS=("unverified","helpful","confirmed_issue","already_available","needs_information")


def enabled():
    return os.environ.get("AIMATE_FEEDBACK_REVIEW_ENABLED") != "0"


def install(store):
    if enabled():
        store.execute("CREATE TABLE IF NOT EXISTS feedback_reviews (id TEXT PRIMARY KEY, state TEXT NOT NULL, assessment TEXT NOT NULL, reply TEXT NOT NULL, evidence TEXT NOT NULL, task TEXT, updated REAL NOT NULL, reviewer TEXT NOT NULL)")


def safe(store,value):
    from app.connectors import scrub
    from app.vault import redactions
    return scrub(value,{**store.config(),"_vault_secrets":redactions(store)})


def register(app,store,auth,config_lock):
    if not enabled():
        return

    def editable(session):
        if session["role"] not in {"admin","developer"}:
            raise HTTPException(403,"Administrator or developer review access required.")

    @app.get("/api/feedback/reviews")
    def reviews(before:float=0,session=Depends(auth)):
        if not math.isfinite(before) or before<0:
            raise ValueError("Use a non-negative feedback cursor.")
        rows=store.rows("SELECT f.*,COALESCE(r.state,'new') AS state,COALESCE(r.assessment,'unverified') AS assessment,COALESCE(r.reply,'') AS reply,COALESCE(r.evidence,'') AS evidence,CASE WHEN EXISTS(SELECT 1 FROM todos WHERE id=r.task) THEN r.task END AS task,r.updated AS reviewed_at,r.reviewer FROM feedback f LEFT JOIN feedback_reviews r ON r.id=f.id WHERE (?=0 OR f.created<?) ORDER BY f.created DESC LIMIT 51",(before,before))
        return {"entries":rows[:50],"next_before":rows[49]["created"] if len(rows)>50 else None,
                "can_review":session["role"] in {"admin","developer"},
                "notice":"Reviewer assessments, not automatic verification. Feedback belongs to this workspace."}

    @app.patch("/api/feedback/{ident}/review")
    async def review(ident:str,request:Request,session=Depends(auth)):
        editable(session)
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={"state","assessment","reply","evidence"}:
            raise ValueError("Provide state, assessment, reply and evidence.")
        if body["state"] not in STATES or body["assessment"] not in ASSESSMENTS:
            raise ValueError("Choose a valid feedback state and reviewer assessment.")
        if any(not isinstance(body[k],str) or len(body[k])>2000 for k in ("reply","evidence")):
            raise ValueError("Keep the reply and evidence under 2,000 characters each.")
        if body["assessment"]=="confirmed_issue" and not body["evidence"].strip():
            raise ValueError("Add evidence before classifying a confirmed issue.")
        if (body["state"]=="resolved" or body["assessment"]=="already_available") and not body["reply"].strip():
            raise ValueError("Add a reply explaining the resolution or existing feature.")
        async with config_lock:
            if not store.rows("SELECT id FROM feedback WHERE id=?",(ident,)):
                raise ValueError("Feedback not found in this workspace.")
            with store.lock:
                task=store.rows("SELECT task FROM feedback_reviews WHERE id=?",(ident,))
                store.execute("INSERT OR REPLACE INTO feedback_reviews VALUES (?,?,?,?,?,?,?,?)",
                    (ident,body["state"],body["assessment"],safe(store,body["reply"]),safe(store,body["evidence"]),
                     task[0]["task"] if task else None,time.time(),session["role"]))
        return {"saved":ident}

    @app.post("/api/feedback/{ident}/task")
    async def task(ident:str,session=Depends(auth)):
        editable(session)
        async with config_lock:
            with store.lock:
                rows=store.rows("SELECT f.category,f.comment,r.assessment,r.task FROM feedback f JOIN feedback_reviews r ON r.id=f.id WHERE f.id=?",(ident,))
                if not rows or rows[0]["assessment"]!="confirmed_issue":
                    raise ValueError("Review and confirm the issue with evidence before creating a task.")
                row=rows[0]
                if row["task"] and store.rows("SELECT id FROM todos WHERE id=?",(row["task"],)):
                    return {"id":row["task"],"existing":True}
                if store.rows("SELECT COUNT(*) AS n FROM todos")[0]["n"]>=2000:
                    raise ValueError("Task limit reached. Remove old tasks first.")
                ident_task,now=secrets.token_hex(12),time.time()
                title=safe(store,f"Feedback · {row['category']}\n\n{row['comment']}\n\nFeedback ID: {ident}")
                with store.db:
                    store.db.execute("INSERT INTO todos VALUES (?,?,0,?,?)",(ident_task,title,now,now))
                    store.db.execute("INSERT INTO todo_types VALUES (?,?)",(ident_task,"bug"))
                    store.db.execute("INSERT INTO todo_priorities VALUES (?,?)",(ident_task,"P1"))
                    store.db.execute("UPDATE feedback_reviews SET task=?,state='planned',updated=? WHERE id=?",(ident_task,now,ident))
        return {"id":ident_task,"existing":False}
