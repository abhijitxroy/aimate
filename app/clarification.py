"""Optional user clarification: stop the entire tool batch before any lookup."""
import json
import os

NAME = "ask_user"
POLICY = """
CLARIFY BEFORE FETCHING: First decide whether the current request is clear enough
using the user's message and already supplied conversation context. If a missing
target, scope, meaning or desired outcome would materially change your work,
call ask_user and wait for the user's answer BEFORE any source lookup or action
preparation. Never guess a repository, ticket, build, time range or interpretation.
This rule takes priority over instructions to inspect tools or search old chats
before asking. Context-resolved follow-ups, greetings and clear factual questions
do not need clarification. Ask one short, plain-English question; offer relevant
yes/no, single-choice, multiple-choice or free-text answers when useful. Do not
ask for credentials. After clarification, retain the original request and proceed
only within the clarified scope. Do not mix ask_user with research/proposal calls.
"""
TOOL = {
    "name": NAME,
    "description": "Ask the user to clarify missing intent before fetching information. Ends this turn without executing other tool calls.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "maxLength": 500},
            "kind": {"type": "string", "enum": ["text", "single", "multiple", "yes_no"]},
            "options": {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 120}},
        },
        "required": ["question", "kind"],
        "additionalProperties": False,
    },
}


def enabled():
    return os.environ.get("AIMATE_CLARIFICATION_ENABLED", "1") != "0"


def request(calls, responses=False):
    if not enabled():
        return None
    selected = next((call for call in calls if call.get("name") == NAME), None)
    if selected is None:
        return None
    try:
        args = json.loads(selected.get("arguments", "{}")) if responses else selected.get("input")
        if responses and selected.get("namespace") not in {None, "project"}:
            raise ValueError()
        if not isinstance(args, dict):
            raise ValueError()
        question = args.get("question")
        kind = args.get("kind", "text")
        options = args.get("options", [])
        if not isinstance(question, str) or not question.strip() or len(question) > 500:
            raise ValueError()
        if kind not in {"text", "single", "multiple", "yes_no"} or not isinstance(options, list):
            raise ValueError()
        if len(options) > 6 or any(not isinstance(value, str) or not value.strip() or len(value) > 120 for value in options):
            raise ValueError()
        options = list(dict.fromkeys(value.strip() for value in options))
        if kind == "yes_no":
            options = ["Yes", "No"]
        if kind in {"single", "multiple"} and len(options) < 2:
            kind, options = "text", []
        if kind == "text":
            options = []
    except (ValueError, TypeError, json.JSONDecodeError):
        # An invalid clarification still must never fall through into a lookup.
        question, kind, options = "What should I check, and what result do you need?", "text", []
    return {"status": "awaiting_input", "notice": "Waiting for your answer",
            "question": question.strip(), "kind": kind, "options": options}


def text(value):
    answer = value["question"]
    if value["options"]:
        answer += "\n\n" + "\n".join(f"{i}. {label}" for i, label in enumerate(value["options"], 1))
        answer += "\n\nChoose all that apply." if value["kind"] == "multiple" else "\n\nChoose one, or enter your own answer."
    return answer
