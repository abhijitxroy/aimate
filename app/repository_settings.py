"""Validated, reviewed changes to the local GitHub repository list."""
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from app.connectors import scrub
from app.validation import validate_config


def repository_name(value, config):
    if not isinstance(value, str):
        raise ValueError("Provide a repository as OWNER/REPO or its GitHub URL.")
    value = value.strip().rstrip("/")
    if value.startswith("https://"):
        parsed = urlsplit(value)
        api_host = urlsplit(config.get("github", {}).get("url", "")).hostname
        web_host = "github.com" if api_host == "api.github.com" else api_host
        if parsed.hostname != web_host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use a repository URL on the saved GitHub host. Set a different host in Settings first.")
        value = parsed.path.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(p in {".", ".."} for p in value.split("/")):
        raise ValueError("Use OWNER/REPO, such as abhijitxroy/aimate, or the repository home URL.")
    return value


async def prepare_repository(config, payload, services_factory):
    from app.connection_checks import check_connection

    repo = repository_name(payload.get("repo"), config)
    before = list(config.get("github", {}).get("repos", []))
    replacing = repository_name(payload["replace"], config) if payload.get("replace") else None
    if replacing and replacing.lower() not in {r.lower() for r in before}:
        raise ValueError("The repository to replace is not configured. Name an existing repository.")
    if repo.lower() in {r.lower() for r in before}:
        raise ValueError("That repository is already configured. No change is needed.")
    after = [repo if replacing and r.lower() == replacing.lower() else r for r in before]
    if not replacing:
        after.append(repo)
    candidate = validate_config({**config, "github": {**config.get("github", {}), "repos": after}}, config)
    probe = {**candidate, "github": {**candidate["github"], "repos": [repo]}}
    report = scrub(await check_connection("github", probe, services_factory(probe), None, None), config)
    if not report["ok"]:
        reasons = [c["name"] + ": " + c["message"] for t in report.get("targets", [])
                   for c in t.get("checks", []) if not c["ok"]]
        reasons += [t["message"] for t in report.get("targets", []) if t.get("status") == "failed"]
        raise ValueError("Repository was not added. " + ("; ".join(reasons) or report["message"]))
    return candidate, {"repository": repo, "before": before, "after": after,
                       "access": report, "note": "Uses the saved GitHub connection. No GitHub repository is created or modified."}


async def propose_repository(store, config, cid, args, services_factory, access_check=None):
    from app.access_lease import bind_factory
    services_factory = bind_factory(services_factory, access_check)
    from app.agent import public_action
    if config["_version"] != store.config()["_version"]:
        raise ValueError("Settings changed while this chat was answering. Ask again to review a fresh proposal.")

    payload = {key: args[key] for key in ("repo", "replace") if args.get(key)}
    if scrub(payload, config) != payload:
        raise ValueError("Do not put credentials in chat. Use the saved GitHub token in Settings.")
    _, preview = await prepare_repository(config, payload, services_factory)
    if access_check:
        access_check()
    if config["_version"] != store.config()["_version"]:
        raise ValueError("Settings changed during access validation. Ask again to review a fresh proposal.")
    for pending in store.rows("""SELECT id FROM actions WHERE conversation=? AND service='settings'
            AND operation='update_github_repositories' AND status='pending' AND config_version=? AND created>?""",
                              (cid, config["_version"], time.time() - 1800)):
        card = public_action(store.action(pending["id"]))
        if card["preview"]["after"] == preview["after"]:
            return card
    aid = secrets.token_hex(16)
    store.execute("""INSERT INTO actions
        (id,conversation,service,operation,payload,preview,config_version,status,created)
        VALUES (?,?,?,?,?,?,?,'pending',?)""",
        (aid, cid, "settings", "update_github_repositories", json.dumps(payload),
         json.dumps(preview), config["_version"], time.time()))
    return public_action(store.action(aid))
