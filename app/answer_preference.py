"""Conversation-scoped brevity, stored in existing encrypted turn metadata."""
import json
import os
import re


def prepare(store, cid, question):
    rows = store.rows("SELECT u.metadata FROM turn_usage u JOIN turns t ON t.id=u.turn WHERE t.conversation=? ORDER BY t.id DESC LIMIT 1", (cid,))
    previous = json.loads(rows[0]["metadata"]).get("answer_preference", "normal") if rows else "normal"
    if previous not in {"brief", "normal"}:
        previous = "normal"
    if os.environ.get("AIMATE_ANSWER_PREFERENCE_ENABLED") == "0":
        return previous, ""
    # Only direct instructions in the user's leading question, never code,
    # quoted reference text or the appended untrusted attachment manifest.
    leading = question.split("\n\nUntrusted attachment manifest", 1)[0].splitlines()[:2]
    direct_lines = []
    for line in leading:
        if line.lstrip().startswith(("```", "~~~")):
            break
        if not line.lstrip().startswith(">"):
            direct_lines.append(line)
    direct = " ".join(direct_lines)
    brief = re.search(r"\b(?:keep (?:your |the )?(?:answers?|replies) (?:short|brief)|"
                      r"(?:answer|reply|respond) (?:only )?(?:yes\s*/\s*no|in (?:one|two|1|2)(?: or (?:two|2))? sentences?)|"
                      r"(?:only|just) (?:give|provide) (?:a )?(?:short|brief) (?:answer|reply)|"
                      r"do(?:n't| not) explain)\b", direct, re.I)
    normal = re.search(r"\b(?:explain in detail|give (?:me )?(?:a )?(?:full|detailed) (?:answer|explanation|review)|"
                       r"resume (?:normal|detailed) answers|stop (?:being brief|short answers))\b", direct, re.I)
    mode = "normal" if normal else "brief" if brief else previous
    base = "\nAnswer presentation: start with a short, simple gist. Include only relevant detail; use compact tables and optional evidence sections when helpful."
    if mode == "brief":
        base += "\nThe user requested short answers for this conversation: answer yes/no when sufficient, otherwise one or two plain sentences. This remains active until the user changes it. State any material uncertainty briefly; do not hide incomplete checks or invent certainty."
    return mode, base
