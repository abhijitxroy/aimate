"""Pure scope and input validation, independent of networking and web frameworks."""
import re
from urllib.parse import unquote, urlsplit

def valid_base(value):
    value = str(value or "").strip().rstrip("/")
    u = urlsplit(value)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("Service URLs must be HTTPS URLs without credentials, query or fragment")
    if "\\" in value or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid service URL")
    return value


def clean_path(value):
    if not isinstance(value, str) or len(value) > 2000 or not value.startswith("/") or value.startswith("//"):
        raise ValueError("Use a relative API path starting with one /")
    decoded = value
    for _ in range(4):
        decoded = unquote(decoded)
    if any(part in {".", ".."} for part in decoded.split("/")) or any(c in decoded for c in "\\?#"):
        raise ValueError("Path traversal, query strings and fragments are not allowed in paths")
    if any(ord(c) < 32 for c in decoded):
        raise ValueError("Invalid API path")
    # Encoded separators can make a proxy interpret the scope differently.
    if re.search(r"%2f|%5c|%25", value, re.I):
        raise ValueError("Encoded path separators are not allowed")
    return value


def number(value):
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError("Expected a positive issue, PR or build number")
    return int(value)


def ref(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", value):
        raise ValueError("Invalid branch or ref")
    if ".." in value or "//" in value or value.endswith(("/", ".", ".lock")):
        raise ValueError("Invalid branch or ref")
    return value


def scoped_jql(query, projects):
    """Keep a filter inside its project constraint; reject attempts to escape its parentheses."""
    query = str(query or "").strip()
    masked, depth, quoted, escaped = [], 0, None, False
    for char in query:
        if quoted:
            masked.append(" ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quoted:
                quoted = None
        elif char in "\"'":
            quoted = char
            masked.append(" ")
        else:
            masked.append(char)
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError("Unbalanced JQL parentheses")
    if quoted or depth:
        raise ValueError("Unbalanced JQL quotes or parentheses")
    order = re.search(r"\border\s+by\b", "".join(masked), re.I)
    condition = query[:order.start()].strip() if order else query
    ordering = query[order.start():] if order else ""
    # ORDER BY inside a subexpression is not valid JQL, and cannot escape the outer scope.
    if any(c in ordering for c in "()"):
        raise ValueError("Invalid JQL ordering")
    scope = "project IN (" + ",".join(projects) + ")"
    return scope + (" AND (" + condition + ")" if condition else "") + (" " + ordering if ordering else "")


def validate_config(raw, old):
    if not isinstance(raw, dict):
        raise ValueError("Settings must be an object")
    out = {"allow_writes": bool(raw.get("allow_writes"))}
    allowed_fields = {
        "ai": {"provider", "model", "region", "api_key", "bedrock_auth", "bedrock_endpoint",
               "aws_access_key", "aws_secret_key", "aws_session_token"},
        "github": {"url", "repos", "token"},
        "jira": {"url", "projects", "auth", "username", "api_version", "token"},
        "jenkins": {"url", "jobs", "username", "token"},
    }
    for name, fields in allowed_fields.items():
        section = raw.get(name, {})
        if not isinstance(section, dict):
            raise ValueError("Each connection must be an object")
        out[name] = {k: v for k, v in section.items() if k in fields}
        secret = "api_key" if name == "ai" else "token"
        if not out[name].get(secret):
            changed_provider = name == "ai" and section.get("provider") != old.get(name, {}).get("provider")
            out[name][secret] = "" if section.get("clear_token") or changed_provider else old.get(name, {}).get(secret, "")
        if name == "ai":
            for key in ("aws_access_key", "aws_secret_key", "aws_session_token"):
                if not out[name].get(key):
                    out[name][key] = "" if section.get("clear_aws") else old.get(name, {}).get(key, "")
        for key, value in out[name].items():
            if key not in {"repos", "projects", "jobs"} and (not isinstance(value, str) or len(value) > 20_000):
                raise ValueError("Connection fields must be strings")
        if name != "ai" and out[name].get("url"):
            out[name]["url"] = valid_base(out[name]["url"])
        if name != "ai" and out[name].get("token") and not out[name].get("url"):
            raise ValueError(f"Add the {name} URL")
    if out["ai"].get("provider", "anthropic") not in {"anthropic", "bedrock", "chatgpt"}:
        raise ValueError("Choose ChatGPT, Anthropic or Bedrock")
    ai = out["ai"]
    if ai.get("bedrock_auth", "bearer") not in {"bearer", "iam"}:
        raise ValueError("Choose a Bedrock API key or AWS credentials")
    if ai.get("bedrock_endpoint", "runtime") not in {"runtime", "mantle"}:
        raise ValueError("Choose Bedrock Runtime or Mantle")
    if ai.get("region") and not re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-\d+", ai["region"]):
        raise ValueError("Use an AWS region such as us-east-1")
    if bool(ai.get("aws_access_key")) != bool(ai.get("aws_secret_key")):
        raise ValueError("Add both the AWS access key ID and secret access key, or remove saved AWS credentials")
    if ai.get("provider") == "bedrock" and ai.get("bedrock_endpoint") == "mantle" and ai.get("bedrock_auth") == "iam":
        raise ValueError("Use a Bedrock bearer key with Mantle in this app")
    if out["jira"].get("auth", "bearer") not in {"basic", "bearer"}:
        raise ValueError("Choose Jira basic or bearer authentication")
    if out["jira"].get("api_version", "2") not in {"2", "3"}:
        raise ValueError("Choose Jira API 2 or 3")
    for name, key, pattern, maximum in (
        ("github", "repos", r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", 20),
        ("jira", "projects", r"[A-Z][A-Z0-9_]*", 100),
        ("jenkins", "jobs", r"[A-Za-z0-9_. -]+(?:/[A-Za-z0-9_. -]+)*", 100),
    ):
        items = out[name].get(key, [])
        if not isinstance(items, list) or len(items) > maximum:
            raise ValueError(f"Use a list of at most {maximum} {key}")
        if any(not isinstance(item, str) for item in items):
            raise ValueError(f"Invalid {key}")
        items = list(dict.fromkeys(items))
        if any(not isinstance(item, str) or not re.fullmatch(pattern, item)
               or any(part in {".", ".."} for part in item.split("/")) for item in items):
            raise ValueError(f"Invalid {key}")
        out[name][key] = items
        if out[name].get("token") and not items:
            raise ValueError(f"Add at least one {key} entry for {name}")
    for name in ("jenkins", "jira"):
        if out[name].get("token") and (name == "jenkins" or out[name].get("auth") == "basic") and not out[name].get("username"):
            raise ValueError(f"Add the {name} username/email")
    return out

