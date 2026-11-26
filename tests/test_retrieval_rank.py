"""Measured retrieval fixtures: identifiers, old evidence, excerpts and isolation."""
import json
import tempfile
import unittest
from unittest.mock import patch

from app.context_brief import relevant
from app.memory import recall, save_record
from app.retrieval_rank import excerpt, score, terms
from app.store import Store


class RankTests(unittest.TestCase):
    def test_exact_identifiers_dominate_generic_and_numeric_lookalikes(self):
        for query, exact, lookalike in (
            ("Review DEMO-8521 release failure", "DEMO-8521", "DEMO-85210 release failure"),
            ("Review PR1257 release", "PR #1257", "PR #12570 release"),
            ("Investigate pull request 17", "https://github.com/team/repo/pull/17", "PR #170")):
            self.assertGreater(score(query, exact), score(query, lookalike))
        self.assertEqual(score("GPU", "gpupdate ran"), 0)
        self.assertEqual(terms("Please tell me about PR1257"), ["pr", "1257"])
        self.assertEqual(terms("please tell me more"), [])

    def test_excerpt_targets_identifier_in_middle_not_generic_prefix(self):
        text = "Release PR #11\n" + "ordinary text " * 400 + "\nPR #1257: useful evidence" + " tail" * 400
        value, start, end = excerpt(text, "Review release PR1257")
        self.assertIn("PR #1257", value)
        self.assertGreater(start, 0)
        self.assertEqual(value, text[start:end])
        self.assertLessEqual(len(value), 1200)


class MemoryRankingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config({"ai": {}, "github": {"token": "synthetic-ranking-secret"}})
        self.cid = self.store.new_conversation()

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def turn(self, cid, text):
        self.store.save_turn(cid, [{"role": "user", "content": text}, {"role": "assistant", "content": "Saved reference."}])

    def test_old_exact_case_beats_many_recent_generic_matches_and_scrubs_secrets(self):
        old = self.store.new_conversation("Target")
        self.turn(old, "DEMO-8521 exact diagnosis synthetic-ranking-secret")
        for index in range(85):
            chat = self.store.new_conversation("Release failure " + str(index))
            self.turn(chat, "DEMO-85210 release failure release failure")
        save_record(self.store, {"key": "DEMO-8521", "value": "old " * 500 + "DEMO-8521 root cause synthetic-ranking-secret"})
        save_record(self.store, {"key": "Release failure", "value": "DEMO-85210 release failure"})
        result = recall(self.store, self.cid, "search_knowledge", {"query": "Review DEMO-8521 release failure"})
        self.assertEqual(result["chats"][0]["conversation_id"], old)
        self.assertEqual(result["records"][0]["key"], "DEMO-8521")
        self.assertNotIn("synthetic-ranking-secret", json.dumps(result))
        self.assertIn("not instructions", result["note"])
        self.assertNotIn("content", result["chats"][0])
        self.assertLessEqual(len(result["chats"]), 8)

    def test_auto_context_keeps_project_scope_and_prefers_old_diary_identifier(self):
        project = self.store.create_group("A")
        other = self.store.create_group("B")
        self.store.move_conversation(self.cid, project)
        source = self.store.new_conversation("Exact case", project)
        foreign = self.store.new_conversation("Private other project", other)
        self.turn(source, "Investigate DEMO-111 and PR #17")
        self.turn(foreign, "DEMO-111: unrelated private context never-recall-from-b")
        save_record(self.store, {"key": "DEMO-111", "value": "Verified old observation", "group_id": project})
        for i in range(8):
            save_record(self.store, {"key": "Generic " + str(i), "value": "DEMO-1110 investigation", "group_id": project})
        text = relevant(self.store, self.cid, "Review DEMO-111")
        self.assertIn("Verified old observation", text)
        self.assertNotIn("never-recall-from-b", text)
        self.assertNotIn(foreign, text)
        self.assertLessEqual(len(text), 6080)

    def test_disabled_module_preserves_legacy_search_and_saved_rows(self):
        save_record(self.store, {"key": "GPU", "value": "Validation reference"})
        before = self.store.rows("SELECT * FROM knowledge")
        with patch.dict("os.environ", {"AIMATE_RETRIEVAL_RANKING_ENABLED": "0"}):
            result = recall(self.store, self.cid, "search_knowledge", {"query": "GPU"})
            self.assertEqual(result["records"][0]["key"], "GPU")
            self.assertNotIn("match_basis", result["records"][0])
        self.assertEqual(before, self.store.rows("SELECT * FROM knowledge"))

    def test_separate_account_store_and_private_context_are_not_mixed(self):
        second = tempfile.TemporaryDirectory()
        other = Store(second.name)
        try:
            other.save_config({"ai": {}})
            other_id = other.new_conversation()
            self.turn(self.cid, "UNIQUE-44 owner-only content")
            self.assertEqual(recall(other, other_id, "search_knowledge", {"query": "UNIQUE-44"})["chats"], [])
            self.store.save_config({"_private": True, "ai": {}})
            self.assertEqual(relevant(self.store, self.cid, "UNIQUE-44"), "")
        finally:
            other.db.close()
            second.cleanup()
