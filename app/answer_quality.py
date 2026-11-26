"""Optional answer assessments, distinct from independently measured accuracy."""
import os
import re

TOOL = {
    "name": "assess_answer",
    "description": (
        "Record a concise assessment of the final answer, after inspecting evidence. "
        "This is your assessment, not measured accuracy or certification. Do not guess "
        "percentages. For numerical badges provide checks of important claims against "
        "read evidence and a checklist covering every requested task. The server calculates "
        "the percentages. Never invent checks, evidence or completed work. "
        "Describe actual coverage, important gaps and further investigation. "
        "Do not include hidden reasoning. Call once before your final answer; update it "
        "if later evidence changes the conclusion."
    ),
    "input_schema": {"type": "object", "properties": {
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "basis": {"type": "string", "maxLength": 400},
        "coverage": {"type": "string", "enum": ["complete", "partial", "limited", "not_applicable"]},
        "gaps": {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 200}},
        "further_investigation": {"type": "boolean"},
        "next_step": {"type": "string", "maxLength": 300},
        "checks": {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {
            "claim": {"type": "string", "maxLength": 200},
            "supported": {"type": "boolean"},
            "source": {"type": "string", "maxLength": 500},
        }, "required": ["claim", "supported", "source"], "additionalProperties": False}},
        "work_items": {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {
            "task": {"type": "string", "maxLength": 200},
            "completed": {"type": "boolean"},
        }, "required": ["task", "completed"], "additionalProperties": False}},
    }, "required": ["confidence", "basis", "coverage", "gaps", "further_investigation", "next_step"],
        "additionalProperties": False},
}


def enabled():
    return os.environ.get("AIMATE_ANSWER_QUALITY_ENABLED") != "0"


def kind(question, style="auto"):
    if not enabled() or style == "plain":
        return None
    query = question.split("\n\nUntrusted attachment manifest", 1)[0][:6000]
    if style in {"review", "debug", "investigate"}:
        return {"review": "review", "debug": "analysis", "investigate": "analysis"}[style]
    for label, pattern in (
        ("review", r"\b(review|audit)\b"),
        ("design", r"\b(architecture|architectural|design)\b"),
        ("analysis", r"\b(analy[sz]\w*|investigat\w*|debug|diagnos\w*|root cause|triage)\b"),
        ("note", r"\b(technical|investigation|design|review)\s+notes?\b"),
        ("search", r"\b(search|look up|lookup)\b"),
    ):
        if re.search(pattern, query, re.I):
            return label
    return None


def instruction(answer_kind):
    if not answer_kind:
        return ""
    return (
        "\nBefore concluding this " + answer_kind + " answer, use assess_answer to record "
        "a short evidence-based assessment. Confidence is your qualitative assessment, "
        "not an accuracy score. Coverage describes the requested scope actually checked, "
        "not whether the code is correct. State missing evidence, uncertainty and a "
        "concrete next step when needed. Never mark partial/truncated reads complete. "
        "Include optional checks only for claims checked against sources actually read "
        "this turn, using their exact source identifiers. Include work_items covering "
        "all parts of the user request, with completed=false for unfinished verification. "
        "The accuracy badge estimates support within those checks, not guaranteed factual "
        "accuracy; do not claim a complete fix merely because code was proposed. "
        "The interface shows these details separately; do not repeat a long scorecard "
        "in the answer. Routine factual searches need only a concise source-accuracy "
        "assessment. Do not include private chain-of-thought."
    )


class Assessment:
    def __init__(self, answer_kind):
        self.kind = answer_kind
        self.value = None
        self.sources = set()
        self.failed_reads = 0

    def observe(self, name, result=None, failed=False):
        if name in {"api_read", "read_github_file", "read_pr_manifest", "read_attachment",
                    "find_repository_files", "search_repository_text", "read_requested_repository", "inspect_local_source"}:
            # Later evidence invalidates an earlier assessment; don't show it as final.
            self.value = None
            if failed:
                self.failed_reads += 1
            elif isinstance(result, dict) and isinstance(result.get("source"), str):
                self.sources.add(result["source"])

    def record(self, args):
        required = set(TOOL["input_schema"]["required"])
        if not self.kind or not isinstance(args, dict) or not required <= set(args) or set(args) - required - {"checks", "work_items"}:
            raise ValueError("Provide the answer assessment fields only.")
        if not isinstance(args["confidence"], str) or not isinstance(args["coverage"], str) or args["confidence"] not in {"high", "medium", "low"} or args["coverage"] not in {
                "complete", "partial", "limited", "not_applicable"}:
            raise ValueError("Choose a valid confidence and coverage.")
        for key, maximum in (("basis", 400), ("next_step", 300)):
            if not isinstance(args[key], str) or len(args[key]) > maximum or "\0" in args[key]:
                raise ValueError("Use concise assessment text.")
        if not args["basis"].strip() or type(args["further_investigation"]) is not bool:
            raise ValueError("Provide the evidence basis and an investigation boolean.")
        gaps = args["gaps"]
        if not isinstance(gaps, list) or len(gaps) > 6 or any(
                not isinstance(gap, str) or not gap.strip() or len(gap) > 200 or "\0" in gap for gap in gaps):
            raise ValueError("Use up to six concise coverage gaps.")
        if args["coverage"] == "complete" and gaps:
            raise ValueError("Coverage cannot be complete while requested evidence is missing.")
        if (gaps or args["coverage"] in {"partial", "limited"}) and not args["further_investigation"]:
            raise ValueError("Incomplete coverage needs further investigation.")
        if args["further_investigation"] and not args["next_step"].strip():
            raise ValueError("Describe the next investigation step.")
        for key, text_key, boolean_key in (("checks", "claim", "supported"), ("work_items", "task", "completed")):
            items = args.get(key, [])
            if not isinstance(items, list) or len(items) > 20:
                raise ValueError("Use up to twenty concise checklist items.")
            seen = set()
            for item in items:
                fields = {text_key, boolean_key} | ({"source"} if key == "checks" else set())
                if not isinstance(item, dict) or set(item) != fields:
                    raise ValueError("Provide only the checklist fields.")
                text = item[text_key]
                if not isinstance(text, str) or not text.strip() or len(text) > 200 or "\0" in text or text.strip().casefold() in seen:
                    raise ValueError("Use distinct concise checklist items.")
                seen.add(text.strip().casefold())
                if type(item[boolean_key]) is not bool:
                    raise ValueError("Checklist states must be booleans.")
                if key == "checks" and (not isinstance(item["source"], str) or item["source"] not in self.sources or len(item["source"]) > 500):
                    raise ValueError("Each accuracy check needs an exact source read this turn.")
            if key == "work_items" and items:
                unfinished = any(not item["completed"] for item in items)
                if (args["coverage"] == "complete" and unfinished) or (
                        args["coverage"] in {"partial", "limited"} and not unfinished):
                    raise ValueError("The task checklist must match coverage.")
        self.value = {**args, "gaps": list(gaps)}
        return {"recorded": True, "note": "Self-assessment recorded; accuracy is not independently measured."}

    def metadata(self):
        if not self.kind or not enabled():
            return None
        checks = (self.value or {}).get("checks", [])
        work = (self.value or {}).get("work_items", [])
        return {"version": 1, "kind": self.kind, "assessed": self.value is not None,
                "accuracy": "not_measured", "source_count": len(self.sources),
                "failed_reads": self.failed_reads, **(self.value or {}),
                "accuracy_percent": round(100 * sum(item["supported"] for item in checks) / len(checks)) if checks else None,
                "completion_percent": round(100 * sum(item["completed"] for item in work) / len(work)) if work else None}
