"""Workspace-owned review profiles and a persistent, explicitly selected panel."""
import copy
import hashlib
import json
import os
import re
import secrets
import time

from fastapi import Depends, Request


def enabled():
    return os.environ.get("AIMATE_FINAL_REVIEW_ENABLED") != "0"


def install(store):
    store.execute("CREATE TABLE IF NOT EXISTS final_review_profiles "
                  "(id TEXT PRIMARY KEY, encrypted TEXT NOT NULL)")
    store.execute("CREATE TABLE IF NOT EXISTS final_review_preferences "
                  "(id INTEGER PRIMARY KEY CHECK(id=1), encrypted TEXT NOT NULL)")


def identity(model):
    """A client name/geographic route does not make a second independent model."""
    model = model.split("/", 1)[-1]
    model = re.sub(r"^(us|global|eu|apac|au)\.", "", model).lower()
    return re.sub(r"^(anthropic|openai)\.", "", model)


def fingerprint(ai):
    return hashlib.sha256(json.dumps(ai, sort_keys=True).encode()).hexdigest()


def profiles(store):
    install(store)
    return {row["id"]: json.loads(store.cipher.decrypt(row["encrypted"].encode()))
            for row in store.rows("SELECT * FROM final_review_profiles")}


def preference(store):
    install(store)
    rows = store.rows("SELECT encrypted FROM final_review_preferences WHERE id=1")
    return json.loads(store.cipher.decrypt(rows[0]["encrypted"].encode())) if rows else None


def put_profile(store, ident, value):
    store.execute("INSERT OR REPLACE INTO final_review_profiles VALUES (?,?)",
                  (ident, store.cipher.encrypt(json.dumps(value).encode()).decode()))


def public_profile(ident, value):
    return {"id": ident, "name": value["name"], "provider": value["ai"]["provider"],
            "model": value["ai"]["model"], "scope": value["scope"],
            "checked": value.get("checked", 0),
            "ready": value.get("verified") == fingerprint(value["ai"]),
            "suggested_lead": "claude-opus" in identity(value["ai"]["model"])}


def require_current_credentials(store, value):
    """Rotating a saved connection must not leave its old key silently usable."""
    active = store.config().get("ai", {})
    saved = value["ai"]
    shared_bedrock = {"bedrock", "bedrock-openai", "opencode"}
    same = active.get("provider") == saved["provider"] or {
        active.get("provider"), saved["provider"]} <= shared_bedrock
    if same:
        fields = ("api_key", "aws_access_key", "aws_secret_key", "aws_session_token") if saved["provider"] != "gemini" else ("gcp_credentials",)
        if any(active.get(key, "") != saved.get(key, "") for key in fields):
            raise ValueError("This profile uses an older credential. Save the refreshed connection as this profile and check it again.")


def capture(store, body, chatgpt=None):
    if not isinstance(body, dict) or set(body) - {"id", "name", "scope", "model"}:
        raise ValueError("Provide a profile name, model and data scope.")
    name, scope = body.get("name"), body.get("scope")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Use a profile name of 1–80 characters.")
    if scope not in {"organization", "non-intel"}:
        raise ValueError("Choose Organization or Non-Intel data.")
    config = store.config()
    ai = copy.deepcopy(config.get("ai", {}))
    provider = ai.get("provider")
    if provider not in {"bedrock", "bedrock-openai", "opencode", "gemini", "anthropic", "chatgpt"}:
        raise ValueError("Save a supported online connection first. Local LLM is not a final reviewer.")
    if scope == "organization" and provider not in {"bedrock", "bedrock-openai", "opencode", "gemini"}:
        raise ValueError("Personal ChatGPT/Anthropic connections cannot review Intel data.")
    model = body.get("model") or ai.get("model")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", model):
        raise ValueError("Choose a valid model ID.")
    if provider == "bedrock":
        from app.claude_catalog import model_id
        model_id(model)
    if provider == "opencode":
        from app.opencode_bedrock import resolve
        resolve(model)
    if provider == "bedrock-openai":
        from app.bedrock_gpt import validate
        validate({**ai, "model": model, "analysis_model": ""})
    # Keep only the active provider's credentials, never other retained keys.
    fields = {"provider", "region", "model", "bedrock_endpoint", "bedrock_auth", "bedrock_mode"}
    if provider in {"bedrock", "bedrock-openai", "opencode", "anthropic"}:
        fields |= {"api_key", "aws_access_key", "aws_secret_key", "aws_session_token"}
    elif provider == "gemini":
        fields |= {"gcp_credentials", "gcp_project", "gcp_location"}
    ai = {key: value for key, value in ai.items() if key in fields}
    ai["model"] = model
    if provider == "chatgpt":
        status = chatgpt.status() if chatgpt else {}
        if not status.get("connected"):
            raise ValueError("Sign in to your personal ChatGPT account first.")
        ai["account"] = status["active"]
    from app.connectors import scrub
    if scrub(name, config) != name:
        raise ValueError("Do not put credentials in a profile name.")
    if scrub(model, config) != model:
        raise ValueError("Use a model ID, not a credential, in the model field.")
    existing = profiles(store)
    ident = body.get("id") or secrets.token_hex(12)
    if body.get("id") and ident not in existing:
        raise ValueError("Review profile not found in this workspace.")
    if len(existing) >= 12 and ident not in existing:
        raise ValueError("Keep up to twelve saved review profiles.")
    old = existing.get(ident, {})
    value = {"name": name.strip(), "scope": scope, "ai": ai}
    if old.get("ai") == ai and old.get("scope") == scope:
        value.update(verified=old.get("verified"), checked=old.get("checked", 0))
    put_profile(store, ident, value)
    return public_profile(ident, value)


def save_preference(store, body):
    if not isinstance(body, dict) or set(body) != {"reviewers", "lead"}:
        raise ValueError("Select reviewers and a lead model.")
    selected, lead = body["reviewers"], body["lead"]
    if (not isinstance(selected, list) or not 2 <= len(selected) <= 6
            or any(not isinstance(value, str) for value in selected)
            or len(set(selected)) != len(selected) or lead not in selected):
        raise ValueError("Choose two to six reviewers and a lead from that panel.")
    available = profiles(store)
    values = [available.get(ident) for ident in selected]
    if any(not value or not public_profile("", value)["ready"] for value in values):
        raise ValueError("Check access for each selected review profile first.")
    if len({identity(value["ai"]["model"]) for value in values}) != len(values):
        raise ValueError("The same underlying model cannot be counted twice through different tools/routes.")
    result = {"reviewers": selected, "lead": lead, "updated": time.time()}
    store.execute("INSERT OR REPLACE INTO final_review_preferences VALUES (1,?)",
                  (store.cipher.encrypt(json.dumps(result).encode()).decode(),))
    return result


def selected_panel(store, intel):
    if not enabled():
        raise ValueError("Final PR review is disabled.")
    chosen = preference(store)
    if not chosen:
        raise ValueError("Configure your Final PR review panel once in Settings.")
    available = profiles(store)
    result = []
    for ident in chosen["reviewers"]:
        value = available.get(ident)
        if not value or not public_profile(ident, value)["ready"]:
            raise ValueError("A selected review profile changed or was removed. Check your saved panel in Settings.")
        if intel and value["scope"] != "organization":
            raise ValueError("This PR contains Intel data. Choose only organization profiles in your saved panel.")
        require_current_credentials(store, value)
        result.append({"id": ident, **value})
    if len({identity(row["ai"]["model"]) for row in result}) != len(result):
        raise ValueError("Choose distinct underlying review models.")
    return result, chosen["lead"]


def model_choices(ai):
    """Local setup IDs only; no paid/background entitlement check."""
    provider = ai.get("provider")
    values = [v for v in (ai.get("model"), ai.get("analysis_model")) if v]
    if provider == "bedrock":
        from app.bedrock_models import presets
        values.extend(row["id"] for row in presets(ai.get("bedrock_endpoint", "runtime")))
    elif provider == "bedrock-openai":
        from app.bedrock_gpt import MODELS
        values.extend(row["id"] for row in MODELS)
    elif provider == "opencode":
        from app.opencode_bedrock import models
        values.extend(row["id"] for row in models())
    elif provider == "gemini":
        from app.gemini_vertex import MODELS
        values.extend(row[0] for row in MODELS)
    return [{"id": value} for value in dict.fromkeys(values)]


def profile_status(store, ident, value):
    result = public_profile(ident, value)
    try:
        require_current_credentials(store, value)
    except ValueError:
        result.update(ready=False, message="Saved credential changed. Refresh this profile and check access.")
    return result


def register(app, store, auth, config_lock, client_factory, chatgpt, lease_factory):
    if not enabled():
        return

    @app.get("/api/settings/final-review")
    def get_panel(session=Depends(auth)):
        return {"profiles": [profile_status(store, ident, value) for ident, value in profiles(store).items()],
                "selection": preference(store),
                "models": model_choices(store.config().get("ai", {})),
                "notice": "Your saved panel runs automatically only when you choose Final PR review. "
                          "Each reviewer and the lead comparison consume tokens. Opus is the suggested lead."}

    @app.post("/api/settings/final-review/profiles")
    async def add_profile(request: Request, session=Depends(auth)):
        body = await request.json()
        async with config_lock:
            return capture(store, body, chatgpt)

    @app.delete("/api/settings/final-review/profiles/{ident}")
    async def delete_profile(ident: str, session=Depends(auth)):
        async with config_lock:
            install(store)
            store.execute("DELETE FROM final_review_profiles WHERE id=?", (ident,))
        return {"removed": ident}

    @app.post("/api/settings/final-review/profiles/{ident}/test")
    async def test_profile(ident: str, session=Depends(auth)):
        from app.final_review_calls import call
        available = profiles(store)
        if ident not in available:
            raise ValueError("Review profile not found in this workspace.")
        value = available[ident]
        stamp = fingerprint(value["ai"])
        require_current_credentials(store, value)
        # A failed recheck must not keep the earlier success state.
        put_profile(store, ident, {k: v for k, v in value.items() if k != "verified"})
        # Explicit button, not a background paid call. No user/PR content.
        check = lease_factory(session)
        await call(store, value, "Reply with OK.", "Connection check only.", client_factory, chatgpt,
                   check, max_tokens=256, origin="Final review access check")
        check()
        async with config_lock:
            current = profiles(store).get(ident)
            if not current or fingerprint(current["ai"]) != stamp:
                raise ValueError("Profile changed during the access check. Check the new profile.")
            current.update(verified=stamp, checked=time.time())
            put_profile(store, ident, current)
        return public_profile(ident, current)

    @app.put("/api/settings/final-review")
    async def update_panel(request: Request, session=Depends(auth)):
        body = await request.json()
        async with config_lock:
            return save_preference(store, body)
