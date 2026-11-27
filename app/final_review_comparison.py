"""Deterministic report provenance, never model votes or factual certification."""
import copy
import json
import os


def unique(report):
    result = copy.deepcopy(report)
    if os.environ.get("AIMATE_FINAL_COMPARISON_ENABLED") == "0":
        return result
    seen, findings = set(), []
    for finding in result["findings"]:
        key = json.dumps(finding, sort_keys=True)
        if key not in seen:
            seen.add(key)
            findings.append(finding)
    result["findings"] = findings
    return result


def anchor(finding):
    return tuple(finding[key] for key in ("path", "commit", "line", "quote"))


def key(finding):
    claim = finding["claim"].strip()
    return (*anchor(finding), claim)


def compare(report, reviewers, lead_completed):
    if os.environ.get("AIMATE_FINAL_COMPARISON_ENABLED") == "0":
        return None
    lead_findings = unique(report)["findings"] if lead_completed else []
    lead_by_key = {key(finding): finding for finding in lead_findings}
    lead_anchors = {anchor(finding) for finding in lead_findings}
    groups, original_anchors = {}, set()
    incomplete = []
    for reviewer in reviewers:
        if not reviewer.get("report"):
            incomplete.append({"id": reviewer["id"], "name": reviewer["name"]})
            continue
        for finding in unique(reviewer["report"])["findings"]:
            ident = key(finding)
            original_anchors.add(anchor(finding))
            entry = groups.setdefault(ident, {
                "path": finding["path"], "commit": finding["commit"], "line": finding["line"],
                "quote": finding["quote"], "claim": finding["claim"], "reviewers": [],
            })
            entry["reviewers"].append({
                "id": reviewer["id"], "name": reviewer["name"], "severity": finding["severity"],
            })
    entries = []
    for ident, entry in groups.items():
        retained = lead_by_key.get(ident)
        entry["status"] = (
            "unresolved" if not lead_completed else "retained" if retained else
            "location_only" if ident[:4] in lead_anchors else "omitted"
        )
        entry["lead_severity"] = retained["severity"] if retained else None
        entry["severity_disagreement"] = len({
            row["severity"] for row in entry["reviewers"]
        } | ({retained["severity"]} if retained else set())) > 1
        entries.append(entry)
    for finding in lead_findings:
        if anchor(finding) not in original_anchors:
            entries.append({
                **{field: finding[field] for field in ("path", "commit", "line", "quote", "claim")},
                "reviewers": [], "status": "lead_only", "lead_severity": finding["severity"],
                "severity_disagreement": False,
            })
    counts = {status: sum(row["status"] == status for row in entries)
              for status in ("retained", "location_only", "omitted", "unresolved", "lead_only")}
    counts["severity_disagreements"] = sum(row["severity_disagreement"] for row in entries)
    return {"entries": entries, "counts": counts, "incomplete_reviewers": incomplete,
            "note": "Retained means the lead included the same cited claim, not that it is proven. "
                    "Location-only matches can describe different failures. Omission is not a rejection "
                    "as false. Disagreements require source review; model agreement is not evidence."}
