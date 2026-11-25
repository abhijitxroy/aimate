"""Password-encrypted, device-independent AiMate migration. Never prints secrets."""
import argparse
import base64
import getpass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from contextlib import closing
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

try:
    from device_key import dpapi
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.device_key import dpapi

try:
    from app.database import connect as connect_database, snapshot as memory_snapshot, migrate, password as protected_password
except ImportError:
    from database import connect as connect_database, snapshot as memory_snapshot, migrate, password as protected_password

MAGIC = b"AIMATE-BACKUP-1\n"
EXCLUDED = {".git", ".venv", ".data", ".demo-data", ".public-data", "_site",
            "__pycache__", ".pytest_cache", "node_modules", ".migration-venv"}
TABLES = ("conversations", "turns", "knowledge", "todos", "vault_entries", "review_sessions", "conversation_briefs",
          "access_grants", "usage_events", "feedback", "actions", "documents", "usage_calls",
          "usage_preferences", "usage_invoices", "library_items","todo_types", "conversation_icon_styles")
LIMIT = 512 * 1024 * 1024


def password_key(password, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=600_000).derive(password.encode("utf-8"))


def seal(payload, password):
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    return header + AESGCM(password_key(password, salt)).encrypt(nonce, payload, header)


def unseal(payload, password):
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 44:
        raise ValueError("This is not a supported AiMate backup.")
    position = len(MAGIC)
    salt, nonce = payload[position:position + 16], payload[position + 16:position + 28]
    header = payload[:position + 28]
    try:
        return AESGCM(password_key(password, salt)).decrypt(nonce, payload[len(header):], header)
    except InvalidTag:
        raise ValueError("Wrong backup password, or the backup file has been changed.") from None


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))
            or str(path) != name):
        raise ValueError("Backup contains an unsafe file path.")
    return path


def counts(db):
    existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {name: db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            for name in TABLES if name in existing}


def verify_db(db, key, oauth_portable=False):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("Database integrity check failed. Original data has been preserved.")
    cipher = Fernet(key)
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        if "encrypted" not in {row[1] for row in db.execute(f"PRAGMA table_info({quoted})")}:
            continue
        for (value,) in db.execute(f"SELECT encrypted FROM {quoted}"):
            if not value:
                continue
            if table == "chatgpt_auth":
                raw = base64.b64decode(value, validate=True)
                plain = cipher.decrypt(raw) if oauth_portable or os.name != "nt" else dpapi(raw, decrypt=True)
                json.loads(plain)
            else:
                cipher.decrypt(value.encode() if isinstance(value, str) else value)


def convert_oauth(db, key, exporting):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chatgpt_auth'").fetchone():
        return
    cipher = Fernet(key)
    for row_id, value in db.execute("SELECT id, encrypted FROM chatgpt_auth").fetchall():
        if not value:
            continue
        raw = base64.b64decode(value, validate=True)
        if exporting:
            plain = dpapi(raw, decrypt=True) if os.name == "nt" else cipher.decrypt(raw)
            encoded = cipher.encrypt(plain)
        else:
            plain = cipher.decrypt(raw)
            encoded = dpapi(plain) if os.name == "nt" else cipher.encrypt(plain)
        json.loads(plain)
        db.execute("UPDATE chatgpt_auth SET encrypted=? WHERE id=?",
                   (base64.b64encode(encoded).decode(), row_id))
    db.commit()


def files_under(root, exclusions=()):
    for directory, directories, filenames in os.walk(root, followlinks=False):
        base = Path(directory)
        directories[:] = sorted(name for name in directories
                                if name not in exclusions and not (base / name).is_symlink())
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink():
                raise ValueError("Symbolic links cannot be migrated; replace the link with a regular file.")
            yield path


def export_backup(source, data_dir, output, password):
    source, data_dir, output = Path(source).resolve(), Path(data_dir).resolve(), Path(output).resolve()
    if not (source / "app" / "main.py").is_file() or not (data_dir / "app.sqlite3").is_file():
        raise ValueError("AiMate app or saved database not found. Check the source/data folder.")
    if output.exists() or output.is_relative_to(source) or output.is_relative_to(data_dir):
        raise ValueError("Choose a new backup file outside the app and data folders.")
    stores = []
    snapshots = {}
    for path in sorted(data_dir.rglob("app.sqlite3")):
        relative = path.relative_to(data_dir).as_posix()
        protected, legacy = path.parent / "encryption.dpapi", path.parent / "encryption.key"
        key = dpapi(protected.read_bytes(), decrypt=True) if protected.exists() else legacy.read_bytes()
        Fernet(key)
        with closing(connect_database(path, key, readonly=True)) as original:
            with closing(memory_snapshot(original)) as snapshot:
                verify_db(snapshot, key)
                inventory = counts(snapshot)
                convert_oauth(snapshot, key, exporting=True)
                verify_db(snapshot, key, oauth_portable=True)
                snapshots[relative] = snapshot.serialize()
        stores.append({"database": relative, "key": key.decode(), "counts": inventory})
    manifest = {"version": 1, "created": datetime.now(timezone.utc).isoformat(),
                "stores": stores, "files": {}, "environment_names": sorted(
                    name for name in os.environ
                    if name.startswith(("APP_", "AIMATE_", "AWS_", "ANTHROPIC_"))
                    or name in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE"))}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        total = 0

        def add(name, content):
            nonlocal total
            safe_name(name)
            total += len(content)
            if total > LIMIT:
                raise ValueError("Backup exceeds 512 MB. Move large generated files out of the app folder.")
            if name in manifest["files"]:
                raise ValueError("Duplicate backup path.")
            manifest["files"][name] = hashlib.sha256(content).hexdigest()
            archive.writestr(name, content)

        for path in files_under(source, EXCLUDED):
            if path.is_relative_to(data_dir):
                continue
            add("app/" + path.relative_to(source).as_posix(), path.read_bytes())
        for path in files_under(data_dir):
            relative = path.relative_to(data_dir).as_posix()
            if path.name in ("encryption.dpapi", "encryption.key") or path.name.endswith(("-wal", "-shm")):
                continue
            if relative not in snapshots:
                content = path.read_bytes()
                if os.environ.get("APP_PASSWORD") and relative in ("access-password.txt", "access-password.fernet"):
                    content = os.environ["APP_PASSWORD"].encode()
                    if relative.endswith(".fernet"):
                        owner = next(store for store in stores if store["database"] == "app.sqlite3")
                        content = Fernet(owner["key"].encode()).encrypt(content)
                add("data/" + relative, content)
        for relative, content in snapshots.items():
            add("data/" + relative, content)
        # Preserve an environment-only workspace password without exposing its value.
        if os.environ.get("APP_PASSWORD") and not any(
                "data/" + name in manifest["files"] for name in ("access-password.txt", "access-password.fernet")):
            name = "data/access-password.txt"
            content = os.environ["APP_PASSWORD"].encode()
            add(name, content)
        archive.writestr("manifest.json", json.dumps(manifest).encode())
    output.parent.mkdir(parents=True, exist_ok=True)
    encrypted = seal(buffer.getvalue(), password)
    # Verify authentication before publishing the file. Never overwrite an older backup.
    if unseal(encrypted, password) != buffer.getvalue():
        raise ValueError("Backup verification failed.")
    with output.open("xb") as file:
        file.write(encrypted)
        file.flush()
        os.fsync(file.fileno())
    return manifest


def restore_backup(backup, destination, password):
    backup, destination = Path(backup).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Destination already exists. Choose a new empty folder name; nothing was overwritten.")
    if backup.stat().st_size > LIMIT + 1024 * 1024:
        raise ValueError("Backup file exceeds the supported size.")
    payload = unseal(backup.read_bytes(), password)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or sum(entry.file_size for entry in entries) > LIMIT + 1024 * 1024:
            raise ValueError("Backup has duplicate files or exceeds the supported size.")
        for entry in entries:
            safe_name(entry.filename)
            if entry.is_dir() or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Backup contains unsupported links/directories.")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("version") != 1 or set(names) != set(manifest["files"]) | {"manifest.json"}:
            raise ValueError("Backup manifest is incomplete or unsupported.")
        windows_names = [name.casefold() for name in names]
        if len(windows_names) != len(set(windows_names)):
            raise ValueError("Backup contains conflicting Windows filenames.")
        for name, digest in manifest["files"].items():
            if (not name.startswith(("app/", "data/"))
                    or name.startswith("app/.data/")
                    or hashlib.sha256(archive.read(name)).hexdigest() != digest):
                raise ValueError("Backup file verification failed.")
        if "app/app/main.py" not in manifest["files"] or not manifest["stores"]:
            raise ValueError("Backup does not contain a complete AiMate workspace.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".aimate-restore-", dir=destination.parent))
        try:
            for name in manifest["files"]:
                group, relative = name.split("/", 1)
                path = stage / (relative if group == "app" else ".data/" + relative)
                if path.exists():
                    raise ValueError("Backup contains overlapping app and data paths.")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
            for store in manifest["stores"]:
                relative = str(safe_name(store["database"]))
                if "data/" + relative not in manifest["files"] or not relative.endswith("app.sqlite3"):
                    raise ValueError("Backup store path is invalid.")
                path = stage / ".data" / relative
                key = store["key"].encode()
                Fernet(key)
                with closing(sqlite3.connect(path)) as db:
                    verify_db(db, key, oauth_portable=True)
                    if counts(db) != store["counts"]:
                        raise ValueError("Saved-record counts do not match the backup.")
                    convert_oauth(db, key, exporting=False)
                    verify_db(db, key)
                if os.name == "nt":
                    protected = dpapi(key)
                    if dpapi(protected, decrypt=True) != key:
                        raise ValueError("New Windows account key verification failed.")
                    (path.parent / "encryption.dpapi").write_bytes(protected)
                else:
                    (path.parent / "encryption.key").write_bytes(key)
                    (path.parent / "encryption.key").chmod(0o600)
                migrate(path, key)
                cipher = Fernet(key)
                protected_password(path.parent, cipher)
                legacy = path.parent / "access-password.txt"
                if legacy.exists():
                    legacy.unlink()
                with closing(connect_database(path, key, readonly=True)) as db:
                    verify_db(db, key)
                    if counts(db) != store["counts"]:
                        raise ValueError("Encrypted restore changed saved-record counts.")
            # Race-safe on Windows: rename fails if destination has appeared.
            stage.rename(destination)
        except BaseException:
            if stage.resolve().parent != destination.parent.resolve() or not stage.name.startswith(".aimate-restore-"):
                raise ValueError("Restore cleanup target was unsafe; temporary files were preserved.")
            shutil.rmtree(stage)
            raise
    return manifest


def apply_repo_updates(destination, updates):
    """Apply verified code updates after restore, never saved data or credentials."""
    destination, updates = Path(destination).resolve(), Path(updates).resolve()
    manifest = updates / "updates-manifest.json"
    if not manifest.is_file():
        return 0
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    prepared = []
    for name, digest in entries.items():
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or
                any(part.startswith(".") and part != ".github" for part in relative.parts)):
            raise ValueError("Unsafe migration update path. Saved data was not changed.")
        source, target = updates / relative, destination / relative
        if (source.is_symlink() or not source.resolve().is_relative_to(updates) or
                not target.resolve().is_relative_to(destination) or
                not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest):
            raise ValueError("Migration update verification failed. Saved data was not changed.")
        prepared.append((source, target))
    for source, target in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return len(prepared)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    export.add_argument("--data-dir", type=Path)
    export.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        password = getpass.getpass("Backup password (hidden): ")
        if args.command == "export":
            if len(password) < 12:
                raise ValueError("Use a backup password of at least 12 characters.")
            if password != getpass.getpass("Confirm backup password: "):
                raise ValueError("Passwords did not match.")
            data_dir = args.data_dir or Path(os.environ.get("APP_DATA_DIR", str(args.source / ".data")))
            manifest = export_backup(args.source, data_dir, args.output, password)
            # Exercise a complete restore before the old machine is handed back.
            verification_root = Path(tempfile.mkdtemp(prefix="aimate-backup-check-"))
            try:
                restored = restore_backup(args.output, verification_root / "workspace", password)
                if restored["stores"] != manifest["stores"]:
                    raise ValueError("Full restore verification failed. Do not surrender the old laptop yet.")
            finally:
                if (verification_root.resolve().parent != Path(tempfile.gettempdir()).resolve()
                        or not verification_root.name.startswith("aimate-backup-check-")):
                    raise ValueError("Verification cleanup target was unsafe.")
                shutil.rmtree(verification_root)
            print("Encrypted backup verified and saved:", args.output)
            print("Full restore check: PASS. Saved-record counts and protected credentials verified.")
        else:
            manifest = restore_backup(args.backup, args.destination, password)
            print("Restore verified:", args.destination)
            updated = apply_repo_updates(args.destination, Path(__file__).resolve().parent / "repo-updates")
            if updated:
                print("Latest verified app updates applied:", updated, "files. Saved data and credentials preserved.")
        print("Saved workspaces:", len(manifest["stores"]))
        totals = {}
        for store in manifest["stores"]:
            for name, count in store["counts"].items():
                totals[name] = totals.get(name, 0) + count
        print("Saved records:", ", ".join(f"{name}: {count}" for name, count in totals.items()))
        if manifest.get("environment_names"):
            print("Review machine environment settings on the new laptop:",
                  ", ".join(manifest["environment_names"]))
        print("Private/session-only chats and browser appearance preferences are not stored in this backup.")
    except (Exception, KeyboardInterrupt):
        # Third-party exception messages can contain filenames or secret payloads.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, ValueError) else "Operation failed. Check file permissions, available space and that this is the original Windows account."
        print("Backup/restore stopped:", message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
