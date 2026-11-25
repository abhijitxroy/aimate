"""Non-overlapping Python suites; repeats expose flakes instead of hiding them."""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
UNIT_CLASSES = {
    "test_validation.ValidationTests", "test_app.QueryTests",
    "test_github_guidance.GuidanceTests", "test_ci_suites.SuiteTests",
    "test_build_smoke.SmokeTests",
}
UNIT_METHODS = {
    "test_model_routing.RoutingTests." + name for name in (
        "test_manual_selection_skips_classifier", "test_auto_obeys_ai_decision_and_retains_usage_on_bad_json",
        "test_unconfigured_auto_does_not_classify_and_manual_analysis_errors",
        "test_router_context_bounded_and_excludes_tool_results",
        "test_simple_bedrock_keeps_optional_analysis_id_and_saved_key")
} | {
    "test_read_batch.ReadBatchTests." + name for name in (
        "test_parallelism_is_bounded_and_results_keep_original_order",
        "test_duplicate_concurrent_reads_fetch_once_and_reuse_compact_evidence",
        "test_errors_remain_per_read_and_are_not_cached",
        "test_mixed_writes_and_invalid_namespaces_never_prefetch",
        "test_responses_arguments_and_cancellation_cleanup")
} | {"test_token_budget.TokenBudgetTests.test_large_image_turn_keeps_the_user_question_when_history_is_compacted"}
FLAKY_METHODS = {
    "test_parallel_chats_keep_answers_and_stop_is_scoped_to_visible_chat",
    "test_old_chat_recall_after_reload_and_history_window",
    "test_edit_resend_keeps_chat_and_group",
    "test_tools_toggle_keeps_chat_and_composer_fixed_with_long_sidebar",
    "test_personal_record_locks_guard_updates_and_delete_and_reset_on_reopen",
    "test_screenshot_message_and_card_survive_reload_with_real_image_provider_blocks",
}


def flatten(suite):
    for entry in suite:
        if isinstance(entry, unittest.TestSuite):
            yield from flatten(entry)
        else:
            yield entry


def category(ident):
    if ident.startswith("unittest.loader._FailedTest."):
        raise ValueError("Test discovery failed: " + ident)
    if ident.startswith("test_browser_regression."):
        return "regression"
    cls = ident.rsplit(".", 1)[0]
    if cls in UNIT_CLASSES or ident in UNIT_METHODS or (
            cls == "test_bedrock.BedrockTests" and not ident.endswith(".test_secrets_preserved_removed_and_never_exposed")):
        return "unit"
    # New/uncategorized backend tests are never omitted: integration is conservative.
    return "integration"


def partition(tests):
    groups = {"unit": [], "integration": [], "regression": []}
    seen = set()
    for test in tests:
        ident = test.id()
        if ident in seen:
            raise ValueError("Duplicate discovered test: " + ident)
        seen.add(ident)
        groups[category(ident)].append(test)
    return groups


def discover():
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    return partition(list(flatten(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py"))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=("unit", "integration", "regression", "flaky"))
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 2 <= args.repeat <= 10:
        parser.error("Flaky repetitions must be between 2 and 10.")
    if args.suite in {"regression", "flaky"}:
        os.environ["AIMATE_BROWSER_TESTS"] = "1"
    groups = discover()
    inventory = {key: len(tests) for key, tests in groups.items()}
    print("Discovered suite inventory:", json.dumps(inventory), flush=True)
    if args.inventory:
        return 0
    selected = groups["regression" if args.suite == "flaky" else args.suite]
    if args.suite == "flaky":
        selected = [test for test in selected if test.id().rsplit(".", 1)[1] in FLAKY_METHODS]
        missing = FLAKY_METHODS - {test.id().rsplit(".", 1)[1] for test in selected}
        if missing:
            raise ValueError("Missing repeated regression tests: " + ", ".join(sorted(missing)))
    if not selected:
        raise ValueError("The selected suite is empty.")
    report = {"suite": args.suite, "inventory": inventory, "runs": []}
    repeats = args.repeat if args.suite == "flaky" else 1
    passed = True
    for attempt in range(1, repeats + 1):
        # unittest consumes suites; load fresh cases for every reliability attempt.
        cases = [unittest.defaultTestLoader.loadTestsFromName(test.id()) for test in selected]
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(cases))
        passed = result.wasSuccessful() and passed
        report["runs"].append({"attempt": attempt, "tests": result.testsRun,
            "failures": [test.id() for test, _ in result.failures],
            "errors": [test.id() for test, _ in result.errors], "skipped": len(result.skipped),
            "passed": result.wasSuccessful()})
    report["passed"] = passed
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
