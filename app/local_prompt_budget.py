"""Bound local wire prompts without changing saved history or permissions."""
import copy
import json
import os

MAX_PROMPT_BYTES = 64 * 1024
NOTICE = (
    "\n[Local context excerpt; omitted content was NOT reviewed. "
    "Use saved-record tools or re-read a smaller source range for full details.]\n"
)


def size(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def excerpt(text, limit):
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    room = max(0, limit - len(NOTICE.encode()))
    first = room * 3 // 4
    last = room - first
    return raw[:first].decode("utf-8", errors="ignore") + NOTICE + (
        raw[-last:].decode("utf-8", errors="ignore") if last else "")


def fit(value):
    """Keep policy, schemas, current question and latest complete call/result group."""
    result = copy.deepcopy(value)
    if size(result) <= MAX_PROMPT_BYTES or os.environ.get("AIMATE_LOCAL_PROMPT_COMPACTION") == "0":
        return result
    rows = result["messages"]
    question = max((i for i, row in enumerate(rows) if row["role"] == "user"), default=0)
    # Only remove preceding history; keep every byte of the current question.
    if question > 1:
        old = "\n\n".join(row.get("content", "") for row in rows[1:question]
                        if row["role"] in {"user", "assistant"} and row.get("content"))
        result["messages"] = rows = [rows[0], {
            "role": "user", "content": "Earlier conversation reference; may be stale:\n" + excerpt(old, 2000)
        }, *rows[question:]]
        question = 2
    if size(result) <= MAX_PROMPT_BYTES:
        return result
    for limit in (8000, 2000, 700):
        for row in rows:
            if row["role"] == "tool":
                row["content"] = excerpt(row.get("content", ""), limit)
        if size(result) <= MAX_PROMPT_BYTES:
            return result
    # Drop completed older rounds together, never orphan the newest calls/results.
    latest = max((i for i, row in enumerate(rows) if row.get("tool_calls")), default=question + 1)
    if latest > question + 1:
        older = "\n\n".join(row.get("content", "") for row in rows[question + 1:latest]
                           if row["role"] == "assistant" and row.get("content"))
        result["messages"] = [*rows[:question + 1], {
            "role": "assistant", "content": "Earlier local steps omitted; their evidence must be re-read.\n" + excerpt(older, 1500)
        }, *rows[latest:]]
    return result
