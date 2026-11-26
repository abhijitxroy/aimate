"""User-selected routing preference for the current configured model slots."""
import os

MODES = {"auto-quality": "quality", "auto-economy": "economy"}


def choose(ai, mode):
    if mode not in MODES:
        return None
    if os.environ.get("AIMATE_AUTO_POLICY_ENABLED") == "0":
        raise ValueError("Auto policies are disabled. Choose Auto, Standard or Analysis.")
    policy = MODES[mode]
    route = "analysis" if policy == "quality" else "standard"
    model = ai.get("analysis_model") if route == "analysis" else ai.get("model")
    if not model:
        raise ValueError("Configure an Analysis model before selecting Auto Quality.")
    return {"route": route, "model": model, "policy": policy,
            "notice": "Auto " + policy.title() + " uses your configured " + route.title() +
                      " model. This policy currently stays within the selected provider."}
