# Project AI starter

A standalone, local, single-operator app for asking questions across your GitHub
repositories, Jira projects and Jenkins jobs. Built from scratch with FastAPI,
Claude tool calling, SQLite and plain browser JavaScript.

## Run on Windows

Python 3.11+ is required.

```powershell
cd C:\Users\abhijit4\repo\oneAPI-CI\project-ai-starter
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\run.ps1
```

Open http://127.0.0.1:8765. Sign in with the password in
`.data/access-password.txt`, generated at the first startup. Alternatively, set
`APP_PASSWORD` to a password of at least 12 characters before startup.
If script execution is restricted, launch directly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

## Configure once

Open **Connections & settings** and add:

| Connection | Required setup |
|---|---|
| AI | Anthropic API key + a model ID available to your account, or Bedrock Runtime + exact model/inference-profile ID + AWS region. Bedrock supports a bearer key entered here or the SDK's normal AWS credential chain. |
| GitHub | `https://api.github.com`, or your Enterprise API base such as `https://github.company.com/api/v3`; PAT; `OWNER/REPO` entries. |
| Jira Data Center | HTTPS site URL, bearer PAT, API version 2, project keys. |
| Jira Cloud | HTTPS site URL, email + API token using Basic auth, API version 3, project keys. |
| Jenkins | HTTPS controller URL, username + API token, exact job names. Nested folders use `folder/job`. |

Save, then test each connection. AI testing makes a small **billable** model
request; service checks only read metadata. Blank token fields preserve saved
tokens. Use the removal checkbox to clear one. Adding scopes does not grant
permissions: the upstream service still enforces your token's rights.

Your questions and selected source data are sent to the configured AI provider.
Use a provider/account approved for your project's data. No credentials are
included in the model's system prompt or tool definitions.

## What is implemented

**Read and investigate**

- GitHub repository metadata, files, directory listings, recursive Git trees,
  branches, commits, issues/comments, PRs/files/reviews, checks, Actions runs/jobs,
  releases and tags. Supports Enterprise base URLs and pagination.
- Jira scoped JQL search, issues, comments, changelogs, projects and transitions.
- Jenkins configured jobs, numbered/latest builds and console logs, with
  progressive byte-offset paging for long logs.
- Cross-system investigation through a bounded multi-step AI loop.
- Streamed answers, tool activity, source links and conversation history.

**Propose and confirm**

- GitHub: create/update issues, comment on issues/PRs, create working branches,
  create/update/delete a file on a working branch, create a draft PR, merge a PR
  using an expected head SHA.
- Jira: create/update/delete issues, add comments, transition issues.
- Jenkins: trigger a job with optional parameters, stop a numbered build.
- Each write is stored as a card showing its target and payload. It runs only
  when you click **Confirm change**, and gets an audit record.
- Proposals expire after 30 minutes; changes to connection settings invalidate
  existing proposals. Executed/uncertain actions cannot be replayed.
- File updates use the current SHA and are rechecked before confirmation.
  Direct writes to the repository default branch are blocked.

Example questions:

```text
Read DEMO-123 and find related pull requests in team/service.
Explain why the last completed team/build Jenkins build failed.
Read the README and source tree in team/service and explain its architecture.
Propose a comment on DEMO-123 with the build failure and evidence.
Create a working branch named fix/DEMO-123 from the current main commit.
On that branch, propose the fix and then a draft pull request.
Trigger team/build with BRANCH=fix/DEMO-123.
```

A workflow with dependent writes takes multiple confirmations. For example,
confirm branch creation, then ask the assistant to edit that branch; confirm
the edit, then ask it to open the draft PR. The next question receives recorded
action outcomes as context.

## Architecture

```text
Browser → authenticated FastAPI endpoint → Claude tool loop
                                            ↓
                                 scoped service connector
                                            ↓
                                  GitHub / Jira / Jenkins

Model proposes write → stored card → user confirmation
                    → revalidation → service write → audit
```

| File | Responsibility |
|---|---|
| `app/main.py` | Authentication, CSRF/origin checks, settings, chat stream and confirmation routes |
| `app/agent.py` | Provider clients, model instructions, tool loop and proposal persistence |
| `app/connectors.py` | Scope validation, service authentication, read endpoints and write operations |
| `app/validation.py` | Dependency-free URL, path, JQL and settings validators |
| `app/store.py` | SQLite state and encrypted credentials |
| `app/static/` | Chat, connections, proposal cards and history UI |

## Scope and practical limits

This is an extensible starter, not unrestricted access to every endpoint.
Unsupported operations produce an explicit error. Add a validated operation
to `connectors.py`, document its payload in `agent.py`, and test it before use.
It does not execute shell commands, run local tests, bulk edit files, retrieve
binary artifacts, or implement autonomous test/fix loops.

Source payloads and log excerpts are limited to control model cost; paginate or
narrow the question when data is truncated. GitHub/Jira search visibility and
Jenkins job access depend on actual service permissions.

The app has a local password, HTTP-only session cookie, same-origin checks and
CSRF protection. It must remain bound to loopback. For a shared deployment,
add HTTPS, real user accounts/SSO, per-user credentials and scopes, persistent
sessions, production rate limiting and deployment controls.

Tokens are encrypted with a locally generated key. Both key and database are
under `.data/`; restrict access to that directory and your OS account. This
protects against accidental plaintext disclosure, not an attacker who can read
both files. Conversations and action previews are stored in SQLite with
best-effort secret redaction; do not paste credentials into chat.

Write failures are conservatively marked **unknown**, because a network timeout
can happen after the target accepted the operation. Inspect the target before
requesting the change again. Restarting does not replay pending writes.

For corporate certificates, set `SSL_CERT_FILE` to a trusted PEM CA bundle
before starting the app. Standard HTTPS proxy environment variables are
respected; TLS verification remains enabled.

## Tests

The test suite uses local HTTP mocks and a fake AI client; it never spends AI
credits or writes to a real project.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

If dependencies are unavailable, the input/scope checks can run independently:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_validation.py -v
```

API references: [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python),
[Jira Cloud enhanced JQL search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/).
