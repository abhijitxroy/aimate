# Selected project knowledge

In **Connections → Admin → Local evidence**, expand **Knowledge index**.
Select an already connected repository and enter explicit Markdown paths.
Indexing reads committed files at one fixed Git HEAD and does not alter the repo,
scan every file, invoke AI or change credentials.

The owner-only index supports up to 20 files per import, 100 stored documents and
3 MB total; each document is at most 64 KB. Larger sources remain readable through
the existing source paging tools. Stored text is encrypted with the workspace
Fernet key in `.data/knowledge-index.fernet`. The portable encrypted backup includes
this file; a fresh backup is still needed to migrate newly indexed records.

Search ranks exact identifiers, titles/aliases and text. Retired/obsolete records
are excluded from normal suggestions. Reads return pinned commit, content hash,
declared status/date, indexed time, current HEAD and changed-source indication.
Each turn tracks page ranges, so jumping to the final page is not a full read.
Reindexing gives a changed commit a new ID; it cannot silently replace a requested
old version. Full document text remains readable from the index panel.

Records are historical leads, not proof of recurrence. Source-declared “active”
or “reviewed” does not mean AiMate verified the current environment or outcome.
Inspect current evidence and contradictions before a conclusion.

The index is available only to the desktop owner with connected local roots.
Private chats, grants, remote clients and public deployments cannot query it.
Disconnected/changed root mappings invalidate access. No content goes to a new
embedding provider. Existing configured AI sees only the excerpts/pages it
explicitly requests through knowledge tools.

Set `AIMATE_KNOWLEDGE_INDEX_ENABLED=0` to disable this module independently.
Remote knowledge-repository ingestion, structured case promotion and matched Odin
quality evaluation remain separate tasks.
