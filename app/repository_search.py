"""Optional scoped, commit-pinned file discovery and literal content search."""
import base64
import binascii
import fnmatch
import json
import os
import re
from collections import OrderedDict
from urllib.parse import quote

from app.review import file_path
from app.validation import ref as validate_ref

SHA = re.compile(r"[0-9a-fA-F]{40}")
MAX_FILE = 1_400_000
MAX_CACHE = 8_000_000
MAX_RESULT = 14_000
COMMON = {
    "repo": {"type": "string"},
    "ref": {"type": "string", "description": "Branch/tag or pinned commit; omitted uses the current default branch."},
    "directory": {"type": "string", "description": "Optional repository-relative directory; narrow large trees."},
    "path_pattern": {"type": "string", "description": "Path glob, or a filename/path substring without glob characters."},
    "offset": {"type": "integer", "minimum": 0},
}
TOOLS = [
    {"name": "find_repository_files",
     "description": "Find file paths in a saved repository by glob or substring. Pins a commit. Follow next using its ref and offset; incomplete upstream trees are explicitly marked.",
     "input_schema": {"type": "object", "properties": {**COMMON,
         "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
         "required": ["repo", "path_pattern"], "additionalProperties": False}},
    {"name": "search_repository_text",
     "description": "Search UTF-8 file contents for a literal string in a saved repository, with line citations. Narrow directory/path_pattern first. Follow next exactly; gaps and partial searches are not full-repository coverage. Read matched files with read_github_file before a verdict.",
     "input_schema": {"type": "object", "properties": {**COMMON,
         "query": {"type": "string", "minLength": 1, "maxLength": 200},
         "case_sensitive": {"type": "boolean"},
         "start_line": {"type": "integer", "minimum": 1},
         "limit": {"type": "integer", "minimum": 1, "maximum": 20},
         "max_files": {"type": "integer", "minimum": 1, "maximum": 20}},
         "required": ["repo", "query", "path_pattern"], "additionalProperties": False}},
]


def enabled():
    return os.environ.get("AIMATE_REPOSITORY_SEARCH_ENABLED") != "0"


def integer(args, name, default, minimum, maximum):
    value = args.get(name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be {minimum}–{maximum}.")
    return value


def text(value, name, maximum):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f"Use a nonempty {name} up to {maximum} characters without control characters.")
    return value


def indexable(path):
    parts = path.lower().split("/")
    return not (any(p in {".git", "secrets", ".secrets"} for p in parts) or
                parts[-1].startswith(".env") or parts[-1].endswith((".pem", ".key")) or
                parts[-1] in {"id_rsa", "id_ed25519", "credentials.json", "gcp-creds.json"})


def matches(path, pattern):
    return (fnmatch.fnmatchcase(path, pattern) if any(c in pattern for c in "*?[")
            else pattern.casefold() in path.casefold())


class RepositorySearch:
    def __init__(self, services):
        self.services = services
        self.trees = {}
        self.refs = {}
        self.files = OrderedDict()
        self.cache_bytes = 0

    def scope(self, repo):
        if self.services.access_check:
            self.services.access_check()
        return self.services.repo(repo)

    async def get(self, repo, tail="", params=None):
        self.scope(repo)
        return await self.services.request("github", "GET", "/repos/" + repo + tail, params=params)

    async def commit(self, repo, ref):
        self.scope(repo)
        if ref is not None:
            validate_ref(ref)
        key = repo, ref
        if key in self.refs:
            return self.refs[key]
        if ref is not None:
            if SHA.fullmatch(ref):
                return ref.lower()
        else:
            metadata = await self.get(repo)
            ref = metadata.get("default_branch")
            validate_ref(ref)
        rows = await self.get(repo, "/commits", {"sha": ref, "per_page": 1})
        value = rows[0].get("sha") if isinstance(rows, list) and rows else None
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise ValueError("Repository ref did not resolve to a full commit SHA.")
        self.refs[key] = value.lower()
        return value.lower()

    async def tree(self, repo, commit, directory):
        key = repo, commit, directory
        self.scope(repo)
        if key not in self.trees:
            if len(self.trees) >= 24:
                raise ValueError("Search reached this turn's tree limit; narrow or continue in a new turn.")
            tree_sha = commit
            for part in directory.split("/") if directory else []:
                value = await self.get(repo, "/git/trees/" + tree_sha)
                if not isinstance(value, dict) or not isinstance(value.get("tree"), list):
                    raise ValueError("Repository tree returned an unsupported response.")
                if value.get("truncated"):
                    raise ValueError("Directory discovery is incomplete; a narrower source is required.")
                entry = next((row for row in value["tree"] if isinstance(row, dict) and row.get("path") == part and row.get("type") == "tree"), None)
                if not entry or not SHA.fullmatch(str(entry.get("sha", ""))):
                    raise ValueError("Search directory was not found at the pinned commit.")
                tree_sha = entry["sha"]
            value = await self.get(repo, "/git/trees/" + tree_sha, {"recursive": 1})
            if not isinstance(value, dict) or not isinstance(value.get("tree"), list):
                raise ValueError("Repository tree returned an unsupported response.")
            paths, excluded = {}, 0
            for row in value["tree"]:
                if not isinstance(row, dict):
                    raise ValueError("Repository tree contains unsupported entries.")
                if row.get("type") != "blob":
                    continue
                path = file_path((directory + "/" if directory else "") + row["path"])
                if not indexable(path) or row.get("mode") == "120000":
                    excluded += 1
                    continue
                size = row.get("size")
                paths[path] = {"path": path, "size": size if type(size) is int and size >= 0 else None}
            self.trees[key] = sorted(paths.values(), key=lambda row: row["path"]), bool(value.get("truncated")), excluded
        return self.trees[key]

    async def lines(self, repo, commit, path):
        key = repo, commit, path
        self.scope(repo)
        if key in self.files:
            self.files.move_to_end(key)
            if self.services.public_policy:
                self.services.public_policy.text("\n".join(self.files[key][0]))
            return self.files[key][0]
        value = await self.get(repo, "/contents/" + quote(path, safe="/"), {"ref": commit})
        if not isinstance(value, dict) or value.get("type") != "file" or value.get("encoding") != "base64":
            raise ValueError("Content is not an inline UTF-8 text file.")
        try:
            raw = base64.b64decode("".join(value["content"].split()), validate=True)
            if len(raw) > MAX_FILE:
                raise ValueError("Content exceeds the 1.4 MB source limit.")
            if b"\0" in raw:
                raise ValueError("Binary content was not searched.")
            decoded = raw.decode("utf-8")
            if self.services.public_policy:
                self.services.public_policy.text(decoded)
            lines = decoded.splitlines()
        except (KeyError, TypeError, binascii.Error, UnicodeError):
            raise ValueError("Content is not valid UTF-8 source.") from None
        self.files[key] = lines, len(raw)
        self.cache_bytes += len(raw)
        while self.cache_bytes > MAX_CACHE:
            _, (_, size) = self.files.popitem(last=False)
            self.cache_bytes -= size
        return lines

    async def read(self, name, args):
        if not enabled():
            raise ValueError("Repository search is disabled.")
        permitted = set(COMMON) | {"limit"}
        if name == "search_repository_text":
            permitted |= {"query", "case_sensitive", "start_line", "max_files"}
        elif name != "find_repository_files":
            raise ValueError("Unknown repository search tool.")
        if not isinstance(args, dict) or set(args) - permitted:
            raise ValueError("Use the declared repository-search arguments.")
        repo = self.scope(args.get("repo"))
        pattern = text(args.get("path_pattern"), "path pattern", 300)
        directory = args.get("directory", "")
        if directory:
            directory = file_path(directory)
        elif not isinstance(directory, str):
            raise ValueError("Use a repository-relative directory.")
        offset = integer(args, "offset", 0, 0, 100000)
        limit = integer(args, "limit", 20, 1, 20 if name == "search_repository_text" else 50)
        matcher, start, max_files = None, 1, 20
        if name == "search_repository_text":
            query = text(args.get("query"), "literal search string", 200)
            case = args.get("case_sensitive", False)
            if type(case) is not bool:
                raise ValueError("case_sensitive must be true or false.")
            matcher = re.compile(re.escape(query), 0 if case else re.IGNORECASE)
            start = integer(args, "start_line", 1, 1, 1400001)
            max_files = integer(args, "max_files", 20, 1, 20)
        commit = await self.commit(repo, args.get("ref"))
        paths, incomplete, excluded = await self.tree(repo, commit, directory)
        candidates = [row for row in paths if matches(row["path"], pattern)]
        if offset > len(candidates):
            raise ValueError("Search offset is outside the candidate list.")
        root = self.services.section("github")["url"].rstrip("/")
        result = {"repo": repo, "commit": commit, "directory": directory,
                  "tree_complete": not incomplete, "candidate_files": len(candidates),
                  "excluded_paths": excluded, "files_examined": 0, "matches": [], "gaps": [],
                  "next": None, "remaining_scope_complete": False,
                  "scope_started_at": {"offset": offset, "line": start},
                  "coverage": "Matched indexable regular files from this cursor; combine every page and its gaps.",
                  "note": "Search findings are leads. Read matched sources and verify applicability before a verdict."}
        if incomplete:
            result["gaps"].append({"reason": "Upstream tree is incomplete; narrow directory. Candidate count is partial."})
        cursor = offset
        if matcher is None:
            for row in candidates[offset:]:
                if len(result["matches"]) >= limit or len(json.dumps({**result, "matches": result["matches"] + [row]})) > MAX_RESULT:
                    break
                result["matches"].append(row)
                cursor += 1
            if cursor < len(candidates):
                result["next"] = {"ref": commit, "offset": cursor}
        else:
            read_bytes = 0
            for i in range(offset, min(len(candidates), offset + max_files)):
                row = candidates[i]
                if read_bytes >= 4_000_000:
                    break
                try:
                    if row["size"] is not None and row["size"] > MAX_FILE:
                        raise ValueError("Source exceeds the 1.4 MB file-search limit.")
                    lines = await self.lines(repo, commit, row["path"])
                    read_bytes += sum(len(line.encode("utf-8")) for line in lines)
                except ValueError as exc:
                    gap = {"path": row["path"], "reason": str(exc)[:300]}
                    if len(json.dumps({**result, "gaps": result["gaps"] + [gap]})) > MAX_RESULT:
                        result["next"] = {"ref": commit, "offset": i, "start_line": 1}
                        break
                    result["gaps"].append(gap)
                    cursor = i + 1
                    continue
                first = start if i == offset else 1
                if first > len(lines) + 1:
                    raise ValueError("Search start_line is outside the first candidate file.")
                result["files_examined"] += 1
                for j in range(first - 1, len(lines)):
                    match = matcher.search(lines[j])
                    if not match:
                        continue
                    begin = max(0, match.start() - 100)
                    found = {"path": row["path"], "line": j + 1,
                             "text": lines[j][begin:begin + 400],
                             "excerpt_start_column": begin,
                             "excerpt_truncated": begin > 0 or len(lines[j]) > begin + 400,
                             "url": root + "/repos/" + repo + "/contents/" + quote(row["path"], safe="/") + "?ref=" + commit}
                    if len(result["matches"]) >= limit or len(json.dumps({**result, "matches": result["matches"] + [found]})) > MAX_RESULT:
                        result["next"] = {"ref": commit, "offset": i, "start_line": j + 1}
                        break
                    result["matches"].append(found)
                if result["next"]:
                    break
                cursor = i + 1
            if result["next"] is None and cursor < len(candidates):
                result["next"] = {"ref": commit, "offset": cursor, "start_line": 1}
        result["remaining_scope_complete"] = result["next"] is None and not result["gaps"]
        result["full_scope_complete"] = offset == 0 and start == 1 and result["remaining_scope_complete"]
        if matcher:
            result["matched_lines_returned"] = len(result["matches"])
        return {"source": root + "/repos/" + repo + "/git/trees/" + commit, "data": result}


async def read(services, name, args):
    if not hasattr(services, "_repository_search"):
        services._repository_search = RepositorySearch(services)
    return await services._repository_search.read(name, args)
