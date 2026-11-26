# What AiMate currently reuses

Checked against the current implementation on 26 November 2026.

| Data | Storage / reuse | Freshness rule |
|---|---|---|
| Saved chats and My Diary | Workspace database; exact-identifier and text ranking selects relevant excerpts | Past references, not current service status |
| Conversation context | Encrypted briefs retain questions, issue/PR identifiers and source URLs; project scope limits automatic recall | Separate chats remain separate; explicit references do not replay actions |
| Repeated GitHub reads | Encrypted `evidence_cache` snapshots for commit-specific metadata or file contents | Full 40-character commit only; five-minute expiry; at most 100 records, 64 KB per result |
| Reads inside one investigation | Bounded per-turn reuse and parallel scheduling | Errors are not cached; access/scope checks still apply |
| Selected Nexus runbooks | Encrypted `.data/knowledge-index.fernet`; committed Markdown only | Pinned commit/hash; author-declared status; current HEAD checked on read; retired notes excluded from suggestions |
| Credentials | Protected connection configuration and vault, separate from knowledge | Do not index or expose them as project knowledge |

The GitHub snapshot cache includes the connection configuration and request in its
key. “Recheck”, “refresh”, “latest”, “current”, “now” or “today” bypass it;
Private chats bypass persisted snapshots too. The returned snapshot includes its
verification time and a cached-reference label.

AiMate does **not** currently maintain Odin's domain-data mirror. Personal chat,
Diary and task tables are not a substitute for Jenkins build populations, Jira
association records or release metrics. SQ-07 tracks a scoped read-only project
data adapter. Structured reviewed cases, wider cache tiers and measured retrieval
quality remain SQ-05, SQ-09 and SQ-12.

The installed owner index was checked with three selected Nexus runbooks:
GPU detection, CI-build triage and an expired LKG-proxy password. GPU and
password-expiry searches returned the expected leading references; full paged
reads passed. These checks establish retrieval behaviour, not a proven cause
for a new failure or measured parity with Odin.
