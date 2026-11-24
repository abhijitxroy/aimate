"""Request-scoped personal stores. The existing data directory belongs to the owner."""
import hashlib
import re
import threading
from contextvars import ContextVar

from app.store import Store


class PersonalStore(Store):
    def __init__(self, directory, owner):
        self.owner = owner
        super().__init__(directory)
        self.public_policy = getattr(owner, "public_policy", None)
        self.execute("UPDATE actions SET status='unknown' WHERE status='executing'")

    def config(self):
        config = super().config()
        # A personal credential never grants permission to execute a change.
        enabled = bool(self.owner.config().get("allow_writes"))
        config["allow_writes"] = enabled
        config["_version"] = hashlib.sha256(
            (config.get("_version", "") + ":" + str(enabled)).encode()).hexdigest()
        return config

    def save_config(self, config):
        ai = config.get("ai", {})
        if (ai.get("provider") == "bedrock" and ai.get("bedrock_auth") == "iam"
                and not (ai.get("aws_access_key") and ai.get("aws_secret_key"))):
            raise ValueError("Add your own AWS access key and secret, or use a Bedrock API key. Personal workspaces cannot use the server's AWS credentials.")
        personal = {k: v for k, v in config.items() if k not in {"allow_writes", "_version"}}
        super().save_config(personal)


class ScopedHandle:
    def __init__(self, current, index):
        self._current, self._index = current, index

    def __getattr__(self, name):
        return getattr(self._current.get()[self._index], name)


class Workspaces:
    def __init__(self, owner, chatgpt, transport=None):
        self.owner, self.transport = owner, transport
        self.entries = {"owner": (owner, chatgpt)}
        self.current = ContextVar("aimate_workspace", default=self.entries["owner"])
        self.store = ScopedHandle(self.current, 0)
        self.chatgpt = ScopedHandle(self.current, 1)
        self.lock = threading.RLock()

    def select(self, grant=None):
        key = grant or "owner"
        if key != "owner" and not re.fullmatch(r"[0-9a-f]{32}", key):
            raise ValueError("Invalid personal workspace.")
        with self.lock:
            if key not in self.entries:
                from app.chatgpt import ChatGPT
                base = (self.owner.directory / "users").resolve()
                directory = (base / key).resolve()
                if directory.parent != base:
                    raise ValueError("Invalid personal workspace directory.")
                store = PersonalStore(directory, self.owner)
                # Never copy the owner's settings, credentials, or conversations.
                self.entries[key] = (store, ChatGPT(store, transport=self.transport))
            return self.entries[key]

    def close(self):
        with self.lock:
            for key, (store, _) in self.entries.items():
                if key != "owner":
                    store.db.close()
            self.entries = {"owner": self.entries["owner"]}
