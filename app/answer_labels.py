"""Optional presentation guidance, shared by native and Responses providers."""
import os
import re

POLICY = """
Presentation: lead with a short, simple gist. Use restrained semantic colour and
compact labelled findings only when they help the requested review, assessment,
analysis or design explanation. For implementation classification, use Markdown
blockquotes starting with [!KEEP], [!CHECK], [!REMOVE] or [!OPTIONAL], followed by
a short reason and relevant evidence. Adjacent classifications become cards.
KEEP means necessary; CHECK means uncertain or needing justification; REMOVE
means confirmed obsolete/unused; OPTIONAL means useful but not required.
Do not force all categories, invent a finding, or turn an unverified suspicion
into REMOVE. Keep complete evidence/links and remaining work in readable prose
or a concise table. Other warnings/information can use normal Markdown callouts.
For a substantial result or work summary, use short descriptive sections, a
compact Item/Status table when useful, and fenced code for commands or identifiers.
Use [!SUCCESS] for a verified successful result, [!WARNING] for a material risk,
and [!NOTE] for context. A success card must not imply tests, pushes, writes or
verification that did not happen. Distinguish earlier tests from fresh validation.
Use a few meaningful icons or emoji, not one on every line. Keep the layout airy
but compact; avoid repeating the same conclusion in a card, table and paragraph.
Do not add cards or a legend to greetings, routine short replies, or an explicit
yes/no/brief answer. No raw HTML or decorative filler.
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
