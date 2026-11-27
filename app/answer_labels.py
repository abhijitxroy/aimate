"""Optional presentation guidance, shared by native and Responses providers."""
import os
import re

POLICY = """
Presentation: short, simple gist; semantic colour only when useful.
For classifications use Markdown blockquotes beginning [!KEEP],
[!CHECK], [!REMOVE] or [!OPTIONAL], with a short reason and evidence. Adjacent
classifications become cards. KEEP=necessary; CHECK=uncertain;
REMOVE=confirmed obsolete/unused; OPTIONAL=useful but not required.
Do not force all categories, invent findings or turn an unverified suspicion into
REMOVE. Preserve evidence/links and remaining work in readable prose or a table.
Work summaries: short sections, an Item/Status table when useful and fenced code.
Use [!SUCCESS] for
verified success, [!WARNING] for material risks and [!NOTE] for context.
A success card must not imply tests, pushes, writes or verification that did not
happen. Distinguish earlier tests from fresh validation.
Use a few meaningful icons/emoji; avoid one on every line and repeated conclusions.
No cards or legend for greetings, routine short replies or explicit yes/no/brief
answers. No raw HTML or decorative filler.
"""


def instruction(question, mode):
    if os.environ.get("AIMATE_ANSWER_LABELS_ENABLED") == "0" or mode == "plain":
        return ""
    if mode not in {"auto", "review", "debug", "investigate"}:
        return ""
    text = question.split("\n\nUntrusted attachment manifest", 1)[0]
    if mode == "auto" and not re.search(
            r"\b(review|audit|analy[sz]\w*|assess\w*|classif\w*|design|architecture|improv\w*|compar\w*|debug|investigat\w*|summari[sz]\w*|summary|status|deliver\w*|commit|push)\b",
            text, re.I):
        return ""
    return "\n" + POLICY
