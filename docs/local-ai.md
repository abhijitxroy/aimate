# Local AI fallback

Ollama runs the model on this laptop at `127.0.0.1:11434`. AiMate never downloads
a model automatically and never sends cloud credentials to Ollama.
Ollama cloud models and remote aliases are rejected before project prompts are
sent. This adapter currently supports downloaded local GGUF models.

1. Install Ollama from its official package.
2. Download the small text/tool model: `ollama pull qwen3:4b`.
3. In AiMate, open **Connections & settings → AI model → Provider → Local LLM · offline**.
4. **Check local access**, select an installed model, then **Use local AI**.
5. The askbar's **Local / Cloud** control switches new requests. Cloud settings
   stay saved. A failed cloud request can also offer **Continue with local AI**;
   nothing switches until you click it.

When you ask without a configured cloud connection, appear offline, or receive
a supported cloud authentication/network error, AiMate offers an offline popup.
It checks the local catalog, not paid inference. Continue is disabled if Ollama
is unavailable or no model is installed; the popup explains what to install/start.
Cancel keeps your draft. There is no automatic provider switch or model download.
Choosing Local in settings uses this session's local model; it never replaces
saved cloud credentials. Reload starts with your saved cloud provider.

The model works without internet after download. GitHub, Jira and Jenkins still
need their normal network/VPN and permissions. Their API calls are made by
AiMate's scoped tools, not by the model itself. Remote writes still need review
and confirmation. Current remote facts cannot be fetched when that network is
unavailable. Saved briefs, My Diary and readable chat excerpts remain reference
material and may be stale; no cached result is presented as a fresh live read.

This small fallback is text-only. Images need your cloud vision provider.
History sent to the local model uses a 3 KB readable excerpt plus existing saved
context; full records remain available through scoped recall tools. The total
local prompt (including context and tool schemas) is limited to 24 KB, with a
32,768-token runtime context and at most 4,096 output tokens. Oversized or
interrupted replies return a clear error instead of saving an incomplete answer.
For a large investigation, use a new chat with a short summary or a cloud model.
Local model answers still need verification.

Provider-reported local tokens appear in Usage & billing under `ollama`.
Default local API rates are zero; electricity and hardware costs are not
estimated. User-entered rates are preserved. A cloud spending stop does not
block explicitly selected local inference.

Local AI is available only from a loopback client in a local development app;
production, public showcases and remote clients cannot activate this bridge.
Disable with `AIMATE_LOCAL_AI_ENABLED=0` or hide the optional UI with
`window.AiMateFeatures={localAI:false}`. Saved cloud/provider data and other
features remain usable.

On an office network, Ollama may need the approved corporate HTTPS proxy before
the initial model download. Do not disable TLS checks. Once model files are
installed and verified, no model-registry connection is needed for inference.
