# Test workflows

| Workflow | Scope | Trigger |
|---|---|---|
| Unit tests | Isolated validation/routing/helper tests plus JavaScript rendering/security/Pages preview | Push, PR, manual |
| Integration tests | Backend API, encrypted storage, permissions, persistence and mocked-provider flows; synthetic read benchmark | Push, PR, manual |
| Browser regression | All real-browser and HTTP regressions against an isolated fixture backend | Push, PR, manual |
| Flaky checks | Six critical browser checks, repeated three times with fresh fixtures | Push, PR, manual |
| Quality checks | Focused Python lint, every JavaScript source's syntax, generated Pages interface consistency | Push, PR, manual |
| Security checks | Known runtime/test dependency vulnerabilities and committed-secret scanning | Push, PR, manual |

`python tools/run_test_suite.py unit --inventory` lists counts across the three non-overlapping primary Python suites. Every discovered Python test belongs to exactly one primary suite. New backend tests default to integration until classified; discovery errors and duplicate cases fail instead of being skipped.

Flaky checks are additional repetitions, not retries that turn failures green. Any failed attempt fails the workflow even if a later attempt passes. `flaky-report.json` records each attempt and is uploaded as an artifact.

Run any suite locally using `python tools/run_test_suite.py <unit|integration|regression|flaky>`. Browser suites require `requirements-dev.txt` and installed Playwright Chromium. External AI/services are mocked; these workflows do not prove live account permissions, actual billing or live model behavior.

All four test workflows plus Quality and Security must pass before a batch is reported CI-verified. Quality checks do not repeat the test suites or enforce cosmetic formatting. Run them locally with `ruff check --select E9,F63,F7,F82 app tools tests` and `python tools/quality_checks.py`.

Security runs `pip-audit` against runtime and test requirements, fails on known findings and saves a JSON report. Gitleaks scans committed history; real tokens must never be committed. A passing scan is bounded evidence, not a guarantee that all vulnerabilities or secrets can be detected. No blanket fixture exemptions or vulnerability ignores are enabled.

Existing historical failed runs remain as GitHub history. The older `Tests` workflow is still listed while `main` retains the older YAML; the feature branch has separate files. Repository-required checks were not changed. Build smoke remains a recorded follow-up.
