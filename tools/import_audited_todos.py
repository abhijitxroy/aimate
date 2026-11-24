"""Import the audited backlog without replacing existing personal tasks."""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import connect
from app.device_key import load_key
from contextlib import closing


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=root / ".data")
    parser.add_argument("--audit", type=Path, default=root / "docs/todo-audit-2026-11-24.md")
    args = parser.parse_args()
    tasks = []
    for line in args.audit.read_text(encoding="utf-8").splitlines():
        if not line.startswith(tuple(f"| P{level} " for level in range(4))):
            continue
        priority, item, status, detail = [cell.strip() for cell in line.strip("|").split("|")]
        state = {"Full": "Done", "Partial": "WIP", "Not touched": "Planned"}[status]
        ident = "audit-" + hashlib.sha256(item.encode()).hexdigest()[:24]
        title = f"{priority} · {state} — {item}\n\n{detail}"
        if len(title) > 6000:
            raise ValueError("Audited task exceeds the supported title size.")
        tasks.append({"id": ident, "title": title, "completed": int(status == "Full"),
                      "status": state, "priority": priority.split()[0]})
    if not tasks:
        raise ValueError("No audited tasks found.")
    data = args.data_dir.resolve()
    database = data / "app.sqlite3"
    if not database.is_file():
        raise ValueError("Restore the workspace before importing tasks.")
    key = load_key(data)
    db = connect(database, key)
    snapshot = data / f"before-todo-import-{time.time_ns()}.sqlite3"
    try:
        with closing(connect(snapshot, key)) as backup:
            db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Pre-import snapshot verification failed.")
        inserted, now = 0, time.time()
        with db:
            for index, task in enumerate(tasks):
                # Stable IDs make reruns safe and preserve user edits/completion.
                cur = db.execute(
                    "INSERT OR IGNORE INTO todos (id,title,completed,created,updated) VALUES (?,?,?,?,?)",
                    (task["id"], task["title"], task["completed"], now - index, now))
                inserted += cur.rowcount
        summary = Counter(task["status"] for task in tasks)
        print(json.dumps({"added": inserted, "audit_total": len(tasks), "statuses": dict(summary),
                          "existing_tasks_preserved": True}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
