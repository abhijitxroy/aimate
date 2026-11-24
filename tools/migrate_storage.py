"""Encrypt existing databases with verified rollback copies; stop AiMate first."""
import argparse
import os
import sys
from pathlib import Path
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import migrate, password, plaintext
from app.device_key import load_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / ".data")
    parser.add_argument("--application-stopped", action="store_true",
                        help="Confirm all AiMate processes using this data directory have stopped.")
    args = parser.parse_args()
    if not args.application_stopped:
        raise ValueError("Stop the app first, then use --application-stopped.")
    root = args.data_dir.resolve()
    if not root.is_dir():
        raise ValueError("Data directory not found.")
    migrated = 0
    for path in sorted(root.rglob("app.sqlite3")):
        if not path.resolve().is_relative_to(root):
            raise ValueError("Database path leaves the selected data directory.")
        key = load_key(path.parent)
        migrated += int(migrate(path, key))
        cipher = Fernet(key)
        value = password(path.parent, cipher)
        legacy = path.parent / "access-password.txt"
        if legacy.exists():
            if cipher.decrypt((path.parent / "access-password.fernet").read_bytes()).decode() != value:
                raise ValueError("Protected password verification failed; original preserved.")
            legacy.unlink()
        # Only our named rollback snapshots: convert representation, retain data.
        for snapshot in path.parent.glob("before-*.sqlite3"):
            if not snapshot.resolve().is_relative_to(root):
                raise ValueError("Snapshot path leaves the selected directory.")
            if plaintext(snapshot):
                protected = snapshot.with_suffix(".sqlite3.fernet")
                raw = snapshot.read_bytes()
                encoded = cipher.encrypt(raw)
                if cipher.decrypt(encoded) != raw:
                    raise ValueError("Snapshot protection failed.")
                with protected.open("xb") as file:
                    file.write(encoded)
                    file.flush()
                    os.fsync(file.fileno())
                snapshot.unlink()
    print(f"Storage migration verified: {migrated} databases encrypted; rollback data retained encrypted.")


if __name__ == "__main__":
    main()
