# AiMate TODO audit — 24 November 2026

Scope: running restored app at C:/Users/abhijit4/AiMate. Audit only; no product features changed.
Evidence: source inspection plus 197 Python tests and 9 JavaScript Markdown/syntax tests passed.
Full means implemented with relevant automated coverage or directly inspectable UI wiring. It does not mean every interaction has been browser-tested today. Partial includes implementation gaps and reported bugs whose UI fix has not been verified. Not touched means no dedicated implementation was found.
TODO.md is outdated: many implemented basics remain unchecked; its later upgrade phases are still planned.

P0 = correctness/security blockers; P1 = reliability and efficiency; P2 = existing everyday features; P3 = new enhancements.

| Priority / work | Your item | Status | What exists / what remains |
|---|---|---|---|
| P0 · AI | Auto routing for debug/analysis, manual override; always-Haiku complaint | Full | Completed and verified locally and in Linux/Windows/browser CI. https://github.com/abhijitxroy/aimate/actions/runs/45411134828 |
| P0 · Analysis | Comprehensive large-file/PR reviews | Full | Pinned paging, PR merge-base coverage and encrypted restart checkpoints verified; explicit limits documented. https://github.com/abhijitxroy/aimate/actions/runs/45415024500 |
| P0 · Memory | Restart continuity, carry previous knowledge, global project context, hold context until asked | Full | Encrypted briefs, scoped project recall, full saved-text paging and restart continuity verified. https://github.com/abhijitxroy/aimate/actions/runs/45422422473 |
| P0 · Security | Data safety for chats, diary, tasks, secrets and configuration | Full | SQLCipher chats, Diary, tasks and search; protected password; Windows DPAPI key. Migration preserved every saved-record count and verified protected credentials. Interrupted migration, encrypted restore and Linux/Windows/browser checks passed. CI: https://github.com/abhijitxroy/aimate/actions/runs/45428297613 |
| P0 · Privacy | Ultra privacy for tokens/passwords | Full | Full database encryption plus session vault reauthentication, 5-minute expiry, Lock now/tab-hide locking, per-entry AI opt-in and live per-read lock checks. Windows/Linux/browser workflow passed: https://github.com/abhijitxroy/aimate/actions/runs/45431479032 |
| P0 · Access | Further role/access improvements | Full | Server roles and isolated accounts plus live session, expiry, revocation and role-change checks throughout model/tool/HTTP requests; resource cleanup verified. Enterprise SSO and cross-account project sharing remain optional future integrations. CI passed: https://github.com/abhijitxroy/aimate/actions/runs/45437361523 |
| P0 · UI bug | To-do Show more not working | Full | Completed and verified locally and in Linux/Windows/browser CI. https://github.com/abhijitxroy/aimate/actions/runs/45411134828 |
| P1 · Speed | Performance improvement | Full | Independent read rounds run at concurrency 4 with ordered results, single-flight duplicate reuse, cancellation and sequential writes. Windows TLS initialization moved off the event loop. Offline benchmark measured 3.98x scheduling speedup and 96.31% repeated-evidence reduction; actual network latency varies. Windows/Linux/browser CI passed: https://github.com/abhijitxroy/aimate/actions/runs/45439006885 |
| P1 · Efficiency | Token optimization | Full | Historical evidence compacted with full saved-record paging; encrypted immutable GitHub snapshots expire after five minutes, invalidate on scope/token rotation and disclose verification time. Mutable sources and fresh/private requests bypass snapshots. CI: https://github.com/abhijitxroy/aimate/actions/runs/45445074986 |
| P1 · Usage | Bill details; day/model usage dashboard | Partial | Token ledger, day/model totals, charts/tables, CSV export and editable price estimates exist. Not provider invoices; connection checks and calls without usage reports are excluded. No provider billing reconciliation or budget enforcement. |
| P1 · Attachments | Files and pasted screenshots | Partial | Image paste/drop/cards, text/code/log files and PDF text extraction exist. Not every file type: binary documents/ZIPs unsupported; no scanned-PDF OCR. |
| P1 · Validation | Attachment size/formats; huge paste becomes attachment | Partial | Six attachments / four images; text files up to 1 MB; PDFs up to 4 MB / 80 pages; combined text limit. Frontend image compression and backend validation exist. Huge text is not automatically converted to an attachment. |
| P1 · Concurrency | Multiple asks in parallel | Partial | Backend concurrent workspace streams have isolation tests. Frontend has one global busy/controller and blocks another ask while running; tool calls are sequential. |
| P1 · Code | Modular code and useful logging | Partial | Separate storage, connectors, routing, memory, access and attachment modules; server logs and audit exist. main.py and app.js remain large; structured tracing/performance telemetry is planned. |
| P1 · GitHub | On 404, ask to add repository if appropriate | Partial | Repo-add proposal validates access before confirmation; scope/auth errors have hints. No deterministic 404-to-add flow. A 404 can also mean nonexistent or inaccessible data. |
| P1 · Files | Validate/extract/search/analyse ZIP | Not touched | No ZIP ingestion or extraction-safety implementation found. |
| P1 · Maintenance | Cleanup unused files with dependency checks | Not touched | Chat/record deletion exists; no dependency-aware file cleanup workflow. |
| P2 · Access | Developer/end-user, view and reviewed execute modes | Full | Backend read/write rules, administrator-only actions/config controls, confirmed writes and account isolation tests. Personal notes/connection settings remain editable in read-only service roles. |
| P2 · Access | Admin/read-write-config; developer/read-write; viewer/read | Full | Four roles: admin, developer, viewer, reviewer. External service writes are restricted by role plus the global write switch and confirmation. |
| P2 · Login | Who are you? Reviewer / End-user choices | Full | Role picker, issued access credentials and secondary authenticator flow; production requires OTP, local dev bypass is loopback-only. |
| P2 · Vault | Password vault, optional AI access | Full | Encrypted entries, per-entry AI sharing off by default, admin UI and redacted stored outputs; tested. |
| P2 · Organization | Single chats, projects/modules/groups/subgroups | Full | Separate conversations and nested organization; creation/move/validation tests. Cross-chat reuse is Partial above. |
| P2 · Organization | Key/value personal records, pin/export/move chats | Full | My Diary records, pinning, Markdown/text export, copying and chat movement. |
| P2 · Organization | Move whole project/group with its contents | Full | Subtree move preserves chats, diary records and children within a workspace. Cross-account workspace transfer is not provided. |
| P2 · Validation | Maximum subgroup depth | Full | Eight levels; cycle, duplicate-name and move-depth validation with tests. |
| P2 · Diary | Separate visual key/value view | Full | My Diary cards/view and editor; persisted scoped records. |
| P2 · Tasks | To-do section | Full | Add/edit/delete/complete/filter/copy; multiline text preserved. Expansion issue is separately Partial. |
| P2 · Identity | At Your Service branding | Full | Login and sidebar branding use the requested text. |
| P2 · Usage UI | Burning-token emoji | Full | Compact Auto/token badge; expanded model/token details. |
| P2 · Feedback | Positive/negative, useful feedback form | Full | Rating, category, comment and restricted feedback log; saved-answer validation. |
| P2 · Conversations | First-message title and rename | Full | Automatic first-message title; persistent rename; edits preserve chat identity/group. |
| P2 · Icons | Topic emoji, default/custom emoji and monogram | Full | Topic defaults, searchable presets, pasted custom emoji and 1–3 character monogram. |
| P2 · Conversations | Archive chats | Full | Archive/unarchive, archived view and persistence tests. |
| P2 · Administration | Rename/restrict Action history | Full | Audit log inside Admin settings; visible to administrator/developer, denied to viewer/reviewer. |
| P2 · Rendering | Colourful code/JSON/YAML | Full | Theme-aware syntax highlighting and exact-text code copy; 9 rendering tests passed. |
| P2 · Help | FAQ | Full | Basic troubleshooting FAQ, quick guide and shortcuts exist. Larger searchable knowledge/support content would be additional scope. |
| P3 · Prompting | Reusable favourite words/prompts | Not touched | My Diary can store text manually; no dedicated prompt-snippet library/insertion UI. |
| P3 · Analysis | Analysis templates and skills | Partial | Response format guidance and structured Markdown/components exist. No reusable analysis-template/skill registry or selected template workflow. |
| P3 · Tasks | To-do type column | Not touched | Current task fields: ID, title, completed, created, updated. No type/category column. |
| P3 · Icons | Change monogram colour | Not touched | Colour follows theme/CSS; no per-icon colour picker/storage. |
| P3 · Composer | B/U/I, colour, indentation, tables, panels, etc. | Not touched | Composer is a plain textarea; rendered answers support Markdown. No rich-text authoring toolbar. |
| P3 · Service | Another level of user assistance | Not touched | Recommendations below; no dedicated new service layer implemented. |

Recommended order:
1. Verify Auto switches models on a real debugging query; reproduce To-do expansion.
2. Add durable project summaries and chunked file/PR readers with explicit coverage tracking.
3. Benchmark latency/tokens; introduce bounded concurrent reads and evidence caching with freshness.
4. Complete database encryption, credential locking/recovery and role-isolation checks.
5. Complete attachment/ZIP handling, parallel asks, billing coverage and structured diagnostics.
6. Add prompt snippets, analysis templates/skills, task types, monogram colour and rich composer.

Potential next-level services: investigation workspace linking Jira → PR → build with evidence coverage; reusable review/runbook templates; stale-source and missing-access notices; resumable investigation checkpoints; cost/budget alerts. These are suggestions, not implementations.

Key evidence: app/model_routing.py, app/memory.py, app/store.py, app/agent.py, app/connectors.py, app/attachments.py, app/access.py, app/vault.py, app/device_key.py, app/usage.py, app/main.py, app/static/app.js, app/static/index.html, tests/test_model_routing.py, tests/test_personal_workspaces.py, tests/test_workspace_memory_usage.py, tests/test_performance_device_key.py and tests/test_todos.py.
