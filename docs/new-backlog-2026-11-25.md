# New requests — 25 November 2026

The 22 requests are recorded individually in `new-todos-2026-11-25.json` with priority, type and honest status. The existing safety-lock task is reused. Separate workflow YAML and safety locks already have CI evidence; other features remain open.

Three additional workflow follow-ups are recorded: Quality checks, Security checks and Build smoke. The older `Tests` workflow remains visible while the default branch retains its previous configuration.

Work one item at a time: implementation → local checks → all four GitHub test workflows → record completion. The active askbar formatting fix comes first, then To-do priorities. Items needing speech/network/privacy decisions should stay open until those requirements are clear.

The reference Dashboard review's exact internal issue details are stored only in the local To-do entry. Repository/branch availability must be verified before that read-only review.

Restore/import the public plan without replacing existing task edits:

```powershell
.\.venv\Scripts\python.exe tools\import_audited_todos.py --audit docs\new-todos-2026-11-25.json
```

This imports tasks, not the full requested workspace-sharing package. Full structured export/import remains its own open feature.
