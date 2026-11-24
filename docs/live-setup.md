# Real GitHub questions

1. Run `.\run_aimate.ps1` and open `http://127.0.0.1:8765`.
   The Windows launcher detects the system HTTPS proxy when no explicit proxy
   environment variable is set. Direct server commands need their own proxy
   configuration where required.
2. Local development opens directly. Use `.\run_aimate.ps1 -Secure` for authenticator
   sign-in (or `.data/access-password.txt` before enrolling an authenticator).
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

Settings has separate **AI model, GitHub, Jira, Jenkins and Changes** tabs.
Each tab saves independently. Use **Save & check** to validate its inputs.
Green means the check passed; red includes the failure and what to correct;
gray means unverified. Saved keys alone never count as a successful connection.

GitHub results show each repository's code, issues, pull requests and Actions
read access, along with its default branch and any reported push permission.
Token checks identify the authenticated account; anonymous public access is
marked separately. Write permissions are not tested by creating a change.
Jira and Jenkins results show which configured projects/jobs are accessible.
ChatGPT checks verify its account model catalog; Claude API/Bedrock checks
show the model's actual test reply and incur a small inference charge.

Checks persist locally with their timestamps across restarts. Changed connection
settings become unverified. GitHub, Jira and Jenkins refresh automatically while
the app is open; the last verified result stays visible during refresh. AI health
updates from successful answers or explicit checks, without automatic paid tests.

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
3. Enroll an authenticator on the deployment machine before enabling production:
   `docker compose -f compose.live.yaml -f compose.enroll.yaml up -d --build`.
   Open the loopback address, sign in with `APP_PASSWORD`, then choose
   **Connections & settings → Admin → Set up OTP**. Keep recovery codes privately.
   Stop enrollment mode with
   `docker compose -f compose.live.yaml -f compose.enroll.yaml down`
   (keep the volume), then run `docker compose -f compose.live.yaml up -d --build`.
4. Proxy that HTTPS origin to `127.0.0.1:8765`. Keep the upstream port private.
   Disable response buffering for `/api/chat` and allow long streamed requests.
5. Sign in with your authenticator and add credentials in the app. `/healthz` reports process health;
   **Check repository access** checks the upstream service.

Hosted mode enables secure session cookies, checks the configured origin, and
allows only that hostname plus local health checks. Use one Uvicorn worker:
sessions, rate limits and conversation locks are process-local. Restarting
requires sign-in again. The `live-data` volume holds the encrypted settings,
encryption key, conversation history and audit records; protect and back it up.

Production always disables development bypass and password sign-in, even if
`AIMATE_DEV_LOGIN=1` is accidentally set. Missing owner OTP prevents startup.
Admin assigns named Developer, Viewer or Reviewer access; each invited user has
their own encrypted authenticator seed and a revocable, expiring access code.
User role changes and revocation apply on the next request. Each invitation has
its own encrypted connection settings and separate chats, records and usage.
Users add their own AI and service credentials; owner credentials are not shared.
Admin controls whether Developers can execute reviewed external changes.
The original data directory remains the owner's workspace; personal workspaces
live in `users/<invitation-id>/` within the same backed-up data volume.
A public multi-user product still needs self-service account recovery, durable
sessions/rate-limit storage and an operational deployment review.

No remote deployment has been provisioned by these configuration files.

## Public showcase with personal data

Keep GitHub Pages as the public landing/demo page and link to a separately hosted
AiMate backend. Pages cannot run the Python server.

Use `compose.live.yaml` **with** `compose.public.yaml`. This uses a new
`public-data` volume, never the existing local or private deployment data.
For initial enrollment:

```powershell
docker compose -f compose.live.yaml -f compose.public.yaml -f compose.enroll.yaml up -d --build
```

Enroll a new owner authenticator locally on the deployment machine, stop enrollment
without deleting the volume, then start production:

```powershell
docker compose -f compose.live.yaml -f compose.public.yaml -f compose.enroll.yaml down
docker compose -f compose.live.yaml -f compose.public.yaml up -d --build
```

The backend enforces approved personal GitHub owners (`abhijitxroy` by default)
and rejects Intel GitHub organizations, Intel service domains, and known Intel
resource links in source responses and new chats/records. Jira and Jenkins
are disabled unless the operator explicitly approves non-Intel hosts through
`AIMATE_PUBLIC_JIRA_HOSTS` / `AIMATE_PUBLIC_JENKINS_HOSTS`.
Personal AWS credentials are required; server IAM fallback is disabled.
Repository additions from chat obey the same policy before any access check.

Never upload or copy local `.data`, credentials, OTP seeds, keys, backups or chat
exports. Public mode refuses an existing unmarked data directory. Add fresh
personal credentials in the public app. Source filtering is not comprehensive
content classification: it cannot identify every corporate detail pasted as
plain text or embedded in an image/PDF. Only submit non-corporate material.

On your office laptop, keep using the local app at `http://127.0.0.1:8765`
without `AIMATE_PUBLIC_SHOWCASE=1`. Its authorized Intel sources continue to
work through your office network. The public site's **Open local AiMate** link
opens that separate running application; it does not transfer local credentials
or data to the website. Device location never disables the public backend policy.

## GitHub + Jira + Claude through Bedrock

In **Connections & settings**:

1. Choose **AWS Bedrock Runtime**, enter the AWS region and exact Claude model
   or inference-profile ID from your AWS account.
2. Select **Bedrock API key** and enter your bearer key. For models served by
   the native Messages endpoint, select **Bedrock Mantle** and its model ID.
   Alternatively, select **AWS credentials / server role** for Runtime:
   enter the access key ID and secret access key, plus the session token for
   temporary credentials. With no saved AWS credentials, the SDK uses the
   server's AWS credential chain. Remove saved AWS credentials to return to it.
3. Add your GitHub PAT and repository names. The PAT must cover those repositories;
   organization SSO may require approval. Reading private code needs Contents
   access; the actions you request need corresponding Issues, Pull requests
   or Contents write permissions.
4. Add your Jira URL, PAT and project keys. Data Center uses bearer authentication
   and API 2; Cloud uses email + API token, Basic authentication and API 3.
5. Save, then check AI, repository and project access. The AI check is a small
   billable inference request. Service checks verify reads, not every write
   permission. Ask “Compare open Jira issues with my GitHub pull requests.”
6. Enable change proposals when needed. Review and confirm each proposed change.

Keys are stored encrypted by the backend and omitted from AI context. Enter
them only in Settings. The assistant supports the operations listed in the
README; it does not gain every service API operation by adding a token.
AWS IAM, model availability, token permissions and API quotas still apply.

References: [AWS bearer-key permissions](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-permissions.html),
[Claude on Bedrock Runtime](https://platform.claude.com/docs/en/build-with-claude/claude-on-amazon-bedrock-legacy),
[Claude on Bedrock Mantle](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock).

Jira Simple setup needs only the site URL and a Data Center PAT. Save & connect verifies the account and discovers visible project keys and names. The assistant can access projects/issues permitted by that account; Jira permissions still apply. Advanced setup supports Cloud email + API token and optional selected-project restrictions. Restrictions use keys (for example ONEAPICI), not display names. Existing API configurations without an access setting remain restricted to their project list.

On Windows, service connections validate TLS against the Windows certificate store. The launcher preserves direct routes for saved intranet URLs while using the Windows proxy for external sites. Restart run_aimate.ps1 after adding a new intranet host so its proxy route is refreshed.

Jenkins Simple setup stores the controller URL and Jenkins username once under Controller & account; only the API token needs replacing. Local setup suggests the current Windows username (confirm it matches your Jenkins account), and JENKINS_URL can provide a default controller. Job names are optional: Simple mode discovers visible root jobs/folders and can read nested jobs/builds through account permissions. Advanced can restrict access to selected job names. Connection checks never trigger or abort a build.
