# AiMate — next work on the new laptop

Current recheck on **26 November 2026**: the live To-do list contains
**77 completed and 42 open** tasks. The original audited app list has 31 completed
and 13 open records; the live total also includes later requests and legacy
user-added entries. Incomplete live validation remains open.
See [the latest request recheck](docs/request-recheck-2026-11-25.md),
[the original status table](docs/todo-audit-2026-11-24.md), and
[the app To-do export](docs/audited-todos.json).

The [new request backlog](docs/new-backlog-2026-11-25.md) records the 22 additional
requests and three CI follow-ups individually.

The highest-priority workstream is [search quality and knowledge reuse](docs/search-quality-plan.md), tracked as SQ-01 through SQ-18.

The platform roadmap below is separate: desktop/VS Code packaging, alternative
backends, shared-server infrastructure and further API typing/telemetry remain
planned. Its original planning checkboxes do not supersede the verified app audit.
The user authorized implementing the improvements below in order, using sensible
defaults and providing short progress updates. Preserve the existing UI and data.

## Product direction — all options, one experience

Keep Python/FastAPI as the default and reference implementation. Add the alternatives
alongside it, choosing by requirements, capabilities and availability. Follow
`docs/backend-options.md`; preserve the same look, features and reviewed-action behavior.
Alternative backend work is additional scope, not a replacement of the existing app.

- [ ] Define versioned API schemas, stream events, errors and feature-parity fixtures.
- [ ] Separate model, connector, storage and credential-protection adapters.
- [ ] Keep one shared UI for browser, desktop and VS Code.
- [ ] Add selectable deployment profiles with explicit capability and network checks.
- [ ] Implement Node.js/TypeScript + Fastify as an optional backend.
- [ ] Implement Cloudflare Workers + TypeScript/Hono as an optional backend.
- [ ] Implement Supabase Edge Functions as an optional backend.
- [ ] Document hosted Python and static GitHub Pages + live backend combinations.
- [ ] Provide approved companion processing where a runtime cannot supply a required feature.
- [ ] Test all shared features, permission boundaries, reviewed writes and migration for each profile.
- [ ] Preserve data isolation; never automatically transfer secrets or replay writes when switching backends.
- [ ] Compare measured latency, tokens and recovery behavior; mark profiles supported only after parity passes.
- [ ] Keep the README capability/status matrix and setup guides current.

## First: restore and establish the baseline

- [ ] Restore the verified encrypted backup using the migration tools.
- [ ] Check saved chats, My Diary, To-do, configuration, protected credentials and authenticator access.
- [ ] Confirm the app starts and run the existing automated checks.
- [ ] Keep the original backup. Create a fresh verified backup before database changes.
- [ ] If this file came from `AiMate-Migration/NEW-LAPTOP-TODO.md`, copy it into the restored repo as `TODO.md`.
- [ ] Copy the newer planning documents from `AiMate-Migration/repo-updates` into the restored repo; these were written after the original backup.

## Phase 1 — speed, token use and conversation continuity

- [ ] Measure response time, API calls and token usage before changing behavior.
- [ ] Run independent read-only API calls concurrently with bounded concurrency.
- [ ] Reuse HTTP connections; add sensible timeouts and safe retries for reads.
- [ ] Reuse recent evidence with expiry, source links and credential/user scope isolation.
- [ ] Return compact tool results; page large logs and avoid repeatedly sending the same content.
- [ ] Improve relevant-context retrieval and compact conversation summaries.
- [ ] Preserve restart continuity and explicitly selected references between chats.
- [ ] Keep Auto, Standard and Analysis selection; record routing and model usage accurately.
- [ ] Test ordinary questions, debugging, expired evidence and revoked access.

## Phase 2 — local privacy and dependable migration

- [ ] Add full local database encryption, evaluating SQLCipher packaging on Windows first.
- [ ] Keep encryption keys device-protected and service secrets out of normal model context.
- [ ] Replace the plain-text workspace password file with an appropriate secure login design.
- [ ] Retain authenticator access and local-only development bypass.
- [ ] Preserve existing records, search indexes, vault permissions and invited workspaces.
- [ ] Update portable backup/restore for the new storage format.
- [ ] Test migration, wrong keys/passwords, recovery, and interruption without data loss.

## Phase 3 — validation, maintainability and observability

- [ ] Add typed Pydantic API request/response models incrementally.
- [ ] Modularize frontend code; introduce TypeScript incrementally where useful.
- [ ] Keep the current navy, beige and Alienware themes and compact UI behavior.
- [ ] Add structured logs and OpenTelemetry timings with secret/content redaction.
- [ ] Add regression checks for authorization, chat context, attachments and reviewed writes.
- [ ] Report measured performance and token improvements against the baseline.

## Phase 4 — desktop app first

Priority: deliver a standalone Windows app before shared-server work. Personal
desktop use does not require a purchased hosting server.

- [ ] Package the existing interface in Tauri with a bundled Python/FastAPI backend.
- [ ] Start and stop the backend automatically; require no terminal or separate Python installation.
- [ ] Restrict backend access to the local app and preserve existing authorization and write review.
- [ ] Store live data in the Windows app-data folder; sync encrypted backups through OneDrive.
- [ ] Import the current portable backup without losing chats, diary, tasks or credentials.
- [ ] Test installation, restart, uninstall data retention, attachments and backup/restore on a clean Windows machine.
- [ ] Show clear connection guidance: Intel services still need Intel network/VPN access; cloud AI needs internet and valid account/key access.
- [ ] Plan release signing and updates separately from the first usable desktop build.

## Phase 5 — VS Code extension follow-up

- [ ] Reuse the same AiMate backend instead of creating a second assistant engine.
- [ ] Add a VS Code webview using the existing interface.
- [ ] Add explicit selected-code, file and workspace context sharing.
- [ ] Preserve secret isolation, role permissions, source evidence and confirmation of writes.
- [ ] Verify local versus remote extension behavior and backend network access.
- [ ] Test extension installation, restart, chat continuity and coexistence with the desktop app.

## Optional later — shared-server readiness

Keep these tasks available for a future shared deployment; they are not a
prerequisite for the desktop app or local VS Code extension.

- [ ] Add PostgreSQL + SQLAlchemy and versioned schema migrations for server deployment.
- [ ] Preserve the portable local mode; distinguish the local and server storage paths.
- [ ] Add Redis only where shared caching/session needs justify it.
- [ ] Preserve per-user permissions, access isolation and explicit confirmation of writes.
- [ ] Verify durable action state, duplicate-submit protection and recovery after restart.
- [ ] Prepare Docker/HTTPS deployment, health checks and tested backup/recovery instructions.
- [ ] Keep internal Intel and public showcase data and credentials separate.

## Completion criteria

Existing saved data remains usable; tests pass; backup restores successfully;
access restrictions and write review work; measured timings and token use are
reported; setup and recovery instructions match the implemented app.

Ask the user only for credentials/sign-in, required infrastructure access, or
decisions that change privacy or public exposure. Do not put secrets in this file.
No deployment destination or external spending is authorized by this to-do alone.

## Planning estimates

AI-assisted engineering estimate, including testing: Phase 1 about 1–3 working
days; Phases 1–2 about 3–5 days; the complete shared-server scope about 5–10 days.
These are provisional estimates, to be revised after the new-laptop baseline and
Windows encryption packaging checks. They are not delivery guarantees.

Additional packaging estimates for a first usable version: desktop about 5–8
working days; VS Code extension alone about 4–7 days; both with a shared backend
about 8–12 days. These estimates do not include all earlier upgrade phases or
release signing/distribution.

The estimates above exclude the additional alternative backend implementations.
Estimate each profile after the shared contract and parity baseline are defined.

## Prompt to resume

“Read TODO.md and continue the AiMate upgrades one by one. First verify my
restored data and app. Keep the existing UI, preserve all data, choose sensible
defaults, test each phase and give short progress updates.”

## In progress — GPT via Bedrock

- [ ] GPT via Bedrock: adapter and mocked checks implemented; verify actual
  GPT-6.2 Sol / GPT-6.1 Sol access using Settings → AI → Save & test before
  marking live validation complete. See [setup](docs/bedrock-gpt.md).

## Completed — formatting and organization

- [x] Theme-aware syntax colors for code, JSON and YAML; exact-text copying.
- [x] Message edits keep the existing chat, title and group; superseded context is excluded.
- [x] Move a group/project with all its chats, diary records and nested groups.
- [x] Latest code updates automatically apply after restoring from the OneDrive migration kit.
