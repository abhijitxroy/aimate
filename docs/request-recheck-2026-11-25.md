# Request recheck — 25 November 2026

This snapshot records the latest requests. The app To-do list remains the live
status source: 48 completed, 32 open. The larger platform roadmap is separate.

| Request | Status | Evidence / next step |
|---|---|---|
| Intel AI options | Partial | Claude Bedrock and GPT via Bedrock adapters exist. Saved GPT-6.2 Sol replies and a matching connection fingerprint prove actual Responses access. Gemini and additional gateways need non-secret endpoint/authentication/model instructions. Codex, Cowork and OpenCode are clients; their API gateway must be identified. |
| Attachment limits and clear errors | Implemented, automated tests passed | 20 MB upload default; separate PDF, extracted-text and ZIP expansion/ratio limits. Rejections name the actual limit. Actual model interpretation of every document type remains a separate open item. |
| Offline local model fallback | Open | Runtime/model and laptop capability details requested. Cloud failure must offer explicit consent; local inference and online connector access remain separate. |
| Cached context while offline | Partial | Scoped encrypted briefs/evidence already exist. Offline fallback must label stale evidence and avoid treating cache as current live facts. |
| Daily Jira-creation email to PDL | Awaiting setup | Need recipient, Jira scope, send time and approved delivery service. No email or schedule has been created. |
| Workspace/project/module info | Implemented, browser checks passed | Workspace keeps separate data/settings; Project organizes chats, including subprojects. Legacy kind values are preserved internally. |
| Chat/message timestamps | Implemented, browser checks passed | Compact message time and full hover timestamp; chat creation time on hover. |
| Ctrl+B/I/U on selected text | Implemented, browser checks passed | Editor shortcuts apply formatting and update the enabled button state without sending the message. |
| Project chat pins | Implemented, browser checks passed | Pins stay first in their own project, before subprojects. |
| Favorite messages | Implemented, backup/browser checks passed | Saved user/reply star pins; paged Favorites, Copy, original-chat links and Unpin. Pins live in encrypted turn metadata, preserve usage and survive portable restore. Private/incomplete messages are excluded. |
| Recents | Implemented, browser checks passed | Separate section below Projects with horizontal divider; three initial chats, five more per step, side-by-side controls and remembered whole-section collapse. |

Four non-duplicate tasks were added: AI connection options, local fallback, daily
Jira email and favorite messages. Existing tasks cover the remaining requests.

## Verified batches

- Import progress, initial chat identity and concurrency help: `19c9794`, all
  seven workflows passed. Local checks: 245 integration and 42 browser tests.
- Life, Brown & Gold and palette import: `27b4402`, all seven workflows passed.
  Import is optional, dark-palette JSON only, up to 4 KB, with schema/contrast checks.
  It accepts no CSS, scripts, URLs or external assets. Light imports remain unsupported.
- Message favorites: `c2a6355`, all seven workflows passed. Local checks:
  247 integration, 44 browser and nine encrypted backup/restore tests.

[Favorite-message CI](https://github.com/abhijitxroy/aimate/actions/runs/45575134840)

## Remaining choices and validation

The current GPT connection has no Analysis model configured. Auto therefore uses
Standard. A model/budget choice has been requested before changing that setup.
Remaining real-model, invoice, large-review, long-context and provider/network
performance checks remain open; fixture success is not a replacement for them.

No Dashboard/DMS changes, email sends, new paid inference or deployment were made.
Verified code and task records were copied to the local app and OneDrive migration
kit. Actual cloud sync and a new password-encrypted full backup are not asserted.
