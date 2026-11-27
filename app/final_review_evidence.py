"""A single read-only, commit-pinned source packet shared by every reviewer."""
import hashlib
import json
import re
from urllib.parse import urlsplit

from app.review import ReviewReader
from app.connectors import scrub

MAX_CHARACTERS = 180_000


def target(question, config):
    urls = re.findall(r"https?://[^\s<>\"()]+", question)
    matches = []
    host = urlsplit(config.get("github", {}).get("url", "")).hostname
    allowed = {"github.com", "api.github.com"} if host in {"api.github.com", "github.com"} else {host}
    for url in urls:
        parts = urlsplit(url.rstrip(".,"))
        match = re.fullmatch(r"/([^/]+/[^/]+)/pull/([1-9]\d*)/?", parts.path)
        if match and parts.hostname in allowed and not parts.username and not parts.password:
            matches.append((match[1], int(match[2])))
    return next(iter(set(matches))) if len(set(matches)) == 1 else None


async def collect(services, repo, pull, config, check):
    reader = ReviewReader(services)
    check()
    page, manifest = 1, None
    while page:
        check()
        result = await reader.manifest({"repo": repo, "pull": pull, "page": page})
        manifest = result["data"]
        if manifest["api_limit_reached"]:
            raise ValueError("The PR exceeds GitHub's changed-file API limit; complete review is unavailable.")
        page = manifest["next_page"]
        if len(reader.expected) > 80:
            raise ValueError("Final review currently supports up to eighty changed files. Split the review scope first.")
    if not reader.manifest_complete():
        raise ValueError("The PR file manifest is incomplete. No model review was started.")
    if len({key for values in reader.expected.values() for key in values}) > 100:
        raise ValueError("This PR requires more than one hundred source versions. Split the review scope first.")
    sources, total = [], 0
    for key in dict.fromkeys(key for values in reader.expected.values() for key in values):
        repo_name, path, commit = key
        check()
        args = {"repo": repo_name, "path": path, "ref": commit}
        while True:
            result = await reader.file(args)
            if result["data"]["read_complete"]:
                break
            args.update(start_line=result["data"]["next_line"],
                        start_column=result["data"]["next_column"])
        value = reader.files[key]
        source = {"path": path, "commit": commit, "sha256": hashlib.sha256(value["text"].encode()).hexdigest(),
                  "lines": value["text"].splitlines(), "url": result["source"]}
        total += len(json.dumps(source))
        if total > MAX_CHARACTERS:
            raise ValueError("This PR exceeds the final-review source packet limit. No partial packet was sent to models.")
        sources.append(source)
    check()
    metadata = await services.request("github", "GET", f"/repos/{repo}/pulls/{pull}")
    if metadata["head"]["sha"] != manifest["head_sha"] or metadata["base"]["sha"] != manifest["target_base_sha"]:
        raise ValueError("The PR moved while collecting source evidence. Retry against its new head.")
    coverage = reader.coverage()["data"]
    if not coverage["complete_pr_read"]:
        raise ValueError("Required changed-source coverage is incomplete. No model review was started.")
    packet = scrub({"repo": repo, "pull": pull, "head": manifest["head_sha"],
                    "base": manifest["base_sha"], "target_base": manifest["target_base_sha"],
                    "changed_files": manifest["changed_files"], "sources": sources,
                    "coverage": {key: coverage[key] for key in (
                        "manifest_complete", "source_count", "missing_source_count",
                        "complete_pr_read", "note")}}, config)
    for source in packet["sources"]:
        source["sha256"] = hashlib.sha256("\n".join(source["lines"]).encode()).hexdigest()
    packet["hash"] = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
    return packet


def validate_report(text, packet):
    """Validate citations structurally; this does not prove the claim is correct."""
    value = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
    if not isinstance(value, dict) or set(value) != {"summary", "findings", "gaps"}:
        raise ValueError("Reviewer report did not follow the evidence format.")
    if (not isinstance(value["summary"], str) or len(value["summary"]) > 3000
            or not isinstance(value["gaps"], list) or len(value["gaps"]) > 30
            or any(not isinstance(item, str) or len(item) > 2000 for item in value["gaps"])
            or not isinstance(value["findings"], list) or len(value["findings"]) > 30):
        raise ValueError("Reviewer report exceeds its limits.")
    sources = {(s["path"], s["commit"]): s for s in packet["sources"]}
    for finding in value["findings"]:
        if not isinstance(finding, dict) or set(finding) != {"severity", "path", "commit", "line", "quote", "claim", "scenario", "suggestion"}:
            raise ValueError("Reviewer finding is missing evidence fields.")
        if (any(not isinstance(finding[k], str) or len(finding[k]) > 3000
                for k in ("severity", "path", "commit", "quote", "claim", "scenario", "suggestion"))
                or finding["severity"] not in {"P0", "P1", "P2", "P3"}):
            raise ValueError("Reviewer finding has invalid fields.")
        source = sources.get((finding["path"], finding["commit"]))
        line = finding["line"]
        if (not source or type(line) is not int or not 1 <= line <= len(source["lines"])
                or not finding["quote"].strip() or finding["quote"] not in source["lines"][line - 1]):
            raise ValueError("Reviewer cited a line/quote outside the shared source snapshot.")
    return value
