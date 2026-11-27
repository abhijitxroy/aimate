"""Comparison counts describe provenance, not correctness or model consensus."""
import copy
import unittest
from unittest.mock import patch

from app.final_review_comparison import compare, unique


def finding(claim="Zero divisor", severity="P2", line=2):
    return {"path": "code.py", "commit": "a" * 40, "line": line,
            "quote": "return 10 / value", "claim": claim, "severity": severity,
            "scenario": "Input is zero.", "suggestion": "Check the divisor."}


def report(*findings):
    return {"summary": "Source review", "findings": list(findings), "gaps": []}


class ComparisonTests(unittest.TestCase):
    def test_duplicates_do_not_inflate_provenance_and_severity_disagreement_is_retained(self):
        first = report(finding(), finding())
        second = report(finding("Zero divisor", "P1"))
        original = copy.deepcopy(first)
        result = compare(report(finding()), [
            {"id": "one", "name": "First", "report": first},
            {"id": "two", "name": "Second", "report": second}], True)
        self.assertEqual(result["counts"]["retained"], 1)
        self.assertEqual(result["counts"]["severity_disagreements"], 1)
        self.assertEqual(len(result["entries"][0]["reviewers"]), 2)
        self.assertEqual(result["entries"][0]["lead_severity"], "P2")
        self.assertEqual(first, original)
        self.assertEqual(len(unique(first)["findings"]), 1)

    def test_different_claim_at_same_location_is_not_assumed_equivalent(self):
        result = compare(report(finding("Different condition")), [
            {"id": "one", "name": "First", "report": report(finding())}], True)
        self.assertEqual(result["counts"]["location_only"], 1)
        self.assertEqual(result["counts"]["retained"], 0)
        self.assertIsNone(result["entries"][0]["lead_severity"])
        self.assertIn("different failures", result["note"])

    def test_case_sensitive_code_identifiers_in_claims_are_not_merged(self):
        result = compare(report(finding("Foo accepts zero")), [
            {"id": "one", "name": "First", "report": report(finding("foo accepts zero"))}], True)
        self.assertEqual(result["counts"]["retained"], 0)
        self.assertEqual(result["counts"]["location_only"], 1)

    def test_omission_and_new_lead_finding_remain_distinct(self):
        result = compare(report(finding(line=5)), [
            {"id": "one", "name": "First", "report": report(finding())}], True)
        self.assertEqual(result["counts"]["omitted"], 1)
        self.assertEqual(result["counts"]["lead_only"], 1)
        self.assertIn("not a rejection", result["note"])

    def test_failed_lead_does_not_reject_findings_or_claim_consensus(self):
        result = compare(report(), [
            {"id": "one", "name": "First", "report": report(finding())},
            {"id": "two", "name": "Second", "error": "No completed report"}], False)
        self.assertEqual(result["counts"]["unresolved"], 1)
        self.assertEqual(result["counts"]["omitted"], 0)
        self.assertEqual(result["incomplete_reviewers"], [{"id": "two", "name": "Second"}])

    def test_module_disabled_preserves_reports_and_normal_panel_fallback(self):
        original = report(finding(), finding())
        with patch.dict("os.environ", {"AIMATE_FINAL_COMPARISON_ENABLED": "0"}):
            self.assertEqual(unique(original), original)
            self.assertIsNone(compare(original, [], True))
