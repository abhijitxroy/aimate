# Real GitHub questions

1. Run `.\run.ps1` and open `http://127.0.0.1:8765`.
   The Windows launcher detects the system HTTPS proxy when no explicit proxy
   environment variable is set. Direct server commands need their own proxy
   configuration where required.
2. Sign in using `.data/access-password.txt`.
3. Open **Connections & settings**. Add an AI provider key and model ID.
4. Set GitHub to `https://api.github.com` and add `abhijitxroy/aimate`.
   Public repositories need no token. Private repositories need a token with
   repository read access. Anonymous requests have GitHub's lower rate limit.
5. Save and **Check repository access**.
6. Ask **Explain my code**. AiMate reads repository files through scoped API
   tools, streams the model's answer, and shows source links.

Change proposals are off by default. Adding a write-capable token and enabling
proposals still requires confirmation for every change.

## ChatGPT subscriptions

ChatGPT Go does not include ordinary OpenAI API usage. The current AiMate backend
supports Claude through Anthropic or AWS Bedrock; it does not yet implement
ChatGPT sign-in or OpenAI inference.

OpenAI documents a separate **Sign in with ChatGPT** integration for eligible
plan usage. Its commercial-app guidance includes Go, while the current
open-source quickstart references Plus and Pro. Go eligibility for a new local
AiMate integration must be verified before promising it. No ChatGPT password,
browser cookie, or copied session token should be entered as an API key.

- [ChatGPT Go](https://help.openai.com/en/articles/11989085-what-is-chatgpt-go)
- [Plan usage in participating apps](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites)
- [Open-source integration](https://developers.openai.com/siwc/token-sharing-open-source)

## Host a private, single-owner workspace

Serve this app's frontend and backend together. GitHub Pages remains the sample
demo until a real HTTPS deployment exists.

1. Choose a server with Docker and an HTTPS reverse proxy.
2. Copy `.env.example` to `.env`. Set a random `APP_PASSWORD` and the exact
   `APP_PUBLIC_URL`, such as `https://aimate.example.com`.
3. Run `docker compose -f compose.live.yaml up -d --build`.
4. Proxy that HTTPS origin to `127.0.0.1:8765`. Keep the upstream port private.
   Disable response buffering for `/api/chat` and allow long streamed requests.
5. Sign in and add credentials in the app. `/healthz` reports process health;
   **Check repository access** checks the upstream service.

Hosted mode enables secure session cookies, checks the configured origin, and
allows only that hostname plus local health checks. Use one Uvicorn worker:
sessions, rate limits and conversation locks are process-local. Restarting
requires sign-in again. The `live-data` volume holds the encrypted settings,
encryption key, conversation history and audit records; protect and back it up.

This deployment is for one owner. Anyone given the workspace password shares
that owner's connections and history. A public multi-user product still needs
per-user accounts, credential isolation and durable session/rate-limit storage.

No remote deployment has been provisioned by these configuration files.
