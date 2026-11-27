import os
import tempfile
import unittest
from unittest.mock import patch

from test_app import Store, fixture_config
from app.answer_labels import instruction as label_instruction
from app.analysis_styles import instruction


class LabelPolicyTests(unittest.TestCase):
    def test_guidance_is_contextual_and_never_forces_all_labels_or_unverified_removal(self):
        for query in ("Review the implementation", "Classify these findings", "Improve this design"):
            policy=label_instruction(query,"auto")
            self.assertIn("[!KEEP]",policy)
            self.assertIn("Do not force all categories",policy)
            self.assertIn("unverified suspicion",policy)
            self.assertIn("yes/no/brief",policy)
        for query in ("Hello", "What is your name?", "Find this link"):
            self.assertEqual(label_instruction(query,"auto"),"")
        self.assertEqual(label_instruction("Review this","plain"),"")
        self.assertEqual(label_instruction("Review this","custom-template"),"")
        status=label_instruction("Summarize the delivered work and test status","auto")
        self.assertIn("[!SUCCESS]",status)
        self.assertIn("Distinguish earlier tests from fresh validation",status)
        self.assertIn("must not imply tests, pushes, writes",status)

    def test_attachment_words_do_not_trigger_visual_guidance(self):
        self.assertEqual(label_instruction(
            "Hello\n\nUntrusted attachment manifest: Review and classify","auto"),"")

    def test_disabled_labels_keep_original_review_style(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            try:
                cfg=fixture_config()
                self.assertIn("[!KEEP]",instruction(store,"Review this","review",cfg))
                with patch.dict(os.environ,{"AIMATE_ANSWER_LABELS_ENABLED":"0"}):
                    policy=instruction(store,"Review this","review",cfg)
                    self.assertIn("Review format:",policy)
                    self.assertNotIn("[!KEEP]",policy)
            finally:
                store.db.close()
