"""Check distributable assets and optional loopback startup; never deploy."""
import argparse
from http.client import RemoteDisconnected
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_pages import build, pages_html


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        value = values.get("src") if tag in {"script", "img"} else values.get("href") if tag == "link" else None
        if value and (value.startswith("./") or value.startswith("/static/")):
            self.paths.append(value)


def check_pages():
    with tempfile.TemporaryDirectory(prefix="aimate-build-") as directory:
        site = Path(directory) / "_site"
        build(site)
        html = (site / "index.html").read_text(encoding="utf-8")
        if html != pages_html():
            raise ValueError("Packaged interface differs from the shared UI.")
        parser = Assets()
        parser.feed(html)
        for value in parser.paths:
            path = (site / urlsplit(value).path).resolve()
            if not path.is_relative_to(site.resolve()) or not path.is_file():
                raise ValueError("Packaged asset is missing or outside the package: " + value)
        files = [path for path in site.rglob("*") if path.is_file()]
        for path in files:
            relative = path.relative_to(site)
            allowed = relative.as_posix() in {"index.html", ".nojekyll"} or relative.parts[:2] == ("app", "static") or relative.parts[0] == "pages"
            if not allowed or path.name.startswith(".env") or path.suffix in {".sqlite3", ".aimate-backup"}:
                raise ValueError("Unexpected file in public package: " + relative.as_posix())
        print(f"Pages package passed: {len(files)} files; {len(parser.paths)} referenced assets present.")


def check_server(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username or
            parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("Startup smoke checks require an HTTP 127.0.0.1 origin.")
    origin = url.rstrip("/")
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 30
    while True:
        try:
            with opener.open(origin + "/healthz", timeout=2) as response:
                if json.load(response) != {"status": "ok"}:
                    raise ValueError("Unexpected health response.")
            break
        except (URLError, ConnectionError, TimeoutError, RemoteDisconnected):
            if time.monotonic() >= deadline:
                raise ValueError("The app did not become healthy within 30 seconds.") from None
            time.sleep(.25)
    with opener.open(origin + "/", timeout=5) as response:
        html = response.read().decode("utf-8")
    if 'id="question"' not in html:
        raise ValueError("The app did not serve the AiMate interface.")
    parser = Assets()
    parser.feed(html)
    for path in parser.paths:
        with opener.open(origin + path, timeout=5) as response:
            if not response.read():
                raise ValueError("Empty served asset: " + path)
    print(f"Loopback startup passed: healthy app, interface and {len(parser.paths)} assets.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Optional already-running isolated app origin.")
    args = parser.parse_args()
    check_pages()
    if args.url:
        check_server(args.url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
