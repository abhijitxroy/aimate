# Token efficiency

Historical tool results use short excerpts with the saved turn ID. Full records
remain encrypted and available through `read_saved_turn`; request/response IDs
and opaque provider reasoning are retained. Recent history is bounded at
60,000 characters, with durable project briefs supplying older context.

Verified immutable GitHub commit/file reads can reuse an encrypted snapshot
for five minutes, scoped to the exact saved GitHub connection and arguments.
Changed credentials or scope invalidate reuse. Mutable PRs, Jira and Jenkins
reads are always fresh. “Recheck”, “latest”, “current”, “now” and private chats
bypass persistent snapshots. Cache hits disclose their original verification
time and do not prove current remote access.
