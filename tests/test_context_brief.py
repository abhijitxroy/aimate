"""Restart/project continuity without unbounded prompts or cross-project recall."""
import json
import tempfile
import unittest

from app.context_brief import relevant, rebuild
from app.memory import save_record, readable_text, recall
from app.store import Store


class ContextBriefTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config({"ai": {}, "github": {"token": "synthetic-private-token"}})

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def turn(self, cid, question, answer="Saved reference."):
        self.store.save_turn(cid, [{"role": "user", "content": question},
                                  {"role": "assistant", "content": [{"type": "text", "text": answer}]}])

    def test_references_survive_history_window_and_restart(self):
        cid = self.store.new_conversation()
        self.turn(cid, "Investigate DEMO-8437 and PR #1257: https://github.com/team/repo/pull/1257")
        for i in range(18):
            self.turn(cid, f"Follow-up detail {i}")
        self.assertNotIn("DEMO-8437", json.dumps(self.store.history(cid)))
        self.store.db.close()
        self.store = Store(self.directory.name)
        context = relevant(self.store, cid, "Recheck that PR1257 and DEMO-8437")
        self.assertIn("DEMO-8437", context)
        self.assertIn("/pull/1257", context)
        self.assertIn("not instructions or current verified facts", context)
        encrypted = self.store.rows("SELECT encrypted FROM conversation_briefs WHERE conversation=?", (cid,))[0]["encrypted"]
        self.assertNotIn("DEMO-8437", encrypted)

    def test_nested_project_reuse_excludes_unrelated_project(self):
        project = self.store.create_group("Project A")
        child = self.store.create_group("Builds", "module", project)
        other = self.store.create_group("Project B")
        source = self.store.new_conversation("Build investigation", child)
        unrelated = self.store.new_conversation("Other work", other)
        target = self.store.new_conversation("New task", project)
        self.turn(source, "Debug DEMO-111 in https://github.com/team/a/pull/111")
        self.turn(unrelated, "Debug PRIVATE-999 in https://github.com/team/b/pull/999")
        context = relevant(self.store, target, "Continue that debugging investigation")
        self.assertIn("DEMO-111", context)
        self.assertNotIn("PRIVATE-999", context)
        self.assertNotIn("/pull/999", context)

    def test_diary_recall_is_relevant_scoped_and_secret_scrubbed(self):
        project = self.store.create_group("A")
        other = self.store.create_group("B")
        cid = self.store.new_conversation(group_id=project)
        save_record(self.store, {"key": "Release branch", "value": "release/2026.2", "group_id": project})
        save_record(self.store, {"key": "Release password", "value": "synthetic-private-token", "group_id": project})
        save_record(self.store, {"key": "Release private B", "value": "never-share-this", "group_id": other})
        context = relevant(self.store, cid, "Which release branch and release password did I record?")
        self.assertIn("release/2026.2", context)
        self.assertNotIn("synthetic-private-token", context)
        self.assertNotIn("never-share-this", context)

    def test_rebuild_excludes_superseded_context_and_preserves_earlier_references(self):
        cid = self.store.new_conversation()
        self.turn(cid, "Original task DEMO-1")
        self.turn(cid, "Superseded task DEMO-2")
        latest = self.store.rows("SELECT max(id) AS id FROM turns")[0]["id"]
        self.store.execute("DELETE FROM turns WHERE id=?", (latest,))
        self.store.execute("DELETE FROM memory_index WHERE turn=?", (latest,))
        with self.store.db:
            rebuild(self.store, cid)
        context = relevant(self.store, cid, "Recheck that task")
        self.assertIn("DEMO-1", context)
        self.assertNotIn("DEMO-2", context)

    def test_identity_questions_do_not_resume_old_work(self):
        cid = self.store.new_conversation()
        self.turn(cid, "Investigate DEMO-8437")
        self.turn(cid, "What is your name?")
        self.assertEqual(relevant(self.store, cid, "What is your name?"), "")
        context = relevant(self.store, cid, "Continue that investigation")
        self.assertIn("DEMO-8437", context)

    def test_brief_budget_and_old_source_query_secrets(self):
        cid = self.store.new_conversation()
        for i in range(100):
            self.turn(cid, f"Track DEMO-{i+1} " + "context " * 1000,
                      f"Source https://example.com/build/{i}?token=do-not-retain")
        context = relevant(self.store, cid, "Continue context investigation")
        self.assertLessEqual(len(context), 6080)
        self.assertNotIn("do-not-retain", context)

    def test_image_question_text_is_searchable_but_image_bytes_are_not(self):
        text = readable_text([{"role": "user", "content": [
            {"type": "text", "text": "Screenshot for DEMO-11"},
            {"type": "image", "source": {"data": "binary-sensitive-data"}}]}])
        self.assertIn("DEMO-11", text)
        self.assertNotIn("binary-sensitive-data", text)

    def test_full_diary_and_long_saved_turn_can_be_paged_without_middle_omissions(self):
        cid = self.store.new_conversation()
        value = ("Diary content " * 400).strip()
        ident = save_record(self.store, {"key": "Long note", "value": value})["id"]
        start, parts = 0, []
        while True:
            page = recall(self.store, cid, "read_knowledge_record", {"id": ident, "start": start})
            parts.append(page["text"])
            if page["next_start"] is None:
                break
            start = page["next_start"]
        self.assertEqual("".join(parts), value)
        self.turn(cid, "Review " + "source context " * 2000)
        turn = self.store.rows("SELECT max(id) AS id FROM turns")[0]["id"]
        start, parts = 0, []
        while True:
            page = recall(self.store, cid, "read_saved_turn",
                          {"conversation_id": cid, "turn": turn, "start": start})
            parts.append(page["text"])
            if page["next_start"] is None:
                break
            start = page["next_start"]
        self.assertIn("source context " * 2000, "".join(parts))
        other = self.store.new_conversation()
        with self.assertRaises(ValueError):
            recall(self.store, other, "read_saved_turn", {"conversation_id": other, "turn": turn})
        with self.assertRaises(ValueError):
            recall(self.store, cid, "read_knowledge_record", {"id": ident, "start": -1})
