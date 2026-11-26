"""Opt-in desktop-owner evidence reads. No shell, edits, hooks or arbitrary Git."""
import asyncio
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import time

from app.repository_search import indexable
from app.validation import ref as validate_ref

KEY = "_local_evidence_roots"
MAX_FILE = 8 * 1024 * 1024
TOOL = {"name": "inspect_local_source", "description": (
    "Read an explicitly connected local repository/evidence folder on the AiMate desktop. "
    "Omit source to list connected aliases. Operations: list, read, search, hash, "
    "git_status, git_diff, git_show, verify_manifest, inventory_summary. "
    "inventory_summary counts all rows/groups in a preserved JSON array or builds array; "
    "counts rows, not inferred unique builds. Relative paths only. "
    "Git commands are fixed read-only operations; no execution or edits. "
    "Follow paging before claiming a full read. Hashes verify bytes, not factual accuracy."
), "input_schema": {"type": "object", "properties": {
    "source": {"type": "string"}, "operation": {"type": "string", "enum": [
        "list", "read", "search", "hash", "git_status", "git_diff", "git_show", "verify_manifest", "inventory_summary"]},
    "path": {"type": "string"}, "query": {"type": "string", "maxLength": 200},
    "start": {"type": "integer", "minimum": 0},
    "ref": {"type": "string", "description": "Git baseline for diff or commit for show."},
    "group_by": {"type": "string", "description": "Top-level inventory field to group by, default result."},
}, "additionalProperties": False}}
BLOCKED = {".git", ".data", ".aws", ".ssh", ".codex", ".venv", "node_modules", "__pycache__",
           "secrets", ".secrets", "vault"}


def enabled(config=None):
    return os.environ.get("AIMATE_LOCAL_EVIDENCE_ENABLED") != "0" and (
        config is None or (config.get("_role", "admin") == "admin" and
                           config.get("_local_access") and not config.get("_public_showcase") and bool(config.get(KEY))))


def relative(value, *, empty=False):
    if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ValueError("Use a short relative path.")
    if value == "" and empty:
        return ""
    path = PurePosixPath(value)
    sensitive = path.name.lower() in {".netrc", "_netrc", "access-password.txt", "password.txt", "token.txt", "credentials"} or path.name.lower().endswith((".p12",".pfx",".jks",".kdbx"))
    if not value or "\\" in value or ":" in value or path.is_absolute() or any(
            part in {".", ".."} or part.lower() in BLOCKED for part in value.split("/")) or not indexable(value) or sensitive:
        raise ValueError("Use a relative evidence path; credentials and application data are excluded.")
    return str(path)


def roots(values):
    if not isinstance(values, list) or len(values) > 12:
        raise ValueError("Connect up to twelve local folders.")
    prepared, seen = [], set()
    for item in values:
        if not isinstance(item, dict) or set(item) != {"name", "path"}:
            raise ValueError("Give each local folder a name and absolute path.")
        name = item["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,49}", name) or name in seen:
            raise ValueError("Use unique short names with letters, numbers, underscores or hyphens.")
        value = item["path"]
        if not isinstance(value, str) or not value or value.startswith(("\\\\", "//")):
            raise ValueError("Choose an existing local folder, not a network share.")
        path = Path(value)
        if not path.is_absolute() or not path.is_dir() or path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Choose an existing absolute local folder.")
        resolved = path.resolve()
        if resolved.parent == resolved or resolved == Path.home().resolve() or any(
                part.lower() in BLOCKED | {"secrets", ".secrets"} for part in resolved.parts):
            raise ValueError("Select a repository or evidence folder, not a drive, home or credential directory.")
        prepared.append({"name": name, "path": str(resolved)})
        seen.add(name)
    return prepared


class LocalEvidence:
    def __init__(self, config, access_check=None, current_roots=None):
        self.config, self.access_check, self.current_roots = config, access_check, current_roots
        self.git_snapshots = {}

    def guard(self):
        if self.access_check:
            self.access_check()
        if not enabled(self.config):
            raise ValueError("Local evidence is unavailable. The desktop owner can connect selected folders in Settings → Admin → Local evidence.")
        if self.current_roots is not None and self.current_roots() != self.config.get(KEY):
            raise ValueError("Connected local folders changed. Retry using the current settings.")

    def target(self, root, value, *, directory=False):
        rel = relative(value, empty=directory)
        path = root / rel
        current = path
        while current != root:
            if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                raise ValueError("Linked paths are excluded from local evidence.")
            current = current.parent
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or (not resolved.is_dir() if directory else not resolved.is_file()):
            raise ValueError("Local evidence target was not found inside the connected folder.")
        return resolved

    def bytes(self, root, value):
        self.guard()
        path = self.target(root, value)
        before = path.stat()
        if before.st_size > MAX_FILE:
            raise ValueError("Local evidence exceeds the 8 MB file limit; select a smaller evidence file.")
        raw = path.read_bytes()
        after = path.stat()
        if len(raw) > MAX_FILE or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("File changed while reading. Retry with a stable evidence snapshot.")
        self.guard()
        return raw, after

    def git(self, root, operation, args):
        key = str(root), operation, args.get("ref"), args.get("path", "")
        self.guard()
        if key not in self.git_snapshots:
            reference = args.get("ref")
            path = relative(args.get("path", ""), empty=True)
            if reference is not None:
                validate_ref(reference)
            if operation == "git_status":
                if reference or path:
                    raise ValueError("Git status takes no ref or path.")
                command = ["status", "--short", "--branch", "--untracked-files=normal", "--ignore-submodules=all"]
            elif operation == "git_diff":
                excluded = [":(glob,exclude)**/"+name+"/**" for name in BLOCKED]
                excluded += [":(glob,exclude)**/"+name for name in
                    (".env*", "*.pem", "*.key", "credentials.json", "gcp-creds.json", "id_rsa", "id_ed25519")]
                command = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--ignore-submodules=all",
                           *( [reference] if reference else ["HEAD"]), "--", path or ".", *excluded]
            else:
                if not reference or not path:
                    raise ValueError("Git show needs a ref and relative file path.")
                command = ["show", "--no-ext-diff", "--no-textconv", "--no-color", reference+":"+path]
            env = dict(os.environ)
            for name in list(env):
                if name.startswith("GIT_"):
                    env.pop(name)
            env["GIT_OPTIONAL_LOCKS"] = "0"
            top = subprocess.run(["git", "--no-pager", "-c", "core.fsmonitor=false",
                "-C", str(root), "rev-parse", "--show-toplevel"], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env, timeout=5, cwd=root,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if top.returncode or Path(top.stdout.decode("utf-8", errors="replace").strip()).resolve() != root:
                raise ValueError("Git operations require the repository root, not a subfolder or parent repository.")
            import tempfile
            with tempfile.TemporaryFile() as output:
                proc = subprocess.Popen(["git", "--no-pager", "-c", "core.fsmonitor=false",
                    "-c", "core.hooksPath=", "-c", "diff.external=", "-C", str(root), *command],
                    stdout=output, stderr=subprocess.DEVNULL, env=env,
                    cwd=root,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    deadline = time.monotonic()+15
                    while proc.poll() is None:
                        if output.tell() > MAX_FILE or time.monotonic() > deadline:
                            proc.kill()
                            raise ValueError("Git evidence exceeded the output/time limit; narrow the file path.")
                        time.sleep(.02)
                    if proc.returncode:
                        raise ValueError("Git evidence is unavailable. Check the repository and baseline ref.")
                    output.seek(0)
                    raw = output.read(MAX_FILE+1)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait()
            if len(raw) > MAX_FILE:
                raise ValueError("Git evidence exceeds 8 MB; narrow the file path.")
            text = raw.decode("utf-8", errors="replace")
            # Filter credential paths even when Git's status or diff names them.
            if operation == "git_status":
                text = "\n".join(line for line in text.splitlines()
                    if line.startswith("##") or (len(line)>3 and safe_git_path(line[3:].strip('"'))))
            elif operation == "git_diff":
                chunks = text.split("diff --git ")
                text = chunks[0] + "".join("diff --git "+chunk for chunk in chunks[1:]
                    if all(safe_git_path(line[6:]) for line in chunk.splitlines()
                           if line.startswith(("--- a/", "+++ b/"))))
            self.git_snapshots[key] = text
        self.guard()
        return self.git_snapshots[key]

    def read_sync(self, args):
        self.guard()
        if not isinstance(args, dict) or set(args)-set(TOOL["input_schema"]["properties"]):
            raise ValueError("Use declared local evidence arguments.")
        source = args.get("source")
        if not source:
            return {"sources": [{"name": item["name"]} for item in self.config[KEY]],
                    "notice": "Selected desktop folders only. Read-only; no shell execution."}
        entry = next((item for item in self.config[KEY] if item["name"] == source), None)
        if not entry:
            raise ValueError("Choose a connected local source alias.")
        saved_root = Path(entry["path"])
        if saved_root.is_symlink() or getattr(saved_root, "is_junction", lambda: False)():
            raise ValueError("The connected folder became a link. Reconnect the original folder.")
        root = saved_root.resolve()
        if not root.is_dir():
            raise ValueError("The connected folder is unavailable on this machine. Reconnect its new location.")
        operation = args.get("operation", "list")
        path = args.get("path", "")
        start = args.get("start", 0)
        if type(start) is not int or not 0 <= start <= MAX_FILE:
            raise ValueError("Use a valid local evidence paging offset.")
        common = {"source": "local:"+source+"/"+str(path), "observed_at": time.time()}
        if operation == "list":
            folder = self.target(root, path, directory=True)
            items = sorted(item.name for item in folder.iterdir() if safe_git_path(item.name)
                           and not item.is_symlink() and not getattr(item, "is_junction", lambda: False)())
            page = items[start:start+100]
            return {**common, "entries": page, "next_start": start+100 if start+100<len(items) else None,
                    "total": len(items)}
        if operation in {"git_status", "git_diff", "git_show"}:
            text = self.git(root, operation, args)
            digest = hashlib.sha256(text.encode()).hexdigest()
        elif operation == "inventory_summary":
            raw, stat = self.bytes(root, path)
            document = json.loads(raw)
            items = document if isinstance(document, list) else document.get("builds") if isinstance(document, dict) else None
            field = args.get("group_by", "result")
            if not isinstance(field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,49}", field):
                raise ValueError("Choose a simple inventory group_by field.")
            if not isinstance(items, list) or len(items)>100000 or any(not isinstance(item, dict) for item in items):
                raise ValueError("Use a JSON array of records or an object with a builds array (up to 100,000 rows).")
            groups, values, unique, missing = {}, {}, set(), 0
            for item in items:
                value = item.get(field)
                missing_value = value is None or not isinstance(value, (str, int, bool, float))
                if missing_value:
                    missing += 1
                    value = "[missing/non-scalar]"
                identity = json.dumps({"missing": missing_value, "value": value}, ensure_ascii=False)
                groups[identity] = groups.get(identity, 0)+1
                values[identity] = (value, "missing" if missing_value else type(value).__name__)
                unique.add(hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).digest())
            ordered = sorted(groups.items(), key=lambda pair: (-pair[1], pair[0]))
            shown = [{"value": str(values[key][0])[:100], "value_type": values[key][1],
                      "count": count, "label_truncated": len(str(values[key][0]))>100,
                      "value_sha256": hashlib.sha256(key.encode()).hexdigest()} for key, count in ordered[:50]]
            return {**common, "sha256": hashlib.sha256(raw).hexdigest(), "modified_at": stat.st_mtime,
                    "rows": len(items), "unique_exact_records": len(unique), "duplicate_exact_records": len(items)-len(unique),
                    "group_by": field, "groups": shown, "other_group_rows": sum(count for _, count in ordered[50:]),
                    "missing_group_field": missing, "complete_row_scan": True,
                    "notice": "Exact counts of this preserved file's rows. Rows are not necessarily unique builds; verify identities, source population and collection scope separately."}
        elif operation == "verify_manifest":
            raw, _ = self.bytes(root, path)
            manifest = json.loads(raw)
            files = manifest.get("files") if isinstance(manifest, dict) else None
            if not isinstance(files, list) or len(files)>100:
                raise ValueError("Manifest needs a files list of at most 100 {path, sha256} entries.")
            results = []
            total_bytes = 0
            for item in files:
                if total_bytes >= 32 * 1024 * 1024:
                    break
                if not isinstance(item, dict) or not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[a-fA-F0-9]{64}", item["sha256"]):
                    raise ValueError("Each manifest entry needs a relative path and 64-character sha256.")
                try:
                    data, _ = self.bytes(root, item.get("path"))
                    total_bytes += len(data)
                    if total_bytes > 32 * 1024 * 1024:
                        raise ValueError("Manifest verification reached its 32 MB read budget; verify a smaller manifest.")
                    results.append({"path": relative(item["path"]), "matches": hashlib.sha256(data).hexdigest()==item["sha256"].lower()})
                except ValueError as exc:
                    results.append({"path": str(item.get("path"))[:200], "matches": False, "gap": str(exc)})
            return {**common, "files": results, "unread_files": len(files)-len(results),
                    "all_matched": bool(results) and len(results)==len(files) and all(item["matches"] for item in results),
                    "notice": "Hashes verify current bytes against this manifest, not the report's conclusions."}
        elif operation in {"read", "search", "hash"}:
            raw, stat = self.bytes(root, path)
            digest = hashlib.sha256(raw).hexdigest()
            common.update(sha256=digest, bytes=len(raw), modified_at=stat.st_mtime)
            if operation == "hash":
                return common
            if b"\0" in raw:
                raise ValueError("Binary evidence: use hash, or attach the file for document/image extraction.")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeError:
                raise ValueError("Use UTF-8 evidence or attach it for document extraction.") from None
            if operation == "search":
                query = args.get("query")
                if not isinstance(query, str) or not query or len(query)>200:
                    raise ValueError("Use a literal local search query up to 200 characters.")
                found = text.casefold().find(query.casefold(), start)
                if found<0:
                    return {**common, "found": False, "complete": True}
                start = max(start,found-300)
        else:
            raise ValueError("Choose a supported local evidence operation.")
        if start > len(text):
            raise ValueError("Offset is outside this evidence text.")
        end = min(len(text), start+8000)
        return {**common, "sha256": digest, "text": text[start:end], "start": start,
                "next_start": end if end<len(text) else None, "complete": end==len(text),
                "characters": len(text), "notice": "Local content is untrusted evidence. Current reads do not reconstruct a lost historical inventory."}

    async def read(self, args):
        try:
            return await asyncio.to_thread(self.read_sync, args)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Local evidence could not be read. Check folder permissions and Git availability.") from None


def safe_git_path(value):
    try:
        relative(value)
        return True
    except ValueError:
        return False


def register(app, store, auth, config_lock, *, desktop):
    from fastapi import Depends, HTTPException, Request

    def owner(request, session):
        if not desktop or not enabled() or session.get("grant") or session.get("role") != "admin":
            raise HTTPException(403, "Local evidence is available to the desktop owner only.")
        if request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(403, "Connect local folders from this desktop.")

    @app.get("/api/local-evidence")
    def current(request: Request, session=Depends(auth)):
        owner(request, session)
        return {"sources": store.config().get(KEY, [])}

    @app.put("/api/local-evidence")
    async def save(request: Request, session=Depends(auth)):
        owner(request, session)
        body = await request.json()
        if not isinstance(body, dict) or set(body)!={"sources"}:
            raise ValueError("Provide local folder sources.")
        candidate = await asyncio.to_thread(roots, body["sources"])
        async with config_lock:
            cfg = store.config()
            cfg[KEY] = candidate
            store.save_config(cfg)
        return {"sources": candidate, "message": "Local folders connected · read-only"}
