---
name: aimate-backlog
description: Review and continue AiMate To-do work, choose actionable priorities, verify changes and keep completion records accurate.
---

# AiMate backlog work

At the start of AiMate development work, check the live To-do list when accessible,
`docs/new-todos-2026-11-25.json`, `docs/audited-todos.json`, and `TODO.md`.
Use the live list for user-added tasks; source records provide audit evidence
and the platform roadmap. Preserve user edits and IDs when reconciling them.

Identify tasks as actionable, in progress, awaiting information/access, or already
verified. Correct stale status using actual implementation and test evidence.
Choose the highest-priority actionable task and work through tasks one at a time.
Continue routine reversible work under the user's existing authorization.
Ask only for missing information, access or a material decision; continue
independent tasks while waiting. Checking the list does not authorize unrelated
repository changes, paid inference, external service writes or unattended jobs.

Follow [pluggable-features](../pluggable-features/SKILL.md), preserve data and
permissions, and use the existing branch. Run relevant local checks and all
required GitHub workflows before applying a batch or marking its task complete.
For account/network/model-dependent work, fixtures prove the tested behavior;
they do not replace the live validation listed in the task.

Update the live task and matching source record after completion with a short
result and evidence link. Keep incomplete scope open with a concrete next step.
Never mark the whole backlog complete because one batch passed. Save verified
updates into the OneDrive migration kit; do not claim cloud sync or a fresh
encrypted backup unless verified.

Recheck the remaining open list after each verified batch and continue the next
actionable task within the active request. Report completed items, meaningful
remaining gaps and any question requiring the user, concisely. This skill
governs active development; it is not a background scheduler.
