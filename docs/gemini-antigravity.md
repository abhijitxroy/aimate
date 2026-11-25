# Gemini / Antigravity

AiMate uses **Google Cloud Vertex AI** directly with the same service-account
credential type supplied for Antigravity. Installing `agy` is optional and
does not connect AiMate or grant it shell execution.

1. In Tokengen, select Antigravity CLI and generate Google Cloud credentials.
2. Download the JSON privately. If a key was pasted into chat, revoke it and
   generate a replacement first.
3. In AiMate → Connections → AI model, choose **Gemini / Antigravity · Vertex AI**.
4. Import the replacement JSON, or paste it in the masked Service-account JSON
   field. Choose Standard and optionally Analysis.
5. Save & test AI. This makes a small billable request; a passing check shows
   the selected model and its reply. Live access depends on your Google project
   permissions, key validity, quota and model availability.

Simple setup uses `global`. Project is read from the JSON. Advanced settings
allow another project or location permitted by the account.
The preset model IDs were checked against Tokengen on 25 November 2026:
Hydrogen, Carbon, Neon, Argon, 3.8 Flash and 3.1 Pro Preview. Presets do not prove
your account's model entitlement.

Credentials are saved in AiMate's existing encrypted configuration, never in a
repository file, exported CLI script or model prompt. The public settings API
returns only a configured flag. Google OAuth tokens stay in client memory and
are refreshed before expiry; JSON/private-key values are redacted from answers
and diagnostics. Google and Bedrock credentials remain separate.

Gemini supports text, images and AiMate's existing scoped tools and reviewed
changes. Provider thought signatures are retained for their original model;
switching models uses readable prior evidence instead of replaying foreign
signatures. Interrupted streams are not saved as completed replies.
Reported tokens include output thinking tokens and separate cached input.
Usage prices remain operator-supplied estimates, not Google invoices.

Disable the server adapter with `AIMATE_GEMINI_ENABLED=0`. Hide the optional
settings UI with `window.AiMateFeatures.geminiVertex=false` before startup.
No server ADC files, environment credentials or arbitrary endpoints are read.
Only service-account JSON with a valid RSA key and Google's fixed token endpoint
is supported. Credential imports are limited to 20 KB.
