"""Task categories kept separate so legacy task rows/backups remain compatible."""
KINDS=("task","enhancement","feature","story","bug","triage","note")


def validate(value):
    if not isinstance(value,str) or value not in KINDS:
        raise ValueError("Choose task, enhancement, feature, story, bug, triage or note.")
    return value


def save(store,ident,kind):
    store.execute("INSERT OR REPLACE INTO todo_types VALUES (?,?)",(ident,validate(kind)))
