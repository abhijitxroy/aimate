---
name: pluggable-features
description: Add or refactor AiMate features as optional modules that can be disabled independently for maintenance and debugging.
---

# Pluggable AiMate features

Make each new feature/enhancement a module with an explicit registration hook or feature flag. Keep its UI, routes and service adapters together behind a small interface; avoid extending unrelated core code.

Disabling a feature must leave the core askbar, saved data and other modules usable. Preserve authentication, scope checks and write confirmation independently of optional features. A disabled module must never bypass these protections.

Validate both enabled and disabled behavior. Preserve existing data and portable-backup compatibility when introducing schema changes. Document the module's switch, dependencies and limitations.

Use the relevant separate unit, integration, browser-regression and flaky-check workflows. Record actual validation and leave incomplete scope or missing live validation open in To-do.
