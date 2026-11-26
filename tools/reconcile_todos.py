"""Explicit backlog reconciliation. Dry-run first; encrypted merge history retained."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store
from app.todo_priorities import validate as priority_valid
from app.todo_types import validate as type_valid

MERGES = {
    "f74dac77ba86df35bd45050b": "audit-45598b108d57b500ed062e06",
    "3feacc2fd0488d415d0e3732": "audit-45598b108d57b500ed062e06",
    "97df82540b454209de829f85": "audit-a64983ae13f38e987b979a30",
    "115fb331adf507255ba60c7a": "audit-3a691f7d991e8d3df4a90393",
    "8796eb990f5e482e4db99bfa": "audit-b0f4e50a4f5a4b5d8e355c8f",
    "d55d279d623a9760b73c7cf3": "audit-bc575b0a1ce95434f2f6e7c0",
}


def reconcile(store, tasks, apply=False):
    if not isinstance(tasks, list) or any(not isinstance(row, dict) for row in tasks):
        raise ValueError("Use a list of explicit task records.")
    ids = set()
    for task in tasks:
        if (set(task) != {"id", "title", "completed", "type", "priority"} or
                not isinstance(task["id"], str) or not task["id"] or task["id"] in ids or
                not isinstance(task["title"], str) or not 1 <= len(task["title"]) <= 10000 or
                type(task["completed"]) is not bool):
            raise ValueError("Task records require unique IDs, bounded titles and boolean completion.")
        ids.add(task["id"])
        type_valid(task["type"])
        priority_valid(task["priority"])
    with store.lock:
        current = {row["id"]: row for row in store.rows(
            "SELECT t.*,k.kind,p.priority FROM todos t LEFT JOIN todo_types k ON k.id=t.id LEFT JOIN todo_priorities p ON p.id=t.id")}
        merges = {old: target for old, target in MERGES.items() if old in current}
        if any(target not in current for target in merges.values()):
            raise ValueError("Canonical task is missing; no changes made.")
        additions = [task for task in tasks if task["id"] not in current]
        result = {"merged": len(merges), "added": len(additions), "applied": apply}
        if not apply:
            return result
        # Persist exact original selected rows before removing duplicate list entries.
        # Portable backup includes this encrypted file. Existing tasks stay untouched.
        path = store.directory / "todo-merge-history.fernet"
        if path.is_symlink() or path.resolve().parent != store.directory.resolve():
            raise ValueError("Unsafe merge-history location.")
        history = json.loads(store.cipher.decrypt(path.read_bytes())) if path.exists() else []
        if not isinstance(history, list):
            raise ValueError("Invalid existing merge history; no changes made.")
        now = time.time()
        history += [{"task": current[old], "canonical": target, "merged_at": now}
                    for old, target in merges.items()]
        raw = json.dumps(history, ensure_ascii=False).encode()
        if len(raw) > 4_000_000:
            raise ValueError("Merge history exceeded its safe limit; no changes made.")
        if merges:
            temporary = path.with_name("todo-merge-" + secrets.token_hex(8) + ".tmp")
            try:
                temporary.write_bytes(store.cipher.encrypt(raw))
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        with store.db:
            for old, target in merges.items():
                remark = "\n\nRemark: Duplicate " + old + " merged here; exact previous record preserved in encrypted merge history."
                store.db.execute("UPDATE todos SET title=title||?,updated=? WHERE id=?", (remark, now, target))
                for table in ("todo_types", "todo_priorities", "todos"):
                    store.db.execute("DELETE FROM " + table + " WHERE id=?", (old,))
            for task in additions:
                store.db.execute("INSERT INTO todos VALUES (?,?,?,?,?)",
                                 (task["id"], task["title"], int(task["completed"]), now, now))
                store.db.execute("INSERT INTO todo_types VALUES (?,?)", (task["id"], task["type"]))
                store.db.execute("INSERT INTO todo_priorities VALUES (?,?)", (task["id"], task["priority"]))
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    store = Store(args.data_dir)
    try:
        print(json.dumps(reconcile(store, json.loads(Path(args.plan).read_text(encoding="utf-8")), args.apply)))
    finally:
        store.db.close()
