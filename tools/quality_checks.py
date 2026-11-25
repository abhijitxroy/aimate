"""Fast source checks without starting AiMate, reading user data or deploying."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_pages import pages_html


def check_pages():
    if (ROOT / "index.html").read_text(encoding="utf-8") != pages_html():
        raise ValueError("index.html is stale. Run: python tools/build_pages.py --index-only")


def main():
    check_pages()
    files = sorted(path for directory in ("app/static", "pages", "tests", "tools")
                   for path in (ROOT / directory).rglob("*")
                   if path.is_file() and path.suffix in {".js", ".cjs", ".mjs"})
    for path in files:
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        if result.returncode:
            raise ValueError(f"JavaScript syntax check failed: {path.relative_to(ROOT)}\n{result.stderr}")
    print(f"Pages interface matches its source; {len(files)} JavaScript files passed syntax checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
