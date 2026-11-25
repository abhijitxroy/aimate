"""Migration tests use synthetic workspaces and credentials only."""
import base64
import importlib.util
import json
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from cryptography.fernet import Fernet
from app.database import connect, plaintext, migrate

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "portable_backup.py"
spec = importlib.util.spec_from_file_location("portable_backup", SCRIPT)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
PASSWORD = "synthetic backup password 123!"


class PortableBackupTests(unittest.TestCase):
    def test_verified_repo_updates_preserve_saved_data_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            updates, destination = root / "updates", root / "app"
            updates.mkdir()
            (destination / ".data").mkdir(parents=True)
            secret = destination / ".data" / "keep.txt"
            secret.write_text("preserve")
            (updates / "index.html").write_text("latest")
            manifest = {"index.html": hashlib.sha256(b"latest").hexdigest()}
            (updates / "updates-manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(migration.apply_repo_updates(destination, updates), 1)
            self.assertEqual((destination / "index.html").read_text(), "latest")
            self.assertEqual(secret.read_text(), "preserve")
            (updates / "index.html").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "verification"):
                migration.apply_repo_updates(destination, updates)
            for name in ("../outside.txt", ".data/keep.txt", ".env"):
                (updates / "updates-manifest.json").write_text(json.dumps({name: "x"}))
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    migration.apply_repo_updates(destination, updates)
            self.assertEqual(secret.read_text(), "preserve")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        (self.source / "app").mkdir(parents=True)
        (self.source / "app/main.py").write_text("# uncommitted app edit")
        (self.source / ".venv").mkdir()
        (self.source / ".venv/excluded.txt").write_text("not portable")
        self.data = self.source / ".data"
        self.backup = self.root / "test.aimate-backup"
        self.destination = self.root / "restored"
        self.old_device, self.new_device = Fernet(Fernet.generate_key()), Fernet(Fernet.generate_key())
        self.keys = {}

    @staticmethod
    def device(cipher):
        return lambda content, decrypt=False: cipher.decrypt(content) if decrypt else cipher.encrypt(content)

    def store(self, relative):
        directory = self.data / relative
        directory.mkdir(parents=True)
        key = Fernet.generate_key()
        self.keys[relative] = key
        cipher = Fernet(key)
        filename = "encryption.dpapi" if os.name == "nt" else "encryption.key"
        (directory / filename).write_bytes(self.old_device.encrypt(key) if os.name == "nt" else key)
        (directory / "access-password.txt").write_text("synthetic workspace password")
        db = sqlite3.connect(directory / "app.sqlite3")
        self.addCleanup(db.close)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE conversations(id TEXT, title TEXT);
            CREATE TABLE turns(id INTEGER, messages TEXT);
            CREATE TABLE todo_priorities(id TEXT PRIMARY KEY, priority TEXT);
            CREATE TABLE knowledge(id TEXT, value TEXT);
            CREATE TABLE settings(id INTEGER PRIMARY KEY, encrypted TEXT);
            CREATE TABLE login_otp(id INTEGER PRIMARY KEY, encrypted TEXT);
            CREATE TABLE vault_entries(id TEXT, encrypted TEXT);
            CREATE TABLE review_sessions(conversation TEXT, fingerprint TEXT, encrypted TEXT);
            CREATE TABLE conversation_briefs(conversation TEXT, encrypted TEXT, updated REAL);
            CREATE TABLE chatgpt_auth(id INTEGER PRIMARY KEY, encrypted TEXT);
        """)
        db.execute("INSERT INTO conversations VALUES ('chat-1','Preserve me')")
        db.execute("INSERT INTO turns VALUES (1,'saved chat with formatting\\nsecond line')")
        db.execute("INSERT INTO todo_priorities VALUES ('saved-task','P1')")
        db.execute("INSERT INTO knowledge VALUES ('note','diary text')")
        for table, value in (("settings", {"token": "synthetic-github-secret"}),
                             ("login_otp", {"secret": "synthetic-totp-secret"})):
            db.execute(f"INSERT INTO {table} VALUES (1,?)", (cipher.encrypt(json.dumps(value).encode()).decode(),))
        db.execute("INSERT INTO vault_entries VALUES ('vault',?)",
                   (cipher.encrypt(b"synthetic-vault-secret").decode(),))
        db.execute("INSERT INTO review_sessions VALUES ('chat-1','scope',?)",
                   (cipher.encrypt(b'{"path":"synthetic-review.py","ranges":[[0,100]]}').decode(),))
        db.execute("INSERT INTO conversation_briefs VALUES ('chat-1',?,1)",
                   (cipher.encrypt(b'{"entities":["DEMO-123"]}').decode(),))
        oauth = b'{"accounts":{"test":{"access_token":"synthetic-oauth-secret"}}}'
        blob = self.old_device.encrypt(oauth) if os.name == "nt" else cipher.encrypt(oauth)
        db.execute("INSERT INTO chatgpt_auth VALUES (1,?)", (base64.b64encode(blob).decode(),))
        db.commit()
        return db

    def export(self):
        with patch.object(migration, "dpapi", self.device(self.old_device)):
            return migration.export_backup(self.source, self.data, self.backup, PASSWORD)

    def restore(self, password=PASSWORD):
        with patch.object(migration, "dpapi", self.device(self.new_device)):
            return migration.restore_backup(self.backup, self.destination, password)

    def test_all_workspaces_wal_and_device_rebinding(self):
        owner = self.store("")
        self.store("users/" + "a" * 32)
        # Keep the source DB open with a live WAL to test committed data capture.
        owner.execute("INSERT INTO turns VALUES (2,'latest committed turn')")
        owner.commit()
        (self.data / "attachment.txt").write_text("attachment content")
        before = (self.data / "encryption.dpapi").read_bytes() if os.name == "nt" else self.keys[""]
        exported = self.export()
        self.assertEqual(len(exported["stores"]), 2)
        self.assertEqual(exported["stores"][0]["counts"]["review_sessions"], 1)
        self.assertEqual(exported["stores"][0]["counts"]["conversation_briefs"], 1)
        self.assertEqual(exported["stores"][0]["counts"]["todo_priorities"], 1)
        raw = self.backup.read_bytes()
        for secret in (b"synthetic-github-secret", b"saved chat", self.keys[""], b"synthetic-oauth-secret"):
            self.assertNotIn(secret, raw)
        self.restore()
        self.assertEqual((self.destination / "app/main.py").read_text(), "# uncommitted app edit")
        self.assertFalse((self.destination / ".venv").exists())
        self.assertEqual((self.destination / ".data/attachment.txt").read_text(), "attachment content")
        self.assertEqual((self.data / "encryption.dpapi").read_bytes() if os.name == "nt" else self.keys[""], before)
        for relative, key in self.keys.items():
            folder = self.destination / ".data" / relative
            if os.name == "nt":
                blob = (folder / "encryption.dpapi").read_bytes()
                self.assertEqual(self.new_device.decrypt(blob), key)
                with self.assertRaises(Exception):
                    self.old_device.decrypt(blob)
                self.assertFalse((folder / "encryption.key").exists())
            self.assertFalse(plaintext(folder / "app.sqlite3"))
            self.assertFalse((folder / "access-password.txt").exists())
            with closing(connect(folder / "app.sqlite3", key)) as db:
                self.assertEqual(db.execute("SELECT priority FROM todo_priorities WHERE id='saved-task'").fetchone()[0],"P1")
                with patch.object(migration, "dpapi", self.device(self.new_device)):
                    migration.verify_db(db, key)
                self.assertEqual(json.loads(Fernet(key).decrypt(db.execute("SELECT encrypted FROM settings").fetchone()[0].encode())),
                                 {"token": "synthetic-github-secret"})
                self.assertEqual(db.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 2 if relative == "" else 1)
        with self.assertRaises(ValueError):
            self.restore()

    def test_wrong_password_and_tampering_leave_no_destination(self):
        self.store("")
        self.export()
        with self.assertRaisesRegex(ValueError, "Wrong backup password"):
            self.restore("wrong password")
        self.assertFalse(self.destination.exists())
        raw = bytearray(self.backup.read_bytes())
        raw[-1] ^= 1
        self.backup.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "Wrong backup password"):
            self.restore()
        self.assertFalse(self.destination.exists())

    def test_corrupt_credentials_fail_export(self):
        db = self.store("")
        db.execute("UPDATE settings SET encrypted='broken'")
        db.commit()
        with self.assertRaises(Exception):
            self.export()
        self.assertFalse(self.backup.exists())

    def test_environment_password_is_in_encrypted_backup(self):
        self.store("")
        with patch.dict(os.environ, {"APP_PASSWORD": "synthetic override password"}):
            self.export()
        self.restore()
        self.assertEqual(Fernet(self.keys[""]).decrypt((self.destination / ".data/access-password.fernet").read_bytes()).decode(),
                         "synthetic override password")

    def test_encrypted_source_and_password_override_roundtrip(self):
        db = self.store("")
        db.close()
        key = self.keys[""]
        migrate(self.data / "app.sqlite3", key)
        (self.data / "access-password.fernet").write_bytes(Fernet(key).encrypt(b"synthetic old password"))
        (self.data / "access-password.txt").unlink()
        with patch.dict(os.environ, {"APP_PASSWORD": "synthetic current override"}):
            self.export()
        self.restore()
        restored = self.destination / ".data"
        self.assertFalse(plaintext(restored / "app.sqlite3"))
        self.assertEqual(Fernet(key).decrypt((restored / "access-password.fernet").read_bytes()),
                         b"synthetic current override")
        with closing(connect(restored / "app.sqlite3", key)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM conversations").fetchone()[0], 1)

    def test_unsafe_paths_rejected(self):
        for name in ("../escape", "/escape", "app/../escape", "C:/escape",
                     "app\\escape", "app//escape", "app/./escape"):
            with self.assertRaises(ValueError):
                migration.safe_name(name)

    def test_cli_export_checks_full_restore_without_printing_secrets(self):
        self.store("")
        captured = io.StringIO()
        argv = ["portable_backup.py", "export", "--source", str(self.source),
                "--data-dir", str(self.data),
                "--output", str(self.backup)]
        with patch.object(migration, "dpapi", self.device(self.old_device)), \
                patch.object(migration.sys, "argv", argv), \
                patch.object(migration.getpass, "getpass", return_value=PASSWORD), \
                patch.object(migration.sys, "stdout", captured):
            self.assertEqual(migration.main(), 0)
        self.assertIn("Full restore check: PASS", captured.getvalue())
        self.assertNotIn("synthetic-github-secret", captured.getvalue())
        self.assertNotIn(PASSWORD, captured.getvalue())
        self.assertTrue(self.backup.exists())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
    def test_real_windows_key_and_oauth_roundtrip(self):
        db = self.store("")
        key = self.keys[""]
        (self.data / "encryption.dpapi").write_bytes(migration.dpapi(key))
        oauth = b'{"accounts":{"test":{"access_token":"synthetic-real-dpapi"}}}'
        db.execute("UPDATE chatgpt_auth SET encrypted=?", (base64.b64encode(migration.dpapi(oauth)).decode(),))
        db.commit()
        migration.export_backup(self.source, self.data, self.backup, PASSWORD)
        migration.restore_backup(self.backup, self.destination, PASSWORD)
        self.assertEqual(migration.dpapi((self.destination / ".data/encryption.dpapi").read_bytes(), decrypt=True), key)
        with closing(connect(self.destination / ".data/app.sqlite3", key)) as restored:
            migration.verify_db(restored, key)
            encoded = restored.execute("SELECT encrypted FROM chatgpt_auth").fetchone()[0]
            self.assertEqual(migration.dpapi(base64.b64decode(encoded), decrypt=True), oauth)


if __name__ == "__main__":
    unittest.main()
