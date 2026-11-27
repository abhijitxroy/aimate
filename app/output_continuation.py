"""Bounded continuation for output exhaustion; never repeat truncated actions."""
import os
import re

INSTRUCTION = (
    "Continue automatically from the evidence and partial answer already present. "
    "The previous response hit its output allowance. Calls marked not executed "
    "were not run. Do not reread already available evidence or repeat proposals. "
    "Finish the requested investigation and give a concise final answer with "
    "verified findings and genuine remaining gaps. Do not ask the user to type Continue."
)


def retries(config):
    if os.environ.get("AIMATE_OUTPUT_CONTINUATION_ENABLED", "1") == "0" or config.get("_local_ai"):
        return 0
    return 2


def budget(model, kind=None, retry=0):
    if os.environ.get("AIMATE_OUTPUT_CONTINUATION_ENABLED", "1") == "0":
        return 4096
    value = str(model).lower()
    legacy = re.search(r"claude-3(?:-(\d))?-(?:haiku|sonnet|opus)", value)
    if legacy and legacy.group(1) != "7":
        return 8192 if legacy.group(1) == "5" else 4096
    modern = re.search(r"claude-(?:haiku|sonnet|opus|fable)-[4-9]", value)
    capable = bool(modern or (legacy and legacy.group(1) == "7") or "openai.gpt-" in value or value.startswith("gemini-"))
    if not capable:
        return 4096
    return min(32768, (16384 if kind in {"analysis", "review", "design", "note"} else 4096) * (2 ** retry))


def output_limited(response):
    if not isinstance(response, dict) or response.get("status") != "incomplete":
        return False
    details = response.get("incomplete_details")
    return isinstance(details, dict) and details.get("reason") in {"max_output_tokens", "max_tokens"}


def normalize_event(event):
    if event.get("type") == "response.incomplete" and output_limited(event.get("response") or {}):
        return {**event, "type": "response.completed"}
    return event


def persisted(messages, internal_ids):
    """Internal recovery prompts must not appear as messages from the user."""
    return [message for message in messages if id(message) not in internal_ids]
