"""SQLCipher storage and explicit, verified legacy migration."""
import base64
import os
import secrets
import sqlite3 as plain_sqlite
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlcipher3 import dbapi2 as driver


def database_key(key):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"AiMate SQLCipher database v1").derive(base64.urlsafe_b64decode(key))


def plaintext(path):
    path = Path(path)
    if not path.is_file():
        return False
    with path.open("rb") as file:
        return file.read(16) == b"SQLite format 3\0"


def connect(path, key, *, readonly=False):
    path = Path(path).resolve()
    existing_plain = plaintext(path)
    address = path.as_uri() + "?mode=ro" if readonly else str(path)
    db = driver.connect(address, uri=readonly, timeout=30, check_same_thread=False)
    try:
        if not db.execute("PRAGMA cipher_version").fetchone():
            raise ValueError("SQLCipher support is required.")
        if not existing_plain:
            # Hex is generated from protected key bytes; no user text enters SQL.
            db.execute('PRAGMA key = "x\'' + database_key(key).hex() + '\'"')
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA secure_delete=ON")
        db.create_function("casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)
        return db
    except Exception:
        db.close()
        raise ValueError("Database could not be unlocked. Preserve the data and its protected key.") from None


def snapshot(source):
    """Copy semantic SQLite data into memory; never write decrypted temp files."""
    target = plain_sqlite.connect(":memory:")
    target.create_function("casefold", 1, lambda value: str(value or "").casefold(), deterministic=True)
    own_transaction = not source.in_transaction
    if own_transaction:
        source.execute("BEGIN")
    schema = source.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'").fetchall()
    virtual = [name for kind, name, sql in schema if kind == "table" and sql.lstrip().upper().startswith("CREATE VIRTUAL")]
    shadow = {name for kind, name, sql in schema if kind == "table"
              and any(name.startswith(parent + "_") for parent in virtual)}
    try:
        for kind, name, sql in schema:
            if kind != "table" or name in shadow:
                continue
            target.execute(sql)
            escaped = '"' + name.replace('"', '""') + '"'
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({escaped})")]
            names = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
            if name in virtual:
                names = "rowid," + names
            rows = source.execute(f"SELECT {names} FROM {escaped}").fetchall()
            target.executemany(f"INSERT INTO {escaped} ({names}) VALUES ({','.join('?' for _ in names.split(','))})", rows)
        if source.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            target.execute("DELETE FROM sqlite_sequence")
            target.executemany("INSERT INTO sqlite_sequence VALUES (?,?)",
                               source.execute("SELECT * FROM sqlite_sequence").fetchall())
        for kind, name, sql in schema:
            if kind != "table":
                target.execute(sql)
        target.execute("PRAGMA user_version=" + str(source.execute("PRAGMA user_version").fetchone()[0]))
        target.commit()
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Decrypted in-memory snapshot failed integrity verification.")
        return target
    except BaseException:
        target.close()
        raise
    finally:
        if own_transaction:
            source.rollback()


def migrate(path, key):
    """Call only with the application stopped; keep an encrypted rollback copy."""
    path = Path(path).resolve()
    if not plaintext(path):
        db = connect(path, key)
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Encrypted database integrity check failed.")
        finally:
            db.close()
        return False
    stage = path.with_name(path.name + ".encrypt-" + secrets.token_hex(6))
    rollback = path.with_name(path.name + ".pre-encryption.fernet")
    if stage.parent != path.parent or rollback.parent != path.parent:
        raise ValueError("Unsafe migration target.")
    source = connect(path, key)
    try:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Original database failed integrity verification; preserved.")
        source.execute("PRAGMA wal_checkpoint(FULL)")
        source.execute("PRAGMA journal_mode=DELETE")
        cipher = Fernet(key)
        raw = path.read_bytes()
        encoded = cipher.encrypt(raw)
        if cipher.decrypt(encoded) != raw:
            raise ValueError("Rollback encryption verification failed.")
        # Preserve prior rollback copies when retrying an interrupted migration.
        if rollback.exists():
            rollback = path.with_name(path.name + ".pre-encryption-" + secrets.token_hex(6) + ".fernet")
        with rollback.open("xb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        source.execute("ATTACH DATABASE ? AS protected KEY ?",
                       (str(stage), "x'" + database_key(key).hex() + "'"))
        source.execute("SELECT sqlcipher_export('protected')")
        source.execute("PRAGMA protected.user_version=" + str(source.execute("PRAGMA user_version").fetchone()[0]))
        source.execute("DETACH DATABASE protected")
        checked = connect(stage, key)
        try:
            if checked.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Encrypted migration integrity check failed.")
            before, after = snapshot(source), snapshot(checked)
            try:
                # Compare semantic data, including regenerated full-text content.
                for name, in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                    quoted = '"' + name.replace('"', '""') + '"'
                    rows_a = sorted(before.execute(f"SELECT * FROM {quoted}").fetchall(), key=repr)
                    rows_b = sorted(after.execute(f"SELECT * FROM {quoted}").fetchall(), key=repr)
                    if rows_a != rows_b:
                        raise ValueError("Migration changed saved data; original database preserved.")
            finally:
                before.close()
                after.close()
        finally:
            checked.close()
        source.close()
        os.replace(stage, path)
        return True
    finally:
        source.close()
        if stage.exists():
            stage.unlink()


def password(directory, cipher):
    directory = Path(directory)
    protected = directory / "access-password.fernet"
    legacy = directory / "access-password.txt"
    if protected.exists():
        return cipher.decrypt(protected.read_bytes()).decode().strip()
    value = legacy.read_text().strip() if legacy.exists() else secrets.token_urlsafe(24)
    with protected.open("xb") as file:
        file.write(cipher.encrypt(value.encode()))
    return value
