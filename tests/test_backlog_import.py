import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from app.store import Store
from tools.import_audited_todos import read_tasks


class BacklogImportTests(unittest.TestCase):
    def test_structured_import_preserves_format_types_ids_and_operator_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)/"data"; source = Path(directory)/"tasks.json"
            store = Store(data); store.db.close()
            text = "P1 · WIP — Keep format\n\n- One\n- Two"
            source.write_text(json.dumps([{"id":"example","title":text,"completed":False,"type":"enhancement"}]),encoding="utf-8")
            script = Path(__file__).resolve().parents[1]/"tools/import_audited_todos.py"
            for attempt in range(2):
                result = subprocess.run([sys.executable,str(script),"--data-dir",str(data),"--audit",str(source)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                summary=json.loads(result.stdout)
                self.assertEqual(summary["added"],1 if attempt==0 else 0)
                store = Store(data)
                self.assertEqual(len(store.rows("SELECT * FROM todos")),1)
                self.assertEqual(store.rows("SELECT kind FROM todo_types")[0]["kind"],"enhancement")
                if attempt==0:
                    self.assertEqual(store.rows("SELECT title FROM todos")[0]["title"],text)
                    store.execute("UPDATE todos SET title='Operator edit',completed=1")
                else:
                    row=store.rows("SELECT title,completed FROM todos")[0]
                    self.assertEqual((row["title"],row["completed"]),("Operator edit",1))
                store.db.close()

    def test_bad_json_and_duplicate_ids_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"tasks.json"
            valid={"id":"x","title":"Task","completed":False}
            for values in ([valid,valid],[{**valid,"completed":"false"}],[{**valid,"type":"unknown"}],[]):
                path.write_text(json.dumps(values),encoding="utf-8")
                with self.assertRaises(ValueError):read_tasks(path)

    def test_markdown_in_progress_remains_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"tasks.md"
            path.write_text("| P1 · Work | Example | In progress | Live validation pending |\n",encoding="utf-8")
            task=read_tasks(path)[0]
            self.assertEqual((task["status"],task["completed"]),("WIP",0))
