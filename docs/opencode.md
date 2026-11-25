# OpenCode

In AiMate: **Connections & settings → AI model → OpenCode · Bedrock**.
Choose Standard and, optionally, Analysis. Keep the key field blank to reuse
your saved Bedrock key. **Save & test AI** verifies your selected models with
small billable requests. Selecting OpenCode alone does not change saved settings.

The supplied portal catalog includes GPT, Claude, Kimi and GLM on US/global
profiles through the fixed `us-east-2` Bedrock gateways. Catalog entries are
presets, not proof of account access. GLM is text-only; Astra/Fable are labelled
premium. AiMate never automatically chooses a premium model that you have not
configured.

OpenCode is also a separate terminal application. **Download opencode.json**
provides the supplied setup for that application:

```text
Windows: %USERPROFILE%\.config\opencode\opencode.json
macOS/Linux: ~/.config/opencode/opencode.json
```

The downloaded file contains environment references, never saved credentials.
The terminal application reads your separately configured
`AWS_BEARER_TOKEN_BEDROCK`. AiMate reads only the key saved in its encrypted
settings; it neither installs nor runs the OpenCode CLI.

Implementation: `app/opencode_bedrock.py` adapts Chat Completions for GPT/Kimi/GLM
and Anthropic Messages for Claude. The existing tool loop retains repository
scope, role checks, evidence handling and confirmation before changes.
Usage is recorded against the requested profile; missing provider usage remains
unreported rather than an invented zero bill. Existing account access and prices
are not inferred from the config.

Disable the module with `AIMATE_OPENCODE_ENABLED=0`; other AI providers and stored
settings remain available. Re-enable it before using a saved OpenCode connection.
