"""Optional, explicit completion checkpoints; never certify factual correctness."""
import os


def enabled():
    return os.environ.get("AIMATE_COMPLETION_CHECKPOINT_ENABLED") != "0"


def reason(round_no, calls, stop_reason=None, final_text=True):
    if not enabled():
        return None
    if stop_reason == "max_tokens":
        return "output_limit"
    if calls and round_no == 8:
        return "tool_limit"
    if not calls and not final_text:
        return "empty_answer"
    return None


def checkpoint(reason_code, quality):
    message = {
        "output_limit": "The answer reached the output limit.",
        "tool_limit": "The investigation reached its lookup limit.",
        "empty_answer": "The model returned no final answer.",
    }[reason_code]
    note = message + " This investigation is incomplete. Ask Continue to resume from saved evidence; unverified findings remain unresolved."
    assessment = quality.metadata()
    if assessment is not None:
        assessment = {**assessment, "assessed": False, "coverage": "partial",
                      "further_investigation": True, "accuracy_percent": None,
                      "completion_percent": None, "next_step": "Continue the unfinished investigation.",
                      "gaps": list(dict.fromkeys([message, *assessment.get("gaps", [])]))[:6]}
    return {"status": "incomplete", "reason": reason_code, "notice": note}, assessment
