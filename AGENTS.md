# AiMate development

At the start of development work and after each verified batch, follow
[the backlog skill](skills/aimate-backlog/SKILL.md): check pending tasks, continue
actionable work, ask only for genuine missing information, and update completion
with evidence. Preserve incomplete live-validation items as open.

For feature/enhancement work, read [the pluggable-feature skill](skills/pluggable-features/SKILL.md). New modules must be independently disableable without breaking the core app or weakening permissions.

Work through requested tasks one at a time. Preserve existing user data and unrelated edits. A green fixture-based test is automated evidence; do not describe it as complete live-service validation.

Before completing a feature batch, run its relevant local checks and require all four separate GitHub test workflows plus the available Quality/Security/Build smoke workflows to pass. Keep genuine scope/validation gaps open with a concrete reason.
