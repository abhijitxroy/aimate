# Investigation quality: implementation order

This work targets independently verified engineering investigations. It does
not claim universal superiority over Odin. The inspected Dashboard checkout is
a feature branch; its pilot features are not assumed to be deployed.

Existing canonical To-dos retain their IDs and previous evidence. Detailed
acceptance requirements are recorded in `new-todos-2026-11-25.json` and
`new-requests-2026-11-26.json`. Private operational benchmark inputs stay local.

| Order | Priority | Task | Required result |
|---|---|---|---|
| 1 | P0 | SQ-08 + `investigation-budget-checkpoint` | Explicit incomplete status, saved paired evidence and safe continuation at request limits |
| 2 | P0 | SQ-02 + SQ-12 | Matched source snapshot, independently verified expected facts and quality measurements |
| 3 | P0 | `artifactory-connection` | Complete scoped artifact discovery and report-content reads |
| 4 | P0 | SQ-07 | Approved read-only CI/Jira data access with scope, freshness and population reconciliation |
| 5 | P0 | `packaging-dms-reconciliation` + SQ-08 | Deterministic eligibility/outcome counts; evidence gate prevents unsupported final verdicts |
| 6 | P1 | SQ-09 | Separate immutable/mutable cache tiers, expiry, access isolation and measurable reuse |
| 7 | P1 | SQ-05 / SQ-06 / SQ-13 | Reviewed Nexus incident cases, relevant retrieval and validated applicability |
| 8 | P1 | SQ-11 | Concise gist, category counts and expandable per-build evidence |

Do not wait for a blocked connector before implementing independent contracts,
synthetic fixtures, benchmark rules and output validation. Live adapter
completion still requires approved endpoint/schema/credentials and real checks.

## Reconciliation benchmark requirements

- Convert the specified local timezone explicitly; never silently assume UTC.
- Freeze the time window and collection snapshot. Enumerate all relevant
  package-creation builds, not only children of failed mirrored parent runs.
- Use actual packaging-stage results. A Jenkins FAILURE is only a candidate.
- Inspect report contents and applicable DMS code/version. Report existence
  alone does not prove eligibility or invocation.
- Check build-specific DMS and Jira outcomes. No recent ticket updates alone
  do not prove zero reuse.
- Separate confirmed, inferred and inconclusive cases. A sampled startup error
  cannot classify all uninspected builds; an incomplete artifact search cannot
  prove a report is missing.
- Deduplicate canonical build/target identities, reconcile category totals and
  preserve infrastructure exclusions and out-of-mirror cases.
- Cite exact source identities, timestamps, report hashes and inspected ranges.
  Score critical factual errors, fact coverage and citation support before
  latency, calls, tokens and cost.

## First implementation batch

`app/investigation_completion.py` classifies tool-budget, native output-limit
and empty-final-answer pauses. It saves an explicit checkpoint in existing
turn metadata; no database migration is required. Last-round pending tools are
paired with “not executed” results and never invoked. Temporary-chat transcripts
stay in session memory. The UI distinguishes incomplete output from a finished
answer and preserves the notice after reload.

Disable this module with `AIMATE_COMPLETION_CHECKPOINT_ENABLED=0`; authentication,
scope checks, proposal confirmation and existing request limits remain enabled.

This is a completion-status safeguard, not a complete factual evidence gate.
Provider transport errors/Responses incomplete events, automatic resumable
multi-batch work, deterministic domain reconciliation and measured Odin parity
remain open. Saved history still follows the existing context budget.
