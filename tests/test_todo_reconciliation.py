import json
import tempfile
import unittest

from app.store import Store
from tools.reconcile_todos import MERGES, reconcile


class ReconcileTests(unittest.TestCase):
    def test_dry_run_merge_journal_idempotence_and_preserve_canonical_status(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            old, canonical = next(iter(MERGES.items()))
            for ident, title in ((old, "Original duplicate\nFull remark"), (canonical, "Verified canonical")):
                store.execute("INSERT INTO todos VALUES (?,?,1,1,1)", (ident, title))
            task = {"id": "new-task", "title": "P0 · Open\nRemark: Need verification.",
                    "completed": False, "type": "task", "priority": "P0"}
            self.assertEqual(reconcile(store, [task]), {"merged": 1, "added": 1, "applied": False})
            self.assertEqual(len(store.rows("SELECT * FROM todos")), 2)
            self.assertEqual(reconcile(store, [task], True)["merged"], 1)
            path = store.directory / "todo-merge-history.fernet"
            self.assertNotIn(b"Original duplicate", path.read_bytes())
            history = json.loads(store.cipher.decrypt(path.read_bytes()))
            self.assertEqual(history[0]["task"]["title"], "Original duplicate\nFull remark")
            self.assertEqual(store.rows("SELECT completed FROM todos WHERE id=?", (canonical,))[0]["completed"], 1)
            self.assertEqual(reconcile(store, [task], True)["merged"], 0)
            self.assertEqual(len(store.rows("SELECT * FROM todos")), 2)
            self.assertEqual(len(json.loads(store.cipher.decrypt(path.read_bytes()))), 1)
            store.db.close()

    def test_missing_canonical_or_invalid_plan_never_deletes_task(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            old = next(iter(MERGES))
            store.execute("INSERT INTO todos VALUES (?,?,0,1,1)", (old, "Unchanged"))
            with self.assertRaises(ValueError):
                reconcile(store, [], True)
            with self.assertRaises(ValueError):
                reconcile(store, [{"id": "bad"}], True)
            self.assertEqual(store.rows("SELECT title FROM todos")[0]["title"], "Unchanged")
            store.db.close()
