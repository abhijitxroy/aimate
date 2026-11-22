"""Single-operator storage. Secrets are encrypted; tool access never exposes them."""
import json
import hashlib
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from cryptography.fernet import Fernet


class Store:
    def __init__(self, directory=None):
        self.directory = Path(directory or os.environ.get("APP_DATA_DIR", ".data"))
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.directory.chmod(0o700)
        key_file = self.directory / "encryption.key"
        if not key_file.exists():
            with key_file.open("xb") as f:
                f.write(Fernet.generate_key())
        if os.name != "nt":
            key_file.chmod(0o600)
        self.cipher = Fernet(key_file.read_bytes())
        self.password = os.environ.get("APP_PASSWORD")
        if not self.password:
            password_file = self.directory / "access-password.txt"
            if not password_file.exists():
                with password_file.open("x") as f:
                    f.write(secrets.token_urlsafe(24))
            self.password = password_file.read_text().strip()
        if len(self.password) < 12:
            raise ValueError("APP_PASSWORD must have at least 12 characters")
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / "app.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), encrypted TEXT);
            CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, title TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, conversation TEXT, messages TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, conversation TEXT, service TEXT,
                operation TEXT, payload TEXT, preview TEXT, config_version TEXT,
                status TEXT, created REAL, result TEXT);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, action TEXT, status TEXT, result TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS connection_checks (service TEXT PRIMARY KEY, fingerprint TEXT, report TEXT);
            CREATE TABLE IF NOT EXISTS turn_usage (turn INTEGER PRIMARY KEY, metadata TEXT NOT NULL);
        """)
        self.db.commit()

    def execute(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def config(self):
        rows = self.rows("SELECT encrypted FROM settings WHERE id=1")
        return json.loads(self.cipher.decrypt(rows[0]["encrypted"].encode())) if rows else {}

    def save_config(self, config):
        config["_version"] = secrets.token_hex(16)
        encrypted = self.cipher.encrypt(json.dumps(config).encode()).decode()
        self.execute("INSERT OR REPLACE INTO settings VALUES (1, ?)", (encrypted,))

    def public_config(self):
        config = self.config()
        for section in config.values():
            if isinstance(section, dict):
                for key in list(section):
                    if key in {"token", "api_key", "aws_access_key", "aws_secret_key", "aws_session_token"}:
                        section[key + "_configured"] = bool(section.pop(key))
        config.pop("_version", None)
        return config

    @staticmethod
    def connection_fingerprint(config, service):
        return hashlib.sha256(json.dumps(config.get(service, {}), sort_keys=True).encode()).hexdigest()

    def save_connection_check(self, service, config, report):
        self.execute("INSERT OR REPLACE INTO connection_checks VALUES (?, ?, ?)",
                     (service, self.connection_fingerprint(config, service), json.dumps(report)))

    def connection_checks(self):
        config = self.config()
        reports = {}
        for row in self.rows("SELECT * FROM connection_checks"):
            report = json.loads(row["report"])
            if (row["fingerprint"] != self.connection_fingerprint(config, row["service"])
                    or time.time() - report["checked_at"] > 3600):
                report = {"status": "unchecked", "message": "Settings changed or check expired. Check access again."}
            reports[row["service"]] = report
        return reports

    def new_conversation(self, title="New conversation"):
        cid = secrets.token_hex(16)
        self.execute("INSERT INTO conversations VALUES (?, ?, ?)", (cid, title[:100], time.time()))
        return cid

    def require_conversation(self, cid):
        if not self.rows("SELECT id FROM conversations WHERE id=?", (cid,)):
            raise ValueError("Conversation not found")

    def history(self, cid):
        rows = self.rows("SELECT messages FROM turns WHERE conversation=? ORDER BY id DESC LIMIT 10", (cid,))
        # Keep complete tool/result groups together when limiting context.
        messages, size = [], 0
        for row in rows:
            turn = json.loads(row["messages"])
            if len(row["messages"]) > 40_000:
                for message in turn:
                    if not isinstance(message.get("content"), list):
                        continue
                    for block in message["content"]:
                        if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                            value = block["content"]
                            if len(value) > 3000:
                                block["content"] = value[:2300] + "\n[Historical result excerpt; re-read the source for full evidence.]\n" + value[-500:]
                        if block.get("type") == "responses":
                            for item in block.get("items", []):
                                value = item.get("output")
                                if isinstance(value, str) and len(value) > 3000:
                                    item["output"] = value[:2300] + "\n[Historical result excerpt; re-read the source for full evidence.]\n" + value[-500:]
                if len(json.dumps(turn)) > 40_000:
                    # A very large tool round must not erase the conversational context.
                    compact = []
                    for message in turn:
                        content = message.get("content")
                        if isinstance(content, str):
                            compact.append({"role": message["role"], "content": content[:12000]})
                        elif message["role"] == "assistant":
                            text = "\n\n".join(b.get("text", "") for b in content if b.get("type") == "text")
                            if text:
                                compact.append({"role": "assistant", "content": text[:12000]})
                    turn = compact
            length = len(json.dumps(turn))
            if messages and size + length > 140_000:
                break
            messages.insert(0, turn)
            size += length
        return [message for turn in messages for message in turn]

    def save_turn(self, cid, messages, metadata=None):
        with self.lock:
            cur = self.db.execute("INSERT INTO turns (conversation,messages,created) VALUES (?,?,?)",
                                  (cid, json.dumps(messages), time.time()))
            if metadata:
                self.db.execute("INSERT INTO turn_usage VALUES (?,?)", (cur.lastrowid, json.dumps(metadata)))
            self.db.commit()

    def action(self, aid):
        rows = self.rows("SELECT * FROM actions WHERE id=?", (aid,))
        if not rows:
            raise ValueError("Action not found")
        row = rows[0]
        for field in ("payload", "preview", "result"):
            row[field] = json.loads(row[field]) if row[field] else None
        return row
