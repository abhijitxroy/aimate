# AI connections

**Personal** uses your own ChatGPT sign-in or Anthropic API key.
**Intel / Bedrock** uses your organization-provided Bedrock key and allowed
models for Claude, GPT/Codex or OpenCode.

These labels explain the access method. Only the selected provider is active;
they do not create extra accounts, share credentials between providers or
change authentication. The Account row retains the existing sign-in and
disconnect controls. Plan details are collapsed until requested.

The optional presentation module is `ai_connection_ui.js` and its stylesheet.
Set `window.AiMateFeatures.aiConnectionLayout=false` before startup to restore
the original layout without changing stored settings or connection behavior.

**Intel / Google Cloud** uses separate Gemini / Antigravity credentials.
See [Gemini setup](gemini-antigravity.md). The Windows installer alone supplies
no connection configuration.
