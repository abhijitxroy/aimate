# Real GitHub questions

1. Run `.\run.ps1` and open `http://127.0.0.1:8765`.
   The Windows launcher detects the system HTTPS proxy when no explicit proxy
   environment variable is set. Direct server commands need their own proxy
   configuration where required.
2. Sign in using `.data/access-password.txt`.
3. Open **Connections & settings**. Choose **ChatGPT account** and
   **Continue with ChatGPT**. Sign in on OpenAI's page and review plan permission.
   After returning, choose an available model. Alternatively, configure
   Anthropic or AWS Bedrock with its own model ID and credentials.
4. Set GitHub to `https://api.github.com` and add `abhijitxroy/aimate`.
   Public repositories need no token. Private repositories need a token with
   repository read access. Anonymous requests have GitHub's lower rate limit.
5. Save and **Check repository access**.
   You can save and check GitHub before adding AI access.
6. Ask **Explain my code**. AiMate reads repository files through scoped API
   tools, streams the model's answer, and shows source links.

Change proposals are off by default. Adding a write-capable token and enabling
proposals still requires confirmation for every change.

## ChatGPT subscriptions

Local AiMate supports **Continue with ChatGPT** using OpenAI's documented
public-client OAuth flow and Responses API. You do not enter an API key or
ChatGPT password in AiMate. The app retrieves the signed-in account's model
catalog and sends streamed requests using its granted plan permission.

OpenAI documents a separate **Sign in with ChatGPT** integration for eligible
plan usage. Go eligibility is not promised: verify sign-in, plan permission,
model access and one completed answer with your own account. Reaching a plan
limit stops the answer; AiMate never switches automatically to paid API usage.
Ordinary API billing remains separate from ChatGPT Go.

Run at **http://127.0.0.1:8765**, using one server process. The callback is
`/auth/callback` on the same loopback port; `localhost` is not accepted by this
OAuth integration. Your existing workspace password remains the local app's
access control. Sign-in callbacks expire after ten minutes and cannot be reused.
OAuth credentials are separate from service settings: Windows protects them
with the current OS user's DPAPI; other systems use the app's local encryption
key in a private data directory. Saved account registrations can be selected
and reauthorized without creating a new client. Disconnect attempts remote
revocation and removes local tokens while retaining the registration.

The OAuth client is for this local personal/open-source app. Hosted commercial
apps need their own OpenAI registration; the local flow is disabled in hosted
and offline demo modes. GitHub Pages remains a scripted showcase.

- [ChatGPT Go](https://help.openai.com/en/articles/11989085-what-is-chatgpt-go)
- [Plan usage in participating apps](https://help.openai.com/en/articles/20001542-using-your-chatgpt-plan-in-other-apps-and-sites)
- [Open-source integration](https://developers.openai.com/siwc/token-sharing-open-source)
- [Sign-in quickstart and eligibility](https://developers.openai.com/siwc/quickstart)

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
