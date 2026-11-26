"""Local compaction preserves current intent, safety policy and call/result pairing."""
import copy
import json
import os
import unittest
from unittest.mock import patch

from app.local_prompt_budget import MAX_PROMPT_BYTES, fit, size
from app.ollama_local import DEFAULT_MODEL, payload


class LocalPromptBudgetTests(unittest.TestCase):
    def args(self):
        return {"model": DEFAULT_MODEL, "system": "Never disclose credentials; writes need confirmation.",
                "messages": [{"role": "user", "content": "Please review PR 7 completely."}],
                "tools": [{"name": "read", "description": "Read a permitted source.",
                           "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}]}

    def test_old_history_is_compacted_without_mutating_the_current_question_or_policy(self):
        args = self.args()
        args["messages"] = [{"role": "user", "content": "History " + "旧" * 40000},
                            {"role": "assistant", "content": "Earlier finding."}, *args["messages"]]
        before = copy.deepcopy(args)
        body = payload(args, True)
        self.assertLessEqual(size(body), MAX_PROMPT_BYTES)
        self.assertEqual(body["messages"][-1]["content"], before["messages"][-1]["content"])
        self.assertEqual(body["messages"][0]["content"], args["system"])
        self.assertEqual(body["tools"][0]["function"]["parameters"], args["tools"][0]["input_schema"])
        self.assertIn("omitted content was NOT reviewed", json.dumps(body, ensure_ascii=False))
        self.assertEqual(args, before)

    def test_latest_multi_tool_round_keeps_calls_and_results_and_marks_large_evidence(self):
        args = self.args()
        args["messages"] += [{"role": "assistant", "content": [
            {"type": "tool_use", "id": "one", "name": "read", "input": {"path": "one"}},
            {"type": "tool_use", "id": "two", "name": "read", "input": {"path": "two"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "one", "content": "FIRST " + "x" * 50000 + " LAST"},
                {"type": "tool_result", "tool_use_id": "two", "content": "SECOND " + "y" * 50000 + " END"}]}]
        before = copy.deepcopy(args)
        body = payload(args, False)
        self.assertLessEqual(size(body), MAX_PROMPT_BYTES)
        self.assertEqual(len(body["messages"][2]["tool_calls"]), 2)
        self.assertEqual([row["tool_name"] for row in body["messages"][3:]], ["read", "read"])
        for row, start, end in zip(body["messages"][3:], ("FIRST", "SECOND"), ("LAST", "END")):
            self.assertTrue(row["content"].startswith(start))
            self.assertTrue(row["content"].endswith(end))
            self.assertIn("NOT reviewed", row["content"])
        self.assertEqual(args, before)

    def test_old_tool_rounds_removed_together_without_orphaning_latest_round(self):
        args = self.args()
        for i in range(14):
            args["messages"] += [{"role": "assistant", "content": [
                {"type": "text", "text": "Readable prior step " + "a" * 8000},
                {"type": "tool_use", "id": str(i), "name": "read", "input": {"path": str(i)}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": str(i), "content": "b" * 8000}]}]
        body = payload(args, True)
        self.assertLessEqual(size(body), MAX_PROMPT_BYTES)
        self.assertEqual(body["messages"][1]["content"], args["messages"][0]["content"])
        self.assertEqual(body["messages"][-2]["tool_calls"][0]["function"]["arguments"]["path"], "13")
        self.assertEqual(body["messages"][-1]["role"], "tool")
        self.assertIn("Earlier local steps omitted", body["messages"][2]["content"])

    def test_disabled_compaction_never_silently_shrinks_prompt(self):
        args = self.args()
        args["messages"].insert(0, {"role": "assistant", "content": "x" * 70000})
        with patch.dict(os.environ, {"AIMATE_LOCAL_PROMPT_COMPACTION": "0"}), self.assertRaisesRegex(ValueError, "64 KB"):
            payload(args, True)

    def test_small_payload_and_utf8_excerpt_are_lossless_and_valid(self):
        args = self.args()
        body = payload(args, True)
        self.assertEqual(fit(body), body)
        self.assertIsNot(fit(body), body)
        args["messages"].insert(0, {"role": "assistant", "content": "😃" * 30000})
        body = payload(args, True)
        self.assertNotIn("\ufffd", json.dumps(body, ensure_ascii=False))
