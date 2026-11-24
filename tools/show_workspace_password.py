"""Run yourself in a private local terminal to view the existing dev password."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.store import Store

if __name__ == "__main__":
    store = Store()
    try:
        print(store.password)
    finally:
        store.db.close()
