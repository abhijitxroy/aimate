# Local evidence

Desktop owner: **Connections & settings → Admin → Local evidence**.
Connect a repository or evidence folder with a short alias and its absolute
path. Ask AiMate to read `report.md`, verify `manifest.json`, inspect the working
tree or compare a Git baseline. It should use these reads before asking you to
paste evidence. Selected content is sent to the configured model when requested.

The optional `inspect_local_source` tool supports:

| Operation | Result |
|---|---|
| list | Connected aliases or a paged folder listing |
| read/search | UTF-8 evidence, paged text and original-byte SHA-256 |
| hash | SHA-256 of the current file bytes, including binary files |
| git_status | Current branch and working-tree file status |
| git_diff | Staged/unstaged changes against HEAD or a specified baseline |
| git_show | File at a specified Git ref |
| verify_manifest | Compare current bytes against `{ "files": [{ "path": "report.md", "sha256": "…" }] }` |
| inventory_summary | Deterministic row/group and duplicate-record counts from a preserved JSON array or `builds` array, with file SHA-256 |

Only explicitly selected local folders are readable. Credential paths, app data,
symlinks/junctions and directory escapes are excluded. Git runs fixed read-only
commands with external diff/text conversion, fsmonitor and submodule processing
disabled; it cannot run arbitrary commands, hooks, edits, commits or pushes.
Git operations require the actual repository root. Untracked file contents can
be read separately. Git output is captured per turn for stable paging.

Files/Git output are bounded to 8 MB, with 8,000-character text pages; Git has a
15-second timeout. Folder lists page 100 names. Manifest verification is bounded
to 100 files and a 32 MB read budget, with unverified entries reported.
Local timestamps/hashes describe current observed evidence, not a historical
inventory that was never retained. A matching hash does not certify a conclusion.
Inventory counts scan the whole supported file (up to 100,000 rows); they describe
rows and exact duplicate records, not assumed unique build identities. Missing
group fields and grouped rows beyond the display limit remain explicit.

Connections are stored in encrypted settings and preserved by the existing
encrypted full backup. General connection updates cannot add/replace local
roots. On a new laptop, reconnect folders whose paths changed; the backup does
not bundle external folders. Private chats keep their normal session lifetime.

The feature is desktop-owner-only and unavailable to public/showcase deployment
and shared-account roles. It is independent of the remote write switch.
Disable with `AIMATE_LOCAL_EVIDENCE_ENABLED=0`. Folder removal/revoked access
invalidates existing reads. It does not bypass source permissions or expose
the entire drive.
