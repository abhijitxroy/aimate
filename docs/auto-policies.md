# User-selected Auto policy

The askbar lets the user choose a policy and shows the selected model:

| Choice | Current behavior |
|---|---|
| Auto · Balanced | Classify the request and choose the current provider's Standard or Analysis model |
| Auto · Quality | Use the configured Analysis slot without a classification request |
| Auto · Economy | Use the configured Standard slot without a classification request |
| Standard / Analysis | Explicit manual selection |

The browser remembers the choice. Each saved answer records its mode/model and
shows the policy in its model details. Browser preferences are not part of the
encrypted portable data backup.

Quality and Economy are user preferences, not independently measured model
rankings or price guarantees. Configure suitable models for the slots; Economy
cannot make an expensive Standard model cheap. Missing Analysis disables Quality.
No provider/account changes or premium models are silently introduced.

`app/auto_policy.py` is optional. Set `AIMATE_AUTO_POLICY_ENABLED=0` to reject the
two additional policy modes with a clear message; original Auto, Standard and
Analysis remain usable.

This batch stays within the selected provider. Automatic selection across
Bedrock, Gemini, OpenCode and ChatGPT/Codex needs validated encrypted profiles,
data permissions, health/cost rules and matched quality measurements. It remains
open in `cross-provider-auto-routing`.
