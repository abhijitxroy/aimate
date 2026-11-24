"""Explain scope versus missing/hidden resources; never treat a 404 as proof."""
import re


def guidance(config,args,error):
    if args.get("service")=="github":
        match=re.match(r"^/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/|$)",str(args.get("path","")))
        repo=match.group(1) if match else None
    else:
        repo=args.get("repo")
    if not isinstance(repo,str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo):
        return None
    if not any(word in error.lower() for word in ("404","outside","scope")):
        return None
    configured=repo.casefold() in {r.casefold() for r in config.get("github",{}).get("repos",[])}
    return {"repo":repo,"action":"check_connection" if configured or config.get("_private") else "validate_repository",
            "message": "Already configured. The target may be missing or hidden by token/SSO permissions; check the full link and connection details."
                       if configured else "Outside the saved repository scope. Validate token access before adding it."}


def register(app,store,auth,services_factory,session_check):
    from fastapi import Depends, HTTPException, Request
    from app.repository_settings import propose_repository
    @app.post("/api/conversations/{cid}/repository-proposal")
    async def repository_proposal(cid:str,request:Request,session=Depends(auth)):
        if session.get("role")!="admin":
            raise HTTPException(403,"Administrator access is required to review source-setting changes.")
        store.require_conversation(cid)
        body=await request.json()
        if not isinstance(body,dict) or set(body)!={"repo"}:
            raise ValueError("Provide the repository to validate.")
        return await propose_repository(store,store.config(),cid,body,services_factory,access_check=session_check(session))
