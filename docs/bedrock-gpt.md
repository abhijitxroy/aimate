# GPT via Bedrock

In **Connections & settings → AI model**, choose **GPT via Bedrock**.
Simple setup uses `us-east-2` and a Bedrock bearer key. When switching from
Claude on Bedrock, leave the key blank to reuse that saved Bedrock key.
Keys from unrelated providers are never reused.

**GPT-6.2 Sol · US** is the default. Select **GPT-6.1 Sol · US** manually if
6.2 is unavailable to your account. Other setup presets include Terra, Sol
and Luna on US/global routes. These are the supplied portal's setup presets,
not a live account entitlement list. Retired GPT-5.6 Sol/Luna profiles are
rejected. Custom profile IDs remain available.

Click **Save & test AI** to verify your actual access. The small inference
test is billable through AWS and appears in AiMate usage. Advanced setup
exposes region and an optional Analysis profile; Auto and manual routing
use the existing routing controls. AiMate does not silently switch to a
more expensive model or change your saved Claude connection.

Requests use the regional Bedrock `/openai/v1/responses` endpoint with TLS,
no credential-bearing redirects, and the existing reviewed tool loop.
Source scope, roles, write confirmation, metering and saved chat context
remain enforced. Foreign provider reasoning blobs are excluded when
switching providers. This does not launch Codex CLI or change its config.

Set `AIMATE_BEDROCK_GPT_ENABLED=0` before starting the server to disable this
optional adapter. The authenticated model-preset route then returns no
presets, and calls/settings for this provider are rejected. Existing
Claude, ChatGPT account and Anthropic connections remain usable.

Automated tests use fictional credentials and mocked Bedrock responses.
Live model/account access still needs the user's Save & test check.

The Type info button is a separate optional UI module (`field_help.js`);
set `window.AiMateFeatures.fieldHelp=false` before it loads to disable it.
Chat creation times appear in sidebar tooltips in the browser's local
time zone; they do not send additional model requests.
