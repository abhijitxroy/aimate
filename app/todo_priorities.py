"""Optional task priority metadata; legacy task rows stay unchanged."""
import os

PRIORITIES=("P0","P1","P2","P3")


def enabled():
    return os.environ.get("AIMATE_TODO_PRIORITIES_ENABLED","1").lower() not in {"0","false"}


def install(store):
    store.execute("CREATE TABLE IF NOT EXISTS todo_priorities (id TEXT PRIMARY KEY, priority TEXT NOT NULL)")


def validate(value):
    if not enabled():
        raise ValueError("Task priorities are disabled on this server.")
    if not isinstance(value,str) or value not in PRIORITIES:
        raise ValueError("Choose P0, P1, P2 or P3.")
    return value


def save(store,ident,value):
    store.execute("INSERT OR REPLACE INTO todo_priorities VALUES (?,?)",(ident,validate(value)))


def remove(store,ident):
    store.execute("DELETE FROM todo_priorities WHERE id=?",(ident,))
