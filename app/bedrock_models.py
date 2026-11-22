"""Read-only model discovery. Listing a model does not verify invocation access."""
import asyncio
import os
import re

import httpx

PRESETS = [
    ("us.anthropic.claude-haiku-5-5", "Claude Haiku 5.5"),
    ("us.anthropic.claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("us.anthropic.claude-opus-5-5", "Claude Opus 5.5"),
    ("us.anthropic.claude-fable-5-2", "Claude Fable 5.2"),
    ("us.anthropic.claude-opus-5", "Claude Opus 5"),
    ("us.anthropic.claude-sonnet-5", "Claude Sonnet 5"),
]


def presets(endpoint="runtime"):
    return [{"id": ident.removeprefix("us.") if endpoint == "mantle" else ident,
             "label": label, "source": "Organization preset"} for ident, label in PRESETS]


async def discover_models(ai, *, transport=None):
    region = ai.get("region", "us-east-2")
    endpoint = ai.get("bedrock_endpoint", "runtime")
    if not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-\d+", region):
        raise ValueError("Save a valid AWS region before refreshing models.")
    rows, notes = [], []
    if ai.get("bedrock_auth", "bearer") == "iam":
        if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
            raise ValueError("Unset AWS_BEARER_TOKEN_BEDROCK before using AWS credential discovery.")

        def listing():
            import boto3
            from botocore.config import Config
            kwargs = {k: ai[k] for k in ("aws_access_key", "aws_secret_key", "aws_session_token") if ai.get(k)}
            kwargs = {{"aws_access_key": "aws_access_key_id", "aws_secret_key": "aws_secret_access_key",
                       "aws_session_token": "aws_session_token"}[k]: v for k, v in kwargs.items()}
            client = boto3.client("bedrock", region_name=region,
                                  config=Config(connect_timeout=10, read_timeout=20, retries={"max_attempts": 1}), **kwargs)
            try:
                foundations = client.list_foundation_models(byProvider="Anthropic")
                profiles, token = [], None
                for _ in range(10):
                    page = client.list_inference_profiles(**({"nextToken": token} if token else {}), maxResults=1000)
                    profiles.extend(page.get("inferenceProfileSummaries", []))
                    token = page.get("nextToken")
                    if not token:
                        break
                return foundations, profiles, bool(token)
            finally:
                client.close()

        try:
            foundations, profiles, incomplete = await asyncio.to_thread(listing)
        except Exception:
            return {"models": [], "message": "Model discovery failed. Check AWS credentials, region and ListFoundationModels/ListInferenceProfiles permissions. Presets remain available."}
        if incomplete:
            notes.append("Profile listing reached its page limit.")
    else:
        if not ai.get("api_key"):
            raise ValueError("Save your Bedrock key in Settings before refreshing models.")
        host = f"https://bedrock-mantle.{region}.api.aws" if endpoint == "mantle" else f"https://bedrock.{region}.amazonaws.com"
        async with httpx.AsyncClient(base_url=host, headers={"Authorization": "Bearer " + ai["api_key"]},
                                    timeout=25, transport=transport, follow_redirects=False) as client:
            async def get(path, params=None):
                response = await client.get(path, params=params)
                if response.status_code != 200:
                    raise ValueError(f"Catalog HTTP {response.status_code}. Check model-list permissions and region.")
                return response.json()

            if endpoint == "mantle":
                try:
                    page = await get("/v1/models")
                    rows = [{"id": m["id"], "label": m["id"], "source": "AWS catalog"}
                            for m in page.get("data", []) if str(m.get("id", "")).startswith("anthropic.claude")]
                except (ValueError, httpx.HTTPError):
                    notes.append("Mantle catalog unavailable. Check your key, region and model-list permissions.")
                return catalog_result(rows, notes)
            foundations, profiles = {}, []
            try:
                foundations = await get("/foundation-models", {"byProvider": "Anthropic"})
            except (ValueError, httpx.HTTPError):
                notes.append("Foundation model catalog unavailable. Check ListFoundationModels permission.")
            try:
                token = None
                for _ in range(10):
                    page = await get("/inference-profiles", {"maxResults": 1000, **({"nextToken": token} if token else {})})
                    profiles.extend(page.get("inferenceProfileSummaries", []))
                    token = page.get("nextToken")
                    if not token:
                        break
                if token:
                    notes.append("Profile listing reached its page limit.")
            except (ValueError, httpx.HTTPError):
                notes.append("Inference profile catalog unavailable. Check ListInferenceProfiles permission.")
    for profile in profiles:
        ident = profile.get("inferenceProfileId", "")
        if profile.get("status") == "ACTIVE" and any("anthropic.claude" in m.get("modelArn", "") for m in profile.get("models", [])):
            rows.append({"id": ident, "label": profile.get("inferenceProfileName", ident), "source": "AWS inference profile"})
    for model in foundations.get("modelSummaries", []):
        if model.get("modelLifecycle", {}).get("status") == "ACTIVE" and str(model.get("modelId", "")).startswith("anthropic.claude"):
            rows.append({"id": model["modelId"], "label": model.get("modelName", model["modelId"]), "source": "AWS foundation model"})
    return catalog_result(rows, notes)


def catalog_result(rows, notes):
    rows = list({row["id"]: row for row in rows if row["id"]}.values())
    return {"models": rows, "message": " ".join(notes + [
        f"{len(rows)} Claude models/profiles listed. Listing does not verify invocation access; Save & test checks the selected models."])}
