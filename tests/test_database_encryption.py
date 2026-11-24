"""Encrypted data/search, wrong-key failure and lossless migration/backup."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.database import connect, migrate, plaintext, snapshot
from app.store import Store


class DatabaseEncryptionTests(unittest.TestCase):
    def test_new_store_encrypts_chat_diary_search_and_password(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            cid = store.new_conversation("Confidential topic marker")
            store.save_turn(cid, [{"role": "user", "content": "confidential chat marker"}])
            store.execute("INSERT INTO knowledge VALUES ('note','secret label','diary marker',NULL,1)")
            password = store.password
            store.db.close()
            root = Path(directory)
            self.assertFalse(plaintext(root / "app.sqlite3"))
            raw = (root / "app.sqlite3").read_bytes()
            for text in ("Confidential topic marker", "confidential chat marker", "diary marker", password):
                self.assertNotIn(text.encode(), raw)
            self.assertFalse((root / "access-password.txt").exists())
            self.assertNotIn(password.encode(), (root / "access-password.fernet").read_bytes())
            with self.assertRaises(sqlite3.DatabaseError):
                with closing(sqlite3.connect(root / "app.sqlite3")) as db:
                    db.execute("SELECT * FROM conversations").fetchall()
            reopened = Store(directory)
            try:
                self.assertEqual(reopened.password, password)
                self.assertEqual(reopened.rows("SELECT value FROM knowledge")[0]["value"], "diary marker")
                self.assertEqual(len(reopened.rows("SELECT * FROM memory_index WHERE memory_index MATCH 'confidential'")), 1)
            finally:
                reopened.db.close()

    def test_legacy_wal_migration_preserves_rows_fts_and_encrypted_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.sqlite3"
            key = Fernet.generate_key()
            source = sqlite3.connect(path)
            source.execute("PRAGMA journal_mode=WAL")
            source.execute("CREATE TABLE records(id INTEGER PRIMARY KEY,value TEXT)")
            source.execute("CREATE VIRTUAL TABLE memory_index USING fts5(content,conversation UNINDEXED,turn UNINDEXED)")
            source.execute("INSERT INTO records VALUES (1,'private migration marker')")
            source.execute("INSERT INTO memory_index VALUES ('searchable migration marker','chat',1)")
            source.commit()
            source.close()
            self.assertTrue(migrate(path, key))
            self.assertFalse(plaintext(path))
            db = connect(path, key)
            try:
                self.assertEqual(db.execute("SELECT value FROM records").fetchone()[0], "private migration marker")
                self.assertEqual(db.execute("SELECT count(*) FROM memory_index WHERE memory_index MATCH 'searchable'").fetchone()[0], 1)
                plain = snapshot(db)
                self.assertEqual(plain.execute("SELECT value FROM records").fetchone()[0], "private migration marker")
                plain.close()
            finally:
                db.close()
            backup = path.with_name("app.sqlite3.pre-encryption.fernet")
            self.assertNotIn(b"private migration marker", backup.read_bytes())
            self.assertTrue(Fernet(key).decrypt(backup.read_bytes()).startswith(b"SQLite format 3"))
            with self.assertRaises(ValueError):
                connect(path, Fernet.generate_key())
            self.assertFalse(migrate(path, key))

    def test_interrupted_migration_preserves_original_and_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.sqlite3"
            key = Fernet.generate_key()
            with closing(sqlite3.connect(path)) as source:
                source.execute("CREATE TABLE records(id INTEGER PRIMARY KEY AUTOINCREMENT,value TEXT)")
                source.execute("INSERT INTO records VALUES (99,'preserve')")
                source.execute("DELETE FROM records")
                source.execute("PRAGMA user_version=7")
                source.commit()
            with patch("app.database.os.replace", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError):
                    migrate(path, key)
            self.assertTrue(plaintext(path))
            self.assertTrue(migrate(path, key))
            with closing(connect(path, key)) as result:
                result.execute("INSERT INTO records(value) VALUES ('next')")
                self.assertEqual(result.execute("SELECT id FROM records").fetchone()[0], 100)
                self.assertEqual(result.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertEqual(len(list(Path(directory).glob("*.fernet"))), 2)

    def test_missing_device_key_never_replaces_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.sqlite3").write_bytes(b"preserve-existing-data")
            with self.assertRaisesRegex(ValueError, "no encryption key"):
                Store(directory)
            self.assertEqual((root / "app.sqlite3").read_bytes(), b"preserve-existing-data")
            self.assertFalse((root / "encryption.dpapi").exists())
            self.assertFalse((root / "encryption.key").exists())
