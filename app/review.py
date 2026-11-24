"""Pinned GitHub source paging and explicit read coverage for large reviews."""
import base64
import binascii
import json
import hashlib
import re
from urllib.parse import quote

from app.validation import clean_path, number

TOOLS = [
    {"name": "read_github_file", "description": (
        "Read scoped GitHub code by line range without silently cutting off the file. "
        "Use a commit SHA from the PR manifest for stable evidence. Follow next_line/next_column "
        "until complete. Long lines are continued by column; returned line numbers are 1-based."),
     "input_schema": {"type": "object", "properties": {
         "repo": {"type": "string"}, "path": {"type": "string"}, "ref": {"type": "string"},
         "start_line": {"type": "integer", "minimum": 1},
         "end_line": {"type": "integer", "minimum": 1,
                      "description": "Read at most 200 lines; omit to use the default page."},
         "start_column": {"type": "integer", "minimum": 0}},
         "required": ["repo", "path", "ref"], "additionalProperties": False}},
    {"name": "read_pr_manifest", "description": (
        "Read a compact page of PR changed files, pinned head/base commits and required review sources. "
        "Follow next_page until manifest_complete. Read added files at head, removed files at base, "
        "and both versions of modified/renamed files using read_github_file."),
     "input_schema": {"type": "object", "properties": {
         "repo": {"type": "string"}, "pull": {"type": "integer", "minimum": 1},
         "page": {"type": "integer", "minimum": 1},
         "reset": {"type": "boolean", "description": "Start an independent review at page 1; clear derived prior coverage."}},
         "required": ["repo", "pull"], "additionalProperties": False}},
    {"name": "review_coverage", "description": (
        "Report the current turn's actual file-reading coverage and missing PR pages/files. "
        "A complete source read is not proof that the code is correct. Report gaps before a verdict."),
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def file_path(value):
    if not isinstance(value, str) or not value or len(value) > 1000 or value.startswith("/"):
        raise ValueError("Use a repository-relative file path.")
    clean_path("/" + quote(value, safe="/"))
    return value


def integer(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"Invalid {label}.")
    return value


def merged_size(ranges):
    end, total = 0, 0
    for start, stop in sorted(ranges):
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def first_unread(ranges, total):
    cursor = 0
    for start, stop in sorted(ranges):
        if start > cursor:
            break
        cursor = max(cursor, stop)
    return min(cursor, total)


class ReviewReader:
    def __init__(self, services, progress=None):
        self.services = services
        self.files = {}
        self.pull = None
        self.expected = {}
        self.pages = {}
        self.changed_files = None
        self.manifest_checked = False
        self.prior = {}
        if progress:
            self.pull = tuple(progress["pull"]) if progress.get("pull") else None
            self.expected = {name: [tuple(key) for key in keys] for name, keys in progress["expected"].items()}
            self.pages = {int(page): count for page, count in progress["pages"].items()}
            self.changed_files = progress["changed_files"]
            self.prior = {tuple(value["key"]): value for value in progress["files"]}

    async def file(self, args):
        repo = self.services.repo(args.get("repo"))
        path = file_path(args.get("path"))
        commit = args.get("ref")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            raise ValueError("Use an exact 40-character commit SHA; obtain it from the PR manifest or commits API.")
        commit = commit.lower()
        start = integer(args.get("start_line", 1), 1, 10_000_000, "start line")
        stop = integer(args.get("end_line", start + 199), start, start + 199, "end line")
        column = integer(args.get("start_column", 0), 0, 2_000_000, "start column")
        key = (repo, path, commit)
        api_path = f"/repos/{repo}/contents/{quote(path, safe='/')}"
        if key not in self.files:
            if len(self.files) >= 100 or sum(len(v["text"]) for v in self.files.values()) >= 8_000_000:
                raise ValueError("This turn's review cache is full. Continue the review in another turn.")
            data = await self.services.request("github", "GET", api_path, params={"ref": commit})
            if (not isinstance(data, dict) or data.get("type", "file") != "file"
                    or data.get("encoding") != "base64" or not isinstance(data.get("content"), str)):
                raise ValueError("The contents API did not return readable file data. This source remains unread.")
            try:
                raw = base64.b64decode("".join(data["content"].split()), validate=True)
                if len(raw) > 1_400_000 or b"\0" in raw:
                    raise ValueError("File is binary or exceeds the supported 1.4 MB source limit.")
                text = raw.decode("utf-8")
            except (KeyError, binascii.Error, UnicodeError):
                raise ValueError("File is not valid UTF-8 source content.") from None
            if self.services.public_policy:
                self.services.public_policy.text(text)
            lines = text.splitlines(keepends=True) or [""]
            offsets, position = [], 0
            for line in lines:
                offsets.append(position)
                position += len(line)
            self.files[key] = {"text": text, "lines": lines, "offsets": offsets, "ranges": [],
                               "blob_sha": data.get("sha"), "size": len(raw)}
            prior = self.prior.get(key)
            if prior and prior["blob_sha"] == data.get("sha") and prior["total_characters"] == len(text):
                self.files[key]["ranges"] = prior["ranges"]
        value = self.files[key]
        if start > len(value["lines"]) or column > len(value["lines"][start - 1]):
            raise ValueError("Requested line/column is outside the file.")
        begin = value["offsets"][start - 1] + column
        requested_end = (value["offsets"][stop] if stop < len(value["lines"]) else len(value["text"]))
        end = min(requested_end, begin + 12000)
        base = self.services.section("github")["url"].rstrip("/")
        def result():
            next_line = next_column = None
            cursor = first_unread(value["ranges"] + [(begin, end)], len(value["text"]))
            if cursor < len(value["text"]):
                import bisect
                index = bisect.bisect_right(value["offsets"], cursor) - 1
                next_line, next_column = index + 1, cursor - value["offsets"][index]
            return {"source": base + api_path + "?ref=" + commit,
                "data": {"repo": repo, "path": path, "commit": commit,
                         "blob_sha": value["blob_sha"], "total_lines": len(value["lines"]),
                         "start_line": start, "start_column": column,
                         "text": value["text"][begin:end], "next_line": next_line,
                         "next_column": next_column, "end_of_file": end == len(value["text"]),
                         "complete": cursor == len(value["text"]),
                         "read_complete": merged_size(value["ranges"] + [(begin, end)]) == len(value["text"])}}
        output = result()
        while len(json.dumps(output, ensure_ascii=False)) > 20000:
            if end - begin <= 1:
                raise ValueError("File metadata exceeds the tool output limit.")
            end = begin + (end - begin) // 2
            output = result()
        value["ranges"].append((begin, end))
        value["next_line"], value["next_column"] = output["data"]["next_line"], output["data"]["next_column"]
        return output

    async def manifest(self, args):
        repo = self.services.repo(args.get("repo"))
        pull = number(args.get("pull"))
        page = integer(args.get("page", 1), 1, 600, "manifest page")
        if type(args.get("reset", False)) is not bool or (args.get("reset") and page != 1):
            raise ValueError("Reset is a boolean and applies only to manifest page 1.")
        path = f"/repos/{repo}/pulls/{pull}"
        metadata = await self.services.request("github", "GET", path)
        head, target_base = metadata["head"]["sha"], metadata["base"]["sha"]
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) for value in (head, target_base)):
            raise ValueError("PR commit metadata is invalid.")
        comparison = await self.services.request("github", "GET",
            f"/repos/{repo}/compare/{target_base}...{head}", params={"per_page": 1})
        base = comparison["merge_base_commit"]["sha"]
        if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
            raise ValueError("PR merge-base metadata is invalid.")
        identity = (repo, pull, head, base)
        if args.get("reset") or (self.pull is not None and identity != self.pull):
            if page != 1:
                raise ValueError("PR changed. Restart at manifest page 1 for consistent review coverage.")
            self.expected, self.pages, self.files, self.prior = {}, {}, {}, {}
        self.pull = identity
        rows = await self.services.request("github", "GET", path + "/files",
                                           params={"page": page, "per_page": 5})
        after = await self.services.request("github", "GET", path)
        if after["head"]["sha"] != head or after["base"]["sha"] != target_base:
            self.manifest_checked = False
            raise ValueError("PR changed while reading its manifest; refresh page 1.")
        if not isinstance(rows, list):
            raise ValueError("PR files response is invalid.")
        files, expected = [], {}
        for row in rows:
            name = file_path(row["filename"])
            previous = file_path(row.get("previous_filename", name))
            status = row["status"]
            required = []
            if status != "removed":
                required.append((repo, name, head))
            if status != "added":
                required.append((repo, previous, base))
            expected[name] = required
            files.append({"path": name, "previous_path": previous, "status": status,
                          "additions": row.get("additions"), "deletions": row.get("deletions"),
                          "sources": [{"path": key[1], "ref": key[2]} for key in required]})
        if len(json.dumps(files, ensure_ascii=False)) > 18000:
            raise ValueError("PR filenames exceed the manifest output limit; coverage remains incomplete.")
        self.expected.update(expected)
        self.pages[page] = len(rows)
        self.changed_files = metadata["changed_files"]
        self.manifest_checked = True
        complete = self.manifest_complete()
        return {"source": self.services.section("github")["url"].rstrip("/") + path,
                "data": {"head_sha": head, "base_sha": base, "target_base_sha": target_base,
                         "changed_files": self.changed_files,
                         "files": files, "manifest_complete": complete,
                         "next_page": None if complete or len(rows) < 5 or page == 600 else page + 1,
                         "api_limit_reached": self.changed_files > 3000}}

    def manifest_complete(self):
        return (self.manifest_checked and self.pull is not None and len(self.expected) == self.changed_files
                and all(page in self.pages for page in range(1, max(self.pages, default=0) + 1)))

    def progress(self):
        files = dict(self.prior)
        files.update({key: {"key": list(key), "blob_sha": value["blob_sha"],
                            "total_characters": len(value["text"]), "ranges": value["ranges"],
                            "next_line": value.get("next_line"), "next_column": value.get("next_column")}
                      for key, value in self.files.items()})
        return {"pull": self.pull, "expected": self.expected, "pages": self.pages,
                "changed_files": self.changed_files, "files": list(files.values())}

    def coverage(self):
        observed = {tuple(value["key"]): value for value in self.progress()["files"]}
        files = [{"repo": key[0], "path": key[1], "commit": key[2],
                  "read_characters": merged_size(value["ranges"]), "total_characters": value["total_characters"],
                  "read_complete": merged_size(value["ranges"]) == value["total_characters"]}
                 for key, value in observed.items()]
        missing = [{"repo": key[0], "path": key[1], "commit": key[2],
                    "next_line": observed.get(key, {}).get("next_line") or 1,
                    "next_column": observed.get(key, {}).get("next_column") or 0}
                   for required in self.expected.values() for key in required
                   if key not in observed or merged_size(observed[key]["ranges"]) != observed[key]["total_characters"]]
        return {"data": {"manifest_complete": self.manifest_complete(),
                         "source_count": len(files), "missing_source_count": len(missing),
                         "complete_pr_read": self.manifest_complete() and not missing,
                         "files": files[:5], "missing_sources": missing[:5],
                         "note": "Read coverage only; never a correctness or test verdict."}}


async def read(services, name, args, store=None, cid=None):
    fingerprint = hashlib.sha256(json.dumps(services.config.get("github", {}), sort_keys=True).encode()).hexdigest()
    persistent = store is not None and not store.config().get("_private")
    if not hasattr(services, "_review_reader") or getattr(services, "_review_fingerprint", None) != fingerprint:
        progress = None
        if persistent:
            rows = store.rows("SELECT encrypted FROM review_sessions WHERE conversation=? AND fingerprint=?",
                              (cid, fingerprint))
            if not rows:
                rows = store.rows(
                    "SELECT r.encrypted FROM review_sessions r JOIN conversation_references c ON c.source=r.conversation "
                    "WHERE c.conversation=? AND r.fingerprint=?", (cid, fingerprint))
            if rows:
                progress = json.loads(store.cipher.decrypt(rows[0]["encrypted"].encode()))
        services._review_reader = ReviewReader(services, progress)
        services._review_fingerprint = fingerprint
    reader = services._review_reader
    if name == "read_github_file":
        result = await reader.file(args)
    elif name == "read_pr_manifest":
        result = await reader.manifest(args)
    else:
        result = reader.coverage()
    if persistent:
        store.execute("INSERT OR REPLACE INTO review_sessions VALUES (?,?,?)",
                      (cid, fingerprint, store.cipher.encrypt(json.dumps(reader.progress()).encode()).decode()))
    return result
