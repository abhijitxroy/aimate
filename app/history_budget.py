"""Reduce historical evidence tokens while retaining full saved records and call IDs."""
import json

MAX_HISTORY = 60000


def compact(turn, ident):
    for message in turn:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            candidates = [(block, "content")] if block.get("type") == "tool_result" else []
            if block.get("type") == "responses":
                candidates += [(item, "output") for item in block.get("items", [])
                               if item.get("type") == "function_call_output"]
            for item, field in candidates:
                value = item.get(field)
                if isinstance(value, str) and len(value) > 2400:
                    item[field] = (value[:1700] + f"\n[Historical result excerpt. Full saved turn {ident} is available via read_saved_turn; re-read sources for current facts.]\n" + value[-400:])
    if len(json.dumps(turn)) > 40000:
        result = []
        for message in turn:
            content = message.get("content")
            if isinstance(content, str):
                result.append({"role": message["role"], "content": content[:12000]})
            elif message.get("role") == "assistant":
                text = "\n\n".join(block.get("text", "") for block in content or [] if block.get("type") == "text")
                if text:
                    result.append({"role": "assistant", "content": text[:12000]})
        return result
    return turn
