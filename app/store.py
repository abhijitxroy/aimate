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
        from app.device_key import load_key
        self.cipher = Fernet(load_key(self.directory))
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
        self.db.create_function("casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)
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
            CREATE TABLE IF NOT EXISTS review_sessions (conversation TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                encrypted TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_briefs (conversation TEXT PRIMARY KEY, encrypted TEXT NOT NULL,
                updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS turn_usage (turn INTEGER PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attachment_previews (turn INTEGER PRIMARY KEY, encrypted TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_revisions (id INTEGER PRIMARY KEY, conversation TEXT NOT NULL,
                encrypted TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS access_grants (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                role TEXT NOT NULL, digest TEXT NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS access_grant_otp (id TEXT PRIMARY KEY, encrypted TEXT NOT NULL, last_counter INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS access_audit (id INTEGER PRIMARY KEY, grant_id TEXT NOT NULL,
                operation TEXT NOT NULL, before_role TEXT, after_role TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS vault_entries (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                encrypted TEXT NOT NULL, ai_access INTEGER NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, conversation TEXT NOT NULL,
                turn INTEGER NOT NULL, rating TEXT NOT NULL, category TEXT NOT NULL,
                comment TEXT NOT NULL, created REAL NOT NULL, role TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_groups (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                kind TEXT NOT NULL, parent TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_locations (conversation TEXT PRIMARY KEY, group_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_flags (conversation TEXT PRIMARY KEY, pinned INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_archives (conversation TEXT PRIMARY KEY, archived INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_icons (conversation TEXT PRIMARY KEY, icon TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conversation_references (conversation TEXT PRIMARY KEY, source TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge (id TEXT PRIMARY KEY, key TEXT NOT NULL,
                value TEXT NOT NULL, group_id TEXT, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS todos (id TEXT PRIMARY KEY, title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_index USING fts5(content, conversation UNINDEXED, turn UNINDEXED);
            CREATE TABLE IF NOT EXISTS usage_events (id TEXT PRIMARY KEY, created REAL NOT NULL,
                provider TEXT NOT NULL, model TEXT NOT NULL, tokens TEXT NOT NULL, origin TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usage_rates (model TEXT PRIMARY KEY, input REAL NOT NULL,
                output REAL NOT NULL, cache_read REAL NOT NULL, cache_write REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS ai_failures (id TEXT PRIMARY KEY, conversation TEXT,
                status INTEGER, diagnosis TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS turns_by_conversation ON turns(conversation,id DESC);
            CREATE INDEX IF NOT EXISTS actions_by_conversation ON actions(conversation,created DESC);
            CREATE INDEX IF NOT EXISTS usage_by_date ON usage_events(created);
            CREATE INDEX IF NOT EXISTS feedback_by_date ON feedback(created DESC);
        """)
        from app.memory import readable_text
        from app.context_brief import backfill
        backfill(self)
        for row in self.db.execute("SELECT id,conversation,messages FROM turns WHERE id NOT IN (SELECT turn FROM memory_index)").fetchall():
            self.db.execute("INSERT INTO memory_index VALUES (?,?,?)",
                            (readable_text(json.loads(row["messages"])), row["conversation"], row["id"]))
        if not self.db.execute("SELECT name FROM migrations WHERE name='usage_backfill'").fetchone():
            for row in self.db.execute("SELECT t.id,t.created,u.metadata FROM turns t JOIN turn_usage u ON u.turn=t.id").fetchall():
                metadata = json.loads(row["metadata"])
                for model, tokens in metadata.get("by_model", {metadata.get("model", "unknown"): metadata.get("usage", {})}).items():
                    if any(tokens.values()):
                        self.db.execute("INSERT OR IGNORE INTO usage_events VALUES (?,?,?,?,?,?)",
                                        (str(row["id"]) + ":" + model, row["created"], "historical", model,
                                         json.dumps(tokens), "Imported saved turn"))
            self.db.execute("INSERT INTO migrations VALUES ('usage_backfill')")
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
        config = json.loads(self.cipher.decrypt(rows[0]["encrypted"].encode())) if rows else {}
        policy = getattr(self, "public_policy", None)
        if policy:
            policy.validate(config)
            config["_public_showcase"] = True
        return config

    def save_config(self, config):
        policy = getattr(self, "public_policy", None)
        if policy:
            policy.validate(config)
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
            if row["fingerprint"] != self.connection_fingerprint(config, row["service"]):
                report = {"status": "unchecked", "message": "Settings changed. Checking the saved connection is required."}
            else:
                report["stale"] = time.time() - report["checked_at"] > 300
            reports[row["service"]] = report
        return reports

    def record_ai_activity(self, config, model, *, ok=True, message=None):
        # An answer/access failure verifies only the model involved in that request.
        with self.lock:
            if self.connection_fingerprint(config, "ai") != self.connection_fingerprint(self.config(), "ai"):
                return
            ai = config.get("ai", {})
            models = list(dict.fromkeys(m for m in (ai.get("model"), ai.get("analysis_model")) if m))
            if model not in models:
                return
            previous = self.connection_checks().get("ai", {})
            targets = {t["target"].split(" · ", 1)[-1]: t for t in previous.get("targets", [])}
            rows = []
            for configured in models:
                label = "Standard" if configured == ai.get("model") else "Analysis"
                row = dict(targets.get(configured, {"target": label + " · " + configured,
                    "ok": False, "status": "unchecked", "message": "This model has not been verified.",
                    "details": [], "checks": []}))
                if configured == model:
                    row.update(ok=ok, status="passed" if ok else "failed",
                               message=message or "Verified by a successful AI answer.")
                rows.append(row)
            passed = sum(row["ok"] for row in rows)
            report = {"ok": passed == len(models), "status": "passed" if passed == len(models) else "partial" if passed else "failed",
                      "checked_at": time.time(), "targets": rows,
                      "message": message or "Updated from a successful AI answer.",
                      "counts": {"passed": passed, "total": len(models), "unit": "models"}}
            self.save_connection_check("ai", config, report)

    def new_conversation(self, title="New conversation", group_id=None):
        if group_id:
            self.require_group(group_id)
        cid = secrets.token_hex(16)
        self.execute("INSERT INTO conversations VALUES (?, ?, ?)", (cid, title[:100], time.time()))
        if group_id:
            self.execute("INSERT INTO conversation_locations VALUES (?, ?)", (cid, group_id))
        return cid

    def require_group(self, group_id):
        if not isinstance(group_id, str) or not self.rows("SELECT id FROM conversation_groups WHERE id=?", (group_id,)):
            raise ValueError("Choose an existing project, module or group.")

    def create_group(self, name, kind="group", parent=None):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError("Use a group name with 1–80 characters.")
        if not isinstance(kind, str) or kind not in {"project", "module", "group"}:
            raise ValueError("Choose Project, Module or Group.")
        if parent is not None:
            self.require_group(parent)
            depth, ancestor = 1, parent
            while ancestor:
                depth += 1
                ancestor = self.rows("SELECT parent FROM conversation_groups WHERE id=?", (ancestor,))[0]["parent"]
                if depth > 8:
                    raise ValueError("Use at most eight levels of groups.")
        if self.rows("SELECT id FROM conversation_groups WHERE lower(name)=lower(?) AND parent IS ?", (name.strip(), parent)):
            raise ValueError("A group with that name already exists here.")
        gid = secrets.token_hex(16)
        self.execute("INSERT INTO conversation_groups VALUES (?, ?, ?, ?, ?)", (gid, name.strip(), kind, parent, time.time()))
        return gid

    def move_conversation(self, cid, group_id):
        self.require_conversation(cid)
        if group_id is not None:
            self.require_group(group_id)
            self.execute("INSERT OR REPLACE INTO conversation_locations VALUES (?, ?)", (cid, group_id))
        else:
            self.execute("DELETE FROM conversation_locations WHERE conversation=?", (cid,))

    def conversation_group(self, cid):
        rows = self.rows("SELECT group_id FROM conversation_locations WHERE conversation=?", (cid,))
        return rows[0]["group_id"] if rows else None

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
        from app.memory import readable_text
        with self.lock:
            next_id = self.db.execute("SELECT max(coalesce((SELECT max(id) FROM turns),0),"
                                     "coalesce((SELECT max(id) FROM conversation_revisions),0))+1").fetchone()[0]
            cur = self.db.execute("INSERT INTO turns (id,conversation,messages,created) VALUES (?,?,?,?)",
                                  (next_id, cid, json.dumps(messages), time.time()))
            self.db.execute("INSERT INTO memory_index VALUES (?,?,?)",
                            (readable_text(messages), cid, cur.lastrowid))
            if metadata:
                self.db.execute("INSERT INTO turn_usage VALUES (?,?)", (cur.lastrowid, json.dumps(metadata)))
            from app.context_brief import record
            record(self, cid, messages)
            self.db.commit()

    def action(self, aid):
        rows = self.rows("SELECT * FROM actions WHERE id=?", (aid,))
        if not rows:
            raise ValueError("Action not found")
        row = rows[0]
        for field in ("payload", "preview", "result"):
            row[field] = json.loads(row[field]) if row[field] else None
        return row
