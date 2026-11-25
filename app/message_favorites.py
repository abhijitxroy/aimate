"""Favorite readable saved messages inside existing encrypted turn metadata."""
import json
import os
from fastapi import Depends, Request


def text(messages,role,metadata):
    if role=="user" and isinstance(metadata.get("display_question"),str):
        return metadata["display_question"]
    parts=[]
    for message in messages:
        if message.get("role")!=role:
            continue
        content=message.get("content","")
        if isinstance(content,str):
            parts.append(content)
        elif isinstance(content,list):
            parts.extend(block.get("text","") for block in content if block.get("type")=="text")
    return "\n\n".join(parts)


def register(app,store,auth,config_lock):
    if os.environ.get("AIMATE_MESSAGE_FAVORITES_ENABLED") == "0":
        return

    @app.get("/api/favorites")
    def favorites(before_turn:int=0,session=Depends(auth)):
        if before_turn<0:
            raise ValueError("Use a non-negative favorite page cursor.")
        entries=[]
        rows=store.rows("SELECT t.id,t.conversation,t.messages,t.created,u.metadata,c.title FROM turns t JOIN turn_usage u ON u.turn=t.id JOIN conversations c ON c.id=t.conversation WHERE u.metadata LIKE '%favorite_roles%' AND (?=0 OR t.id<?) ORDER BY t.id DESC LIMIT 51",(before_turn,before_turn))
        for row in rows[:50]:
            metadata=json.loads(row["metadata"])
            for role in metadata.get("favorite_roles",[]):
                if role in {"user","assistant"}:
                    entries.append({"conversation":row["conversation"],"turn":row["id"],"role":role,"title":row["title"],
                                    "created":row["created"],"text":text(json.loads(row["messages"]),role,metadata)})
        return {"entries":entries,"next_before_turn":rows[49]["id"] if len(rows)>50 else None}

    @app.post("/api/conversations/{cid}/favorites/{turn}/{role}")
    async def favorite(cid:str,turn:int,role:str,request:Request,session=Depends(auth)):
        body=await request.json()
        if role not in {"user","assistant"} or not isinstance(body,dict) or set(body)!={"pinned"} or type(body["pinned"]) is not bool:
            raise ValueError("Choose a saved user/assistant message and a boolean pinned state.")
        async with config_lock:
            with store.lock:
                rows=store.rows("SELECT t.messages,u.metadata FROM turns t LEFT JOIN turn_usage u ON u.turn=t.id WHERE t.id=? AND t.conversation=?",(turn,cid))
                if not rows:
                    raise ValueError("Saved message not found in this workspace. Private chats cannot save favorites.")
                metadata=json.loads(rows[0]["metadata"]) if rows[0]["metadata"] else {}
                if not text(json.loads(rows[0]["messages"]),role,metadata).strip():
                    raise ValueError("This message has no readable text to pin.")
                roles=set(metadata.get("favorite_roles",[])) & {"user","assistant"}
                if body["pinned"]:
                    roles.add(role)
                else:
                    roles.discard(role)
                if roles:
                    metadata["favorite_roles"]=sorted(roles)
                else:
                    metadata.pop("favorite_roles",None)
                store.execute("INSERT OR REPLACE INTO turn_usage VALUES (?,?)",(turn,json.dumps(metadata)))
        return {"pinned":body["pinned"]}
