import asyncio
import json
import tempfile
import time
import unittest
from app.store import Store
from app.evidence_cache import EvidenceCache
from app.read_batch import read_evidence
from app.history_budget import compact


class TokenBudgetTests(unittest.TestCase):
    def test_compaction_preserves_call_ids_reasoning_and_full_saved_text(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                cid = store.new_conversation()
                output = "source evidence " * 1500
                messages = [{"role": "user", "content": "Review PR #1257."},
                    {"role": "assistant", "content": [{"type": "tool_use", "id": "read1", "name": "api_read", "input": {}}]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "read1", "content": output}]},
                    {"role": "assistant", "content": [{"type": "responses", "items": [
                        {"type": "reasoning", "encrypted_content": "exact-opaque-signature"},
                        {"type": "function_call_output", "call_id": "read2", "output": output}]}]}]
                store.save_turn(cid, messages)
                history = store.history(cid)
                self.assertLess(len(json.dumps(history)), len(json.dumps(messages)) / 3)
                self.assertIn("read_saved_turn", str(history))
                self.assertIn("exact-opaque-signature", str(history))
                self.assertEqual(history[2]["content"][0]["tool_use_id"], "read1")
                self.assertEqual(json.loads(store.rows("SELECT messages FROM turns")[0]["messages"]), messages)
            finally:
                store.db.close()

    def test_encrypted_cache_expiry_scope_rotation_freshness_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"github": {"url": "https://api.github.com", "token": "synthetic-one", "repos": ["team/repo"]}}
            args = {"service": "github", "path": "/repos/team/repo/commits/" + "a" * 40}
            store = Store(directory)
            cache = EvidenceCache(store, config, "Explain this commit")
            cache.put(args, {"source": "https://example.test/commit", "data": "private-evidence-marker"})
            self.assertNotIn("private-evidence-marker", str(store.rows("SELECT encrypted FROM evidence_cache")))
            self.assertTrue(cache.get(args)["snapshot"]["cached"])
            self.assertIsNone(EvidenceCache(store, config, "Recheck this commit now").get(args))
            changed = {"github": {**config["github"], "token": "synthetic-two"}}
            self.assertIsNone(EvidenceCache(store, changed, "Explain").get(args))
            self.assertIsNone(EvidenceCache(store, {**config, "_private": True}, "Explain").get(args))
            store.db.close()
            store = Store(directory)
            try:
                self.assertIsNotNone(EvidenceCache(store, config, "Explain").get(args))
                store.execute("UPDATE evidence_cache SET expires=?", (time.time() - 1,))
                self.assertIsNone(EvidenceCache(store, config, "Explain").get(args))
            finally:
                store.db.close()

    def test_mutable_sources_never_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                cache = EvidenceCache(store, {"github": {}}, "Explain")
                for service,path in [("github","/repos/team/repo/pulls/1"),("jira","/rest/api/2/issue/DEMO-1"),
                                     ("jenkins","/job/build/1/consoleText")]:
                    args = {"service":service,"path":path}
                    cache.put(args, {"source":"https://example.test","data":"mutable"})
                    self.assertIsNone(cache.get(args))
                self.assertEqual(store.rows("SELECT count(*) AS n FROM evidence_cache")[0]["n"], 0)
            finally:
                store.db.close()
