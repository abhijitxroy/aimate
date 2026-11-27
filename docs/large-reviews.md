# Large source reviews

AiMate can read GitHub files by line range with an exact commit SHA. A long line
continues at `next_line` / `next_column`; no middle section is silently omitted.
The PR manifest lists added, removed, modified and renamed sources, with head
and base commits. Both versions of changed files are required for read coverage.

`review_coverage` separates complete source reads from code correctness and
test results. Missing source versions and incomplete manifest pages remain
visible. The assistant must state coverage gaps before giving a verdict.

Review checkpoints are encrypted, scoped to a conversation and GitHub credential
configuration, and retained across restarts. They contain ranges and source IDs,
not file bodies. A resumed review must refresh PR metadata. A changed head resets
the derived coverage. Editing/deleting a chat clears its checkpoint. Private chats
keep review state only for the active turn.
Use `reset=true` on manifest page 1 for a new independent review at the same head.

Saved range pairs can be JSON lists while new reads use tuples. Their numeric
bounds are now sorted consistently, so rereading or continuing after restart
does not fail with a mixed-list/tuple TypeError. Existing encrypted checkpoints
remain usable without clearing the review or starting a new chat.

Limits remain explicit: GitHub's 3,000-file PR API cap, a 1.4 MB individual
contents-response limit, 100 cached files / approximately 8 MB per turn, and the
model's tool-round/context limits. These boundaries produce incomplete coverage,
never an invented complete review. Continue the same saved chat for larger work.
