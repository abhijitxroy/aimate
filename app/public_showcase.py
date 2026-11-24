"""Explicit public-source allowlists; never reuse the local corporate dataset."""
import json
import base64
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def intel_host(host):
    host = str(host or "").lower().rstrip(".")
    return host == "intel.com" or host.endswith(".intel.com")


def intel_owner(owner):
    owner = owner.casefold()
    return owner == "intel" or owner.startswith("intel-")


def prepare_directory(directory):
    path = Path(directory)
    marker = path / "public-showcase.json"
    if marker.exists():
        if json.loads(marker.read_text()) != {"dataset": "public-showcase", "version": 1}:
            raise ValueError("Invalid public showcase dataset marker.")
        return
    if path.exists() and any(path.iterdir()):
        raise ValueError("Public showcase requires a fresh data directory. Never copy local chats, credentials or encryption keys.")
    path.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"dataset":"public-showcase","version":1}))


class PublicPolicy:
    def __init__(self):
        self.owners = {value.strip().casefold() for value in
                       os.environ.get("AIMATE_PUBLIC_GITHUB_OWNERS", "abhijitxroy").split(",") if value.strip()}
        if not self.owners or any(intel_owner(owner) or not re.fullmatch(r"[a-z0-9-]+", owner) for owner in self.owners):
            raise ValueError("Choose non-Intel GitHub owners for the public showcase.")
        self.hosts = {}
        for service in ("jira", "jenkins"):
            hosts = {host.strip().lower().rstrip(".") for host in
                     os.environ.get("AIMATE_PUBLIC_" + service.upper() + "_HOSTS", "").split(",") if host.strip()}
            if any(intel_host(host) or "/" in host or ":" in host or not "." in host for host in hosts):
                raise ValueError("Public service allowlists require non-Intel hostnames.")
            self.hosts[service] = hosts

    def validate(self, config):
        ai = config.get("ai", {})
        if (ai.get("provider") == "bedrock" and ai.get("bedrock_auth") == "iam"
                and not (ai.get("aws_access_key") and ai.get("aws_secret_key"))):
            raise ValueError("Public showcase requires personal AWS credentials or a Bedrock API key; server AWS credentials are disabled.")
        github = config.get("github", {})
        if github.get("url") and github["url"].rstrip("/") != "https://api.github.com":
            raise ValueError("Public showcase uses https://api.github.com for GitHub.")
        for repo in github.get("repos", []):
            owner = str(repo).split("/")[0].casefold()
            if intel_owner(owner) or owner not in self.owners:
                raise ValueError("Repository blocked in public showcase. Use an approved personal GitHub owner.")
        for service in ("jira", "jenkins"):
            section = config.get(service, {})
            if any(section.get(key) for key in ("url", "token", "jobs", "projects")):
                host = urlsplit(section.get("url", "")).hostname
                if intel_host(host) or host not in self.hosts[service]:
                    raise ValueError(f"{service.title()} is blocked in public showcase. Admin must approve a non-Intel service host.")

    def text(self, value):
        if isinstance(value, dict):
            if value.get("encoding") == "base64" and isinstance(value.get("content"), str):
                try:
                    decoded_content = base64.b64decode(value["content"]).decode("utf-8")
                except (ValueError, UnicodeError):
                    decoded_content = ""
                self.text(decoded_content)
            for item in value.values():
                if isinstance(item, (dict, list)):
                    self.text(item)
        elif isinstance(value, list):
            for item in value:
                self.text(item)
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        # Detect known corporate links even when they are quoted or URL-encoded.
        decoded = unquote(value)
        for match in re.finditer(r"https?://[^\s<>\"']+", decoded, re.I):
            url = urlsplit(match.group().rstrip(").,;"))
            if intel_host(url.hostname):
                raise ValueError("Intel resource links are blocked in public showcase.")
            hostname = (url.hostname or "").lower().rstrip(".")
            if hostname in {"github.com", "api.github.com"}:
                parts = url.path.strip("/").split("/")
                owner = parts[1] if hostname == "api.github.com" and parts[0].lower() == "repos" and len(parts)>1 else parts[0]
                if intel_owner(owner):
                    raise ValueError("Intel repository links are blocked in public showcase.")
