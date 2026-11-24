# AiMate backend options

Status: design and implementation plan. Python/FastAPI is the existing default;
additional backends and packaging options are not implemented yet.

## One product, selectable implementations

Keep the existing UI, themes and interaction patterns. Put all supported backends
behind the same versioned API, streaming protocol and behavioral contract.
Select a deployment profile based on requirements, available infrastructure and
authorized network access. Retain the Python implementation as the reference.

```text
Browser / desktop / VS Code interface
                  |
       Shared versioned API contract
                  |
     Selected backend implementation
     Python | Node.js | cloud functions
                  |
  Model providers / connectors / storage
```

Desktop and VS Code are interfaces; they do not require a backend rewrite.
GitHub Pages hosts static UI assets and needs a backend for live server features.

## Profiles to implement and document

| Profile | Implementation | Intended location |
|---|---|---|
| Local Python | Existing FastAPI backend | Approved laptop |
| Desktop | Tauri + bundled backend, Python initially | Approved laptop |
| Editor | VS Code webview + selected backend | Local or approved remote extension host |
| Node.js | TypeScript + Fastify | Laptop or server |
| Cloudflare | TypeScript + Hono/Workers | Public cloud |
| Supabase | TypeScript Edge Functions + managed services | Public cloud |
| Hosted Python | Existing backend + deployment/storage adapters | Approved server |

Share TypeScript domain logic where runtimes permit. Use the same contract and
test fixtures for Python and TypeScript rather than assuming cross-language code
can be shared directly. Avoid unnecessary duplication of connector behavior.

## Features that must retain parity

- Conversations, edit/copy, restart continuity, groups, references, search,
  pin/archive/rename/move/export and topic icons.
- My Diary and formatted tasks.
- Attachments, pasted screenshots and document processing.
- Model selection/routing, streaming, evidence and tool activity.
- GitHub/Jira/Jenkins scope validation, reads and reviewed writes.
- Roles, authenticator access, secret isolation and vault sharing controls.
- Usage/token reporting, configured cost calculations and feedback.
- Durable records, portable migration and tested recovery.

Keep the same user-visible capability and interaction, not identical model-generated
wording or guaranteed identical latency. Measure performance for each supported profile.

## Runtime and access compatibility

Some profiles need approved companion services for PDF/image processing, lengthy
investigations or other unavailable runtime capabilities. Include these dependencies
in setup and parity tests; do not silently remove features.

Report capability availability before selecting a backend. If a required capability
is unavailable, select a complete compatible profile or clearly explain the missing
dependency. Never silently send private data or credentials to another environment.

Model/account availability depends on provider eligibility and the target runtime.
Preserve sign-in behavior where supported and explicitly document provider differences.
Windows DPAPI is a local credential-storage adapter, not a portable cloud format.

Intel connections require an authorized network path. Public showcase profiles must
remain isolated from Intel credentials and data. Backend selection does not change
roles, repository scope or write-confirmation requirements.

## Engineering contract

1. Version API schemas, error codes, stream events and portable data formats.
2. Separate model, connector, storage and credential-protection adapters.
3. Require consistent pagination, timeouts, cancellation and source attribution.
4. Scope evidence caching to the user, permissions, credentials and freshness.
5. Preserve reviewed-write identity, duplicate-submit protection and audit outcomes.
6. Never replay writes automatically during a backend failure or switch.
7. Test migration and rollback; switch only with a verified data/secret mapping.
8. Run shared contract tests and end-to-end feature tests for each profile.
9. Document setup, capabilities, networking, recovery and measured performance.

Add implementations incrementally on the new laptop. A profile stays “planned”
until its prerequisites, migration and feature parity are tested.
