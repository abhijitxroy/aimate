# Final PR review

Normal **Review** uses one model. **Final PR review** uses the panel saved in
your own workspace, then asks its lead model to reconcile the independent reports.
Configure it once; later reviews reuse it until you change Settings.

1. Save an AI connection in **Connections & settings → AI model**.
2. Open **Final PR review panel**. Save that connection as a named profile,
   select its model and mark whether it may handle Organization/Intel or
   Non-Intel data. Keys stay in encrypted storage; they do not go into chat.
3. **Check access** explicitly invokes that model with a tiny test prompt.
   Catalog presence alone does not establish access. Repeat for the connections
   and models you want. Switching the active AI connection preserves these profiles.
4. Select two to six distinct models and a lead, then **Save panel**.
   Latest Claude Opus is suggested when you have saved and checked it.
5. Choose **Final PR review** in the askbar Style dropdown. Include one full PR URL.
   Ambiguous/missing targets cause a question before source fetching.

The panel belongs to the signed-in user's workspace and survives restart. Another
user cannot read or replace it. Changing a saved credential requires refreshing
the affected profile and checking it again. Removing a profile invalidates a panel
that selected it; AiMate will not silently substitute another model.

## Evidence and limits

AiMate reads the changed-file manifest and the complete required head/merge-base
file versions once. Every model receives the same SHA/hash-pinned packet.
Independent reviewers run two at a time; the lead receives their valid reports and
the original packet. Exact file/commit/line/quote references must match that packet.
Reports, disagreements, gaps and the packet are saved with the encrypted chat.
Temporary chats keep this material in memory. Expand **Independent reviewers** to
read individual reports after completion or reopening.

**Lead comparison → finding provenance** shows which cited claims were retained,
omitted, matched only by location, or added by the lead. Exact duplicate reports
do not inflate these counts. Different severities remain visible. Matching a
location does not establish that two descriptions refer to the same defect;
omission does not prove a concern false. Failed reviewers and an unfinished lead
stay explicit. The comparison and frozen evidence survive reopening without
fetching or invoking models again. Disable only this comparison module with
`AIMATE_FINAL_COMPARISON_ENABLED=0`; the saved panel remains usable.

The current packet limit is 180,000 serialized source characters, eighty changed
files and one hundred source versions. Binary/unreadable files and an incomplete
manifest stop collection before model calls. Exceeding a limit reports the actual
reason; no silently truncated packet is reviewed. Unchanged dependencies, external
design documents, tests and runtime execution are explicitly outside this first
source-review mode. Findings are review assessments, not automatic approval or a
guarantee of correctness. Source citations and model agreement do not prove a claim.

The PR head/target base are checked again after independent review and lead
comparison. Changed heads, changed settings, revoked profiles/access, or Stop
cannot produce a saved completed final review. A failed participant or lead leaves
the report incomplete. A source-review report still lists unexecuted test/runtime
checks; it is never presented as complete integration validation.

## Providers, privacy and usage

Profiles support the existing Claude/Bedrock, GPT via Bedrock, OpenCode gateway,
Gemini/Vertex, personal Anthropic and local signed-in ChatGPT adapters. These use
inference APIs, not terminal agents or arbitrary CLI execution. OpenCode/Codex and
geographic routes do not count as extra votes for the same underlying model.
Local LLM is excluded from this final-review mode.

Personal ChatGPT/Anthropic profiles cannot be marked for Intel data. Intel targets
and internal references require organization profiles. The profile label is a
user-selected data permission, not a declaration that a provider is company-approved:
only mark an organization route when your organization permits it.
Credential JSON and tokens are encrypted and omitted from public profile responses.

Each reviewer invocation and lead comparison is recorded in Usage & billing.
Access checks also count. Provider-reported usage is retained even if its resulting
JSON/citations are rejected. Cancelled calls may have unavailable provider usage;
they remain in the call ledger. Premium models cost more; selecting Final PR review
explicitly starts the saved multi-model panel, without repeated selection prompts.

Disable the independent module with `AIMATE_FINAL_REVIEW_ENABLED=0`; normal reviews,
chat and saved data remain usable. Existing portable encrypted backup includes its
tables and saved chat metadata.
