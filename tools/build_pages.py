"""Package the real AiMate interface for GitHub Pages, without backend data."""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pages_html():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    html = html.replace('"/static/', '"./app/static/')
    return html.replace(
        '  <script src="./app/static/theme.js"></script>',
        '  <script src="./pages/config.js"></script>\n'
        '  <script src="./pages/preview.js"></script>\n'
        '  <script src="./app/static/theme.js"></script>',
    )


def build(destination):
    destination = Path(destination).resolve()
    if destination == ROOT or ROOT in destination.parents and destination.parts[-1] != "_site":
        raise ValueError("Use a dedicated _site directory or an external build directory.")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("The build directory must be empty to prevent publishing unrelated files.")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "index.html").write_text(pages_html(), encoding="utf-8")
    shutil.copytree(ROOT / "app/static", destination / "app/static", dirs_exist_ok=True)
    shutil.copytree(ROOT / "pages", destination / "pages", dirs_exist_ok=True)
    (destination / ".nojekyll").touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "_site"))
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()
    if args.index_only:
        (ROOT / "index.html").write_text(pages_html(), encoding="utf-8")
    else:
        build(args.output)
