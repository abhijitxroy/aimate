import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch
from tools.run_test_suite import category, partition


class SuiteTests(unittest.TestCase):
    def test_suite_boundaries_are_explicit_and_new_tests_are_not_dropped(self):
        self.assertEqual(category("test_validation.ValidationTests.test_x"), "unit")
        self.assertEqual(category("test_app.WorkflowTests.test_x"), "integration")
        self.assertEqual(category("test_app.QueryTests.test_x"), "unit")
        self.assertEqual(category("test_browser_regression.BrowserRegressionTests.test_x"), "regression")
        self.assertEqual(category("test_new_feature.NewTests.test_x"), "integration")
        with self.assertRaises(ValueError):
            category("unittest.loader._FailedTest.test_x")

    def test_partition_runs_each_discovered_case_once_and_rejects_duplicates(self):
        class Case:
            def __init__(self, ident): self.ident = ident
            def id(self): return self.ident
        cases = [Case("test_validation.ValidationTests.test_x"),
                 Case("test_app.WorkflowTests.test_x"),
                 Case("test_browser_regression.BrowserRegressionTests.test_x")]
        groups = partition(cases)
        self.assertEqual(sum(map(len, groups.values())), len(cases))
        self.assertEqual([len(groups[k]) for k in ("unit", "integration", "regression")], [1, 1, 1])
        with self.assertRaises(ValueError):
            partition(cases + cases[:1])

    def test_flaky_check_stays_failed_after_later_successful_attempts(self):
        from tools import run_test_suite as runner
        case = SimpleNamespace(id=lambda: "test_browser_regression.Case.test_x")
        results = [SimpleNamespace(wasSuccessful=lambda value=value: value, testsRun=1,
                   failures=[] if value else [(case, "failed")], errors=[], skipped=[])
                   for value in (False, True, True)]
        with patch.dict(os.environ), patch.object(runner, "discover", return_value={
                "unit": [], "integration": [], "regression": [case]}), \
                patch.object(runner, "FLAKY_METHODS", {"test_x"}), \
                patch.object(runner.sys, "argv", ["runner", "flaky", "--repeat", "3"]), \
                patch.object(runner.unittest.defaultTestLoader, "loadTestsFromName", return_value=unittest.TestSuite()), \
                patch.object(runner.unittest.TextTestRunner, "run", side_effect=results) as execute:
            self.assertEqual(runner.main(), 1)
            self.assertEqual(execute.call_count, 3)
