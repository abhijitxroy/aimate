"""Scoped service clients and explicit write operations. No arbitrary URL/tool execution."""
import base64
import hashlib
import json
import re
import os
import ssl
from contextlib import asynccontextmanager
from urllib.parse import quote, unquote

import httpx

from app.validation import clean_path, number, ref, scoped_jql, valid_base

OPERATIONS = {
    "github": ["create_issue", "comment_issue", "update_issue", "create_branch",
               "write_file", "delete_file", "create_pull_request", "merge_pull_request"],
    "jira": ["create_issue", "comment_issue", "update_issue", "transition_issue", "delete_issue"],
    "jenkins": ["build_job", "abort_build"],
}
SECRET_KEYS = {"token", "api_key", "password", "authorization", "access_token", "secret",
               "client_secret", "private_key", "aws_secret_access_key", "refresh_token", "id_token",
               "aws_access_key", "aws_secret_key", "aws_session_token"}


def scrub(value, config):
    secrets = [v for section in config.values() if isinstance(section, dict)
               for k, v in section.items() if k in SECRET_KEYS and isinstance(v, str) and v]
    secrets.extend(config.get("_vault_secrets", []))

    def clean(item):
        if isinstance(item, dict):
            return {k: "[redacted]" if k.lower() in SECRET_KEYS else clean(v) for k, v in item.items()}
        if isinstance(item, list):
            return [clean(v) for v in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[redacted]")
            return re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
                          r"sk-ant-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b", "[redacted]", item)
        return item
    return clean(value)












class Services:
    def __init__(self, config, transport=None):
        self.config = config
        self.public_policy = None
        if config.get("_public_showcase") or os.environ.get("AIMATE_PUBLIC_SHOWCASE") == "1":
            from app.public_showcase import PublicPolicy
            self.public_policy = PublicPolicy()
            self.public_policy.validate(config)
        self.transport = transport
        self._reuse = False
        self._clients = {}
        self._tls = None

    def enable_reuse(self):
        self._reuse = True

    @asynccontextmanager
    async def http_client(self, service, **kwargs):
        if self._tls is None:
            self._tls = ssl.create_default_context() if os.name == "nt" else True
        kwargs["verify"] = self._tls
        if not self._reuse:
            async with httpx.AsyncClient(**kwargs) as client:
                yield client
            return
        if service not in self._clients:
            self._clients[service] = httpx.AsyncClient(**kwargs)
        yield self._clients[service]

    async def aclose(self):
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            await client.aclose()

    def section(self, service):
        if service not in OPERATIONS:
            raise ValueError("Unknown service")
        cfg = self.config.get(service, {})
        public_github = (service == "github" and cfg.get("url", "").rstrip("/") == "https://api.github.com"
                         and bool(cfg.get("repos")))
        if not cfg.get("token") and not public_github:
            raise ValueError(f"Configure the {service} token first")
        return cfg

    def repo(self, value):
        if value not in self.section("github").get("repos", []):
            raise ValueError("Repository is outside your configured scope")
        return value

    def issue(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*", value):
            raise ValueError("Use a Jira issue key, for example DEMO-123")
        if self.section("jira").get("access") != "all" and value.rsplit("-", 1)[0] not in self.section("jira").get("projects", []):
            raise ValueError("Jira issue is outside your configured projects")
        return value

    def job_path(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_. -]+(?:/[A-Za-z0-9_. -]+)*", value) or any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("Use a Jenkins job name, for example team/build")
        if self.section("jenkins").get("access") != "all" and value not in self.section("jenkins").get("jobs", []):
            raise ValueError("Jenkins job is outside your configured scope")
        return "".join("/job/" + quote(part, safe="") for part in value.split("/"))

    async def request(self, service, method, path, *, params=None, body=None, form=None):
        cfg = self.section(service)
        if method != "GET" and not cfg.get("token"):
            raise ValueError("Add a GitHub token with write access before preparing or executing changes")
        path = clean_path(path)
        base = valid_base(cfg["url"])
        headers = {"Accept": "application/json"}
        auth = None
        if service == "github":
            headers["User-Agent"] = "AiMate"
            if cfg.get("token"):
                headers["Authorization"] = "Bearer " + cfg["token"]
        elif service == "jira" and cfg.get("auth", "bearer") == "bearer":
            headers["Authorization"] = "Bearer " + cfg["token"]
        else:
            auth = httpx.BasicAuth(cfg.get("username", ""), cfg["token"])
        async with self.http_client(service, timeout=30, follow_redirects=False, transport=self.transport,
                                    headers=headers, auth=auth) as client:
            if service == "jenkins" and method != "GET":
                crumb = await client.get(base + "/crumbIssuer/api/json")
                if crumb.is_success:
                    c = crumb.json()
                    field = c.get("crumbRequestField", "")
                    if not re.fullmatch(r"[A-Za-z0-9-]+", field):
                        raise ValueError("Invalid Jenkins crumb header")
                    headers[field] = c["crumb"]
                elif crumb.status_code not in (403, 404):
                    raise ValueError(f"Jenkins crumb request returned HTTP {crumb.status_code}")
            async with client.stream(method, base + path, params=params, json=body, data=form, headers=headers) as r:
                if r.status_code >= 300:
                    # Do not echo response bodies: provider errors can contain credentials.
                    hint = {301: "API redirected; check the site URL and corporate network/proxy routing",
                            302: "API redirected to another page; check VPN/proxy routing and use the Jira API site URL",
                            303: "API redirected to sign-in; check the site URL and authentication method",
                            307: "API redirected; check the site URL and corporate network/proxy routing",
                            308: "API redirected; check the site URL and corporate network/proxy routing",
                            401: "token is invalid or expired",
                            403: "check token permissions, organization SSO approval and service access",
                            404: "target was not found or your token cannot see it",
                            429: "service rate limit reached; retry later"}.get(r.status_code, "check service availability and target")
                    if service == "github" and r.status_code == 404 and not cfg.get("token"):
                        hint = "target not found with public access; private repositories need a GitHub PAT with repository and organization access"
                    raise ValueError(f"{service}: HTTP {r.status_code}; {hint}")
                data, capped = bytearray(), False
                async for chunk in r.aiter_bytes():
                    remaining = 2_000_000 - len(data)
                    data.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        capped = True
                        break
                if r.headers.get("content-type", "").startswith("application/json"):
                    if capped:
                        raise ValueError("Response exceeds 2 MB; paginate or reduce fields/depth")
                    result = json.loads(data)
                else:
                    # Keep byte offsets accurate for progressive Jenkins log paging.
                    excerpt = bytes(data[:24_000])
                    result = {"text": excerpt.decode(r.encoding or "utf-8", errors="replace")}
                    if len(data) > 24_000 or capped:
                        result["truncated"] = True
                        result["note"] = "Use a narrower request or Jenkins logText/progressiveText with start to read further."
                    if "x-text-size" in r.headers:
                        result["next_start"] = (str(int((params or {}).get("start", 0)) + len(excerpt))
                                                if len(data) > 24_000 or capped else r.headers["x-text-size"])
                        result["more_data"] = len(data) > 24_000 or capped or r.headers.get("x-more-data", "").lower() == "true"
                location = r.headers.get("location")
                if location:
                    result = {"response": result, "location": location}
            if self.public_policy:
                self.public_policy.text(result)
            return scrub(result, self.config)

    async def read(self, service, path, params=None):
        """A flexible read API, restricted to known endpoint families and configured targets."""
        path = clean_path(path)
        params = dict(params or {})
        if len(params) > 20 or any(not isinstance(v, (str, int, bool)) for v in params.values()):
            raise ValueError("Query parameters must be simple strings/numbers")
        if service == "github":
            m = re.fullmatch(r"/repos/([^/]+/[^/]+)(?:/(.*))?", path)
            if not m:
                raise ValueError("GitHub reads must start with /repos/OWNER/REPO")
            self.repo(m[1])
            tail = m[2] or ""
            if not re.fullmatch(r"(?:|contents(?:/.*)?|git/trees/[^/]+|branches(?:/[^/]+)?|"
                                r"commits(?:/[^/]+)?|pulls(?:/[0-9]+(?:/(?:files|commits|comments|reviews))?)?|"
                                r"issues(?:/[0-9]+(?:/(?:comments|events))?)?|"
                                r"actions/runs(?:/[0-9]+(?:/jobs)?)?|actions/jobs/[0-9]+|"
                                r"compare/[^/]+|releases(?:/(?:latest|[0-9]+))?|"
                                r"commits/[^/]+/(?:check-runs|status)|tags)", tail):
                raise ValueError("That GitHub endpoint is not supported for reads")
            if "per_page" in params:
                params["per_page"] = max(1, min(100, int(params["per_page"])))
            else:
                params["per_page"] = 30
        elif service == "jira":
            cfg = self.section(service)
            m = re.fullmatch(r"/rest/api/(2|3)/issue/([A-Z][A-Z0-9_]*-[1-9][0-9]*)(?:/(comment|transitions|changelog|remotelink(?:/[0-9]+)?))?", path)
            if m:
                self.issue(m[2])
            elif re.fullmatch(r"/rest/api/(2|3)/search(?:/jql)?", path):
                projects = cfg.get("projects", [])
                if not projects and cfg.get("access") != "all":
                    raise ValueError("Add Jira projects first")
                params["jql"] = scoped_jql(params.pop("jql", ""), [] if cfg.get("access") == "all" else projects)
                params["maxResults"] = max(1, min(50, int(params.get("maxResults", 20))))
            elif re.fullmatch(r"/rest/api/(2|3)/project(?:/search)?", path) and cfg.get("access") == "all":
                params["maxResults"] = max(1, min(100, int(params.get("maxResults", 50))))
            elif re.fullmatch(r"/rest/api/(2|3)/project/([A-Z][A-Z0-9_]*)", path):
                if cfg.get("access") != "all" and path.rsplit("/", 1)[1] not in cfg.get("projects", []):
                    raise ValueError("Jira project is outside your configured scope")
            else:
                raise ValueError("Use Jira issue, remote links, project, transitions, comments or search endpoints")
        elif service == "jenkins":
            if "start" in params:
                try:
                    params["start"] = max(0, int(params["start"]))
                except (TypeError, ValueError):
                    raise ValueError("Jenkins log start must be a nonnegative byte offset") from None
            cfg = self.section(service)
            if cfg.get("access") == "all":
                # Account permissions govern job access; endpoint families remain restricted.
                match = re.fullmatch(r"((?:/job/[^/]+)+)/(api/json|(?:[1-9][0-9]*|lastBuild|lastCompletedBuild|lastSuccessfulBuild)/(?:api/json|consoleText|logText/progressiveText|wfapi/describe))", path)
                if path == "/api/json":
                    params["tree"] = "jobs[name,fullName,_class]"
                    params.pop("depth", None)
                elif match:
                    job = "/".join(unquote(part) for part in match[1].split("/job/")[1:])
                    if self.job_path(job) != match[1]:
                        raise ValueError("Use a canonical Jenkins job API path")
                else:
                    raise ValueError("Use Jenkins job/build APIs or /api/json to discover jobs")
            else:
                matched = None
                for job in cfg.get("jobs", []):
                    prefix = self.job_path(job)
                    if path == prefix + "/api/json" or re.fullmatch(
                            re.escape(prefix) + r"/(?:[1-9][0-9]*|lastBuild|lastCompletedBuild|lastSuccessfulBuild)/(?:api/json|consoleText|logText/progressiveText|wfapi/describe)", path):
                        matched = job
                        break
                if matched is None:
                    raise ValueError("Use a configured job/build /api/json or build /consoleText path")
        else:
            raise ValueError("Unknown service")
        result = await self.request(service, "GET", path, params=params)
        if service == "jira" and self.section("jira").get("access") != "all" and isinstance(result, dict) and isinstance(result.get("issues"), list):
            # Defence in depth against an upstream JQL parser behaving differently.
            projects = set(self.section("jira").get("projects", []))
            result = {**result, "issues": [issue for issue in result["issues"] if
                       str(issue.get("key", "")).rsplit("-", 1)[0] in projects]}
        # Decode normal GitHub file contents so the model can read code.
        if service == "github" and isinstance(result, dict) and result.get("encoding") == "base64":
            result = dict(result)
            try:
                result["text"] = base64.b64decode(result.pop("content")).decode("utf-8")[:24_000]
            except (ValueError, UnicodeError):
                result["text"] = "[binary file]"
        return {"source": self.section(service)["url"].rstrip("/") + path, "data": scrub(result, self.config)}

    def plan(self, service, operation, payload):
        """Validate and materialize exactly the request displayed on the confirmation card."""
        cfg = self.section(service)
        if not cfg.get("token"):
            raise ValueError("Add a GitHub token with write access before preparing changes")
        if operation not in OPERATIONS[service]:
            raise ValueError("Unsupported operation")
        p = dict(payload)
        body, form, method = None, None, "POST"
        if service == "github":
            repo = self.repo(p.get("repo"))
            base = "/repos/" + repo
            if operation == "create_issue":
                path, body = base + "/issues", self.fields(p, {"title", "body", "labels", "assignees"}, {"title"})
            elif operation == "comment_issue":
                path = base + f"/issues/{number(p.get('number'))}/comments"
                body = self.fields(p, {"body"}, {"body"})
            elif operation == "update_issue":
                method, path = "PATCH", base + f"/issues/{number(p.get('number'))}"
                body = self.fields(p, {"title", "body", "state", "labels", "assignees"}, set())
                if not body:
                    raise ValueError("Provide at least one issue field")
            elif operation == "create_branch":
                branch = ref(p.get("branch"))
                sha = p.get("sha", "")
                if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
                    raise ValueError("Provide a verified 40-character base commit SHA")
                path, body = base + "/git/refs", {"ref": "refs/heads/" + branch, "sha": sha}
            elif operation in {"write_file", "delete_file"}:
                file_path = p.get("path", "")
                clean_path("/" + file_path)
                if not file_path or file_path.startswith("/") or any(
                        part.lower() in {".env", ".aws", ".ssh"} for part in file_path.split("/")):
                    raise ValueError("Invalid or credential file path")
                if re.search(r"(?i)(?:^|/)(?:credentials|id_rsa|id_ed25519)(?:$|[.])|\.(?:pem|key|p12)$", file_path):
                    raise ValueError("Credential files are not supported")
                path = base + "/contents/" + quote(file_path, safe="/")
                method = "DELETE" if operation == "delete_file" else "PUT"
                body = {"message": self.text(p.get("message")), "branch": ref(p.get("branch"))}
                if p.get("sha"):
                    if not re.fullmatch(r"[0-9a-fA-F]{40}", str(p["sha"])):
                        raise ValueError("Invalid file SHA")
                    body["sha"] = p["sha"]
                if operation == "write_file":
                    content = self.text(p.get("content"), allow_empty=True)
                    body["content"] = base64.b64encode(content.encode()).decode()
                elif "sha" not in body:
                    raise ValueError("Deleting a file requires its current SHA")
            elif operation == "create_pull_request":
                path = base + "/pulls"
                body = self.fields(p, {"title", "body", "head", "base"}, {"title", "head", "base"})
                ref(body["head"])
                ref(body["base"])
                body["draft"] = True
            elif operation == "merge_pull_request":
                method, path = "PUT", base + f"/pulls/{number(p.get('number'))}/merge"
                if not re.fullmatch(r"[0-9a-fA-F]{40}", str(p.get("sha", ""))):
                    raise ValueError("Merging requires the verified current PR head SHA")
                merge_method = p.get("merge_method", "squash")
                if merge_method not in {"merge", "squash", "rebase"}:
                    raise ValueError("Invalid merge method")
                body = {"sha": p["sha"], "merge_method": merge_method}
        elif service == "jira":
            version = str(cfg.get("api_version", "2"))
            base = "/rest/api/" + version
            if operation == "create_issue":
                project = p.get("project")
                if not isinstance(project, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", project):
                    raise ValueError("Use a Jira project key, for example DEMO")
                if cfg.get("access") != "all" and project not in cfg.get("projects", []):
                    raise ValueError("Jira project is outside your configured scope")
                fields = {"project": {"key": project}, "summary": self.text(p.get("summary")),
                          "issuetype": {"name": self.text(p.get("issue_type", "Task"))}}
                if p.get("description") is not None:
                    fields["description"] = self.jira_text(p["description"], version)
                path, body = base + "/issue", {"fields": fields}
            else:
                key = self.issue(p.get("issue"))
                path = base + "/issue/" + key
                if operation == "comment_issue":
                    path += "/comment"
                    body = {"body": self.jira_text(p.get("body"), version)}
                elif operation == "update_issue":
                    method = "PUT"
                    fields = self.fields(p, {"summary", "description", "labels", "assignee"}, set())
                    if not fields:
                        raise ValueError("Provide at least one Jira field")
                    if "description" in fields:
                        fields["description"] = self.jira_text(fields["description"], version)
                    body = {"fields": fields}
                elif operation == "transition_issue":
                    path += "/transitions"
                    body = {"transition": {"id": str(number(p.get("transition_id")))}}
                elif operation == "delete_issue":
                    method = "DELETE"
        else:
            path = self.job_path(p.get("job"))
            if operation == "build_job":
                params = p.get("parameters", {})
                if not isinstance(params, dict) or any(not isinstance(v, (str, int, bool)) for v in params.values()):
                    raise ValueError("Jenkins parameters must be a simple object")
                if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) for k in params):
                    raise ValueError("Invalid Jenkins parameter name")
                path += "/buildWithParameters" if params else "/build"
                form = params
            else:
                path += f"/{number(p.get('build'))}/stop"
        return {"service": service, "operation": operation, "method": method,
                "path": clean_path(path), "body": body, "form": form}

    @staticmethod
    def text(value, allow_empty=False):
        if not isinstance(value, str) or len(value) > 100_000 or (not value.strip() and not allow_empty):
            raise ValueError("Expected text, at most 100,000 characters")
        return value

    def fields(self, payload, allowed, required):
        body = {k: payload[k] for k in allowed if k in payload}
        for key in required:
            self.text(body.get(key))
        if len(json.dumps(body)) > 150_000:
            raise ValueError("Payload too large")
        return body

    def jira_text(self, value, version):
        value = self.text(value, allow_empty=True)
        if version == "2":
            return value
        return {"version": 1, "type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []}
            for line in value.split("\n")
        ]}

    async def prepare(self, service, operation, payload):
        plan = self.plan(service, operation, payload)
        # File modifications are restricted to a non-default branch and include a real preview.
        if service == "github" and operation in {"write_file", "delete_file", "create_branch"}:
            repo = payload["repo"]
            metadata = await self.request("github", "GET", "/repos/" + repo)
            if payload["branch"] == metadata["default_branch"]:
                raise ValueError("Use a working branch; direct changes to the default branch are blocked")
            if operation in {"write_file", "delete_file"}:
                existing = None
                if payload.get("sha"):
                    existing = await self.request("github", "GET", plan["path"], params={"ref": payload["branch"]})
                    if existing.get("sha") != payload["sha"]:
                        raise ValueError("File changed; fetch the latest SHA and propose again")
                plan["preview"] = {"previous": base64.b64decode(existing.get("content", "")).decode("utf-8", errors="replace")
                                   if existing else "[new file]",
                                   "proposed": payload.get("content", "[deleted]")}
        return plan

    async def execute(self, plan):
        result = await self.request(plan["service"], plan["method"], plan["path"],
                                    body=plan.get("body"), form=plan.get("form"))
        if plan["operation"] == "merge_pull_request" and isinstance(result, dict) and not result.get("merged"):
            raise ValueError("GitHub did not merge the pull request")
        return result


def plan_fingerprint(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
