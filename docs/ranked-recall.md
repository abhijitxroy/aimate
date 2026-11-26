# Ranked saved references

Saved chat and Diary recall now prefer exact Jira keys, PR numbers and full commit
hashes before generic words or recency. `PR1257`, `PR #1257` and a PR URL identify
the same pull-request number; `1257` never prefix-matches `12570`.

Search selects exact-identifier candidates first, then ranks a bounded full-text
shortlist. Diary key matches receive additional weight. Excerpts focus on the
matched identifier even in the middle of a long record and expose offsets;
existing read tools still page the full original record. Ranking changes no
saved text and adds no database schema, external calls or embeddings.

Automatic context retains the current project-family scope and existing private
chat exclusions. Explicit saved-record search remains within the signed-in
account's workspace, as before. All recalled text is untrusted past reference;
ranking does not establish current facts, root cause or independent accuracy.

Disable this module with `AIMATE_RETRIEVAL_RANKING_ENABLED=0` to retain legacy
recall. Identifier fixtures measure missed targets and misleading lookalikes.
Odin parity, Nexus indexing, structured cases, synonym/semantic retrieval and
representative live model quality remain separate validation/work items.
