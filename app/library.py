"""Personal reusable prompts, stored inside each account's encrypted database."""
import secrets
import time
from fastapi import Depends, Request


def save(store,body,ident=None):
    if not isinstance(body,dict) or set(body)!={"title","body"}:
        raise ValueError("Provide a prompt name and text.")
    title,text=body["title"],body["body"]
    if not isinstance(title,str) or not 1<=len(title.strip())<=80 or not isinstance(text,str) or not text.strip() or len(text)>6000:
        raise ValueError("Use a name under 80 characters and prompt text under 6,000 characters.")
    if ident and not store.rows("SELECT id FROM library_items WHERE id=?",(ident,)):
        raise ValueError("Saved prompt not found.")
    if not ident and store.rows("SELECT count(*) AS n FROM library_items")[0]["n"]>=200:
        raise ValueError("Prompt limit reached. Remove an unused prompt first.")
    ident=ident or secrets.token_hex(12)
    store.execute("INSERT OR REPLACE INTO library_items VALUES (?,?,?,?,?)",(ident,title.strip(),text,"prompt",time.time()))
    return {"id":ident}


def register(app,store,auth,config_lock):
    @app.get("/api/library")
    def entries(session=Depends(auth)):
        return {"items":store.rows("SELECT * FROM library_items ORDER BY updated DESC")}

    @app.post("/api/library")
    async def add(request:Request,session=Depends(auth)):
        async with config_lock:
            return save(store,await request.json())

    @app.patch("/api/library/{ident}")
    async def edit(ident:str,request:Request,session=Depends(auth)):
        async with config_lock:
            return save(store,await request.json(),ident)

    @app.delete("/api/library/{ident}")
    async def delete(ident:str,session=Depends(auth)):
        async with config_lock:
            if not store.rows("SELECT id FROM library_items WHERE id=?",(ident,)):
                raise ValueError("Saved prompt not found.")
            store.execute("DELETE FROM library_items WHERE id=?",(ident,))
            return {"deleted":ident}
