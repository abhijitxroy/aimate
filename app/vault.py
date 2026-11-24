"""Encrypted personal records. AI sharing is off unless explicitly enabled per entry."""
import json
import secrets
import time


TOOL = {"name":"read_vault_entry", "description":"Read a named vault entry explicitly marked AI-accessible by the administrator. Do not guess names or request secrets unless the user asks to use that entry. Never echo its value in your answer.",
        "input_schema":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"],"additionalProperties":False}}


def entries(store):
    return store.rows("SELECT id,name,ai_access,updated FROM vault_entries ORDER BY name")


def save(store, body, ident=None):
    name, value, enabled = body.get("name"), body.get("value"), body.get("ai_access",False)
    if not isinstance(name,str) or not 1 <= len(name.strip()) <= 100 or not isinstance(value,str) or not 1 <= len(value) <= 6000 or type(enabled) is not bool:
        raise ValueError("Provide a name, value and AI-access choice.")
    if ident and not store.rows("SELECT id FROM vault_entries WHERE id=?", (ident,)):
        raise ValueError("Vault entry not found.")
    if store.rows("SELECT id FROM vault_entries WHERE lower(name)=lower(?) AND id<>?",(name.strip(),ident or "")):
        raise ValueError("This vault name already exists.")
    ident = ident or secrets.token_hex(16)
    encrypted = store.cipher.encrypt(value.encode()).decode()
    store.execute("INSERT OR REPLACE INTO vault_entries VALUES (?,?,?,?,?)",(ident,name.strip(),encrypted,int(enabled),time.time()))
    return {"id":ident}


def read(store, name, ai=False):
    rows = store.rows("SELECT * FROM vault_entries WHERE name=?", (name,))
    if not rows or (ai and not rows[0]["ai_access"]):
        raise ValueError("Vault entry is missing or not shared with AI.")
    return store.cipher.decrypt(rows[0]["encrypted"].encode()).decode()


def redactions(store):
    return [store.cipher.decrypt(row["encrypted"].encode()).decode() for row in store.rows("SELECT encrypted FROM vault_entries")]
