# AiMate work plan

Complete and verify one step before starting the next.

1. **Model selection — implemented** — Auto classifies routine versus debugging/analysis requests using AI. Standard and Analysis override it per question. Use only configured models from the current provider; show the selected model and include routing tokens in usage. Verified with offline provider mocks and browser checks; real Analysis access depends on the model configured by the operator.
2. **Performance** — measure response latency and service calls; improve the slowest paths with bounded parallel reads and appropriate caching.
3. **Token efficiency** — measure repeated context and tool output; reduce redundant input while preserving evidence and conversation continuity.
4. **Billing** — per-answer/per-model usage and estimated cost, with explicit pricing dates and a distinction between estimates and provider invoices.
5. **Credential vault** — encrypted credentials, masked UI, replacement/revocation controls and secret-free diagnostics. AI uses connector credentials without receiving raw secrets.
6. **Ultra privacy** — document data leaving the app; minimize retention, add local vault unlock/locking, and support deletion/export controls. Never promise that cloud inference is offline.
7. **Roles and execution** — define developer and end-user experiences, view-only permissions and reviewed execution. Enforce permissions in the backend, including existing sessions.

## Step 1 acceptance

- Existing settings continue using the working Standard model.
- Auto selects only Standard or the optional Analysis model, using a small tool-free classification request.
- Manual choice bypasses classification. An unset Analysis model produces an actionable error.
- Routing failures use Standard with a visible notice; model invocation failures are reported without a hidden retry using another model.
- Routing has no write tools and receives bounded, secret-scrubbed conversational text.
- Usage includes the classifier and exposes per-model totals.
- Model access checks test both configured models and report partial access.
- Verify with offline provider mocks and the UI before shipping.
