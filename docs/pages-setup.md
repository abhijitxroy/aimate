# AiMate on GitHub Pages

Pages opens the same frontend as the Python app. It includes the navy, beige
and Alienware themes, conversations, My Diary, To-do, settings and attachments.
The Pages preview keeps records only until the page reloads. It has no live AI,
service connections, credentials or shared chat history.

## Build

```powershell
python tools/build_pages.py --index-only
python tools/build_pages.py
```

The first command updates the root `index.html` from `app/static/index.html`.
The second creates a clean `_site` artifact containing only the frontend and
Pages bootstrap. Use an empty output directory.

## Live backend

Set `appUrl` in `pages/config.js` to the HTTPS URL of a deployed AiMate app.
Pages then opens that app, which serves the same interface and authenticates
users on its own origin. This file is public: never add a token, password,
private URL query or credentials to it.

ChatGPT sign-in currently requires the local Python app. Publishing this
frontend does not enable hosted ChatGPT authentication. Bedrock, Jira and
Jenkins require the backend, appropriate credentials and network access.

For office use, continue running the local app on your office laptop.
Publishing a public frontend does not grant access to your local data.

## Intel sandbox

The Nexus workflow is manual and refuses to publish unless GitHub reports
that its Pages site has private visibility. Private repository visibility
alone does not make a Pages site private. The workflow packages only
`applications/aimate` frontend assets, excluding Nexus documentation and all
runtime data. A repository administrator must configure private Pages first.
