"""Real browser + HTTP + SSE checks against a fully isolated fixture backend."""
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

import httpx


@unittest.skipUnless(os.environ.get("AIMATE_BROWSER_TESTS") == "1", "Dedicated browser workflow")
class BrowserRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}"
        root = Path(__file__).resolve().parents[1]
        cls.server = subprocess.Popen([sys.executable, str(root / "tools/browser_test_server.py"),
                                       "--port", str(port)], cwd=root,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if cls.server.poll() is not None:
                        raise RuntimeError(cls.server.stderr.read().decode())
                    try:
                        if client.get(cls.url).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError("Fixture server did not start.")
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.server.terminate()
            cls.server.wait(timeout=10)
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.server.stderr.close()

    def setUp(self):
        from playwright.sync_api import expect
        self.expect = expect
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()
        self.page.goto(self.url)
        self.page.locator("#password").fill("browser-regression-password")
        self.page.locator("#loginForm button[type=submit]").click()
        self.expect(self.page.locator("#workspace")).to_be_visible()

    def tearDown(self):
        self.context.close()

    def test_todo_expansion_preserves_text_and_visible_controls(self):
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openTodos").click()
        row = self.page.locator(".todo-row").first
        text = row.locator(".todo-text")
        self.expect(text).to_contain_text("Step 19")
        collapsed = text.bounding_box()["height"]
        row.get_by_role("button", name="Show more", exact=True).click()
        self.expect(row).to_have_class("todo-row expanded")
        self.assertGreater(text.bounding_box()["height"], collapsed * 3)
        for name in ("Copy", "Edit", "Delete"):
            control = row.get_by_role("button", name=name, exact=True)
            box = control.bounding_box()
            self.assertGreaterEqual(box["x"], 0)
            self.assertLessEqual(box["x"] + box["width"], 1280)
        row.get_by_role("button", name="Show less", exact=True).click()
        self.expect(row).to_have_class("todo-row")

    def test_auto_uses_analysis_over_http_stream_and_survives_reload(self):
        self.page.locator("#question").fill("Debug this failing pipeline and analyse the root cause.")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        self.expect(self.page.locator("#messages")).to_contain_text("Analysis model answered.")
        usage = self.context.request.get(self.url + "/api/usage?days=30").json()
        self.assertIn("analysis-fixture", [model["model"] for model in usage["models"]])
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        self.expect(self.page.locator("#conversations")).to_contain_text("Debug this failing pipeline")

    def test_old_chat_recall_after_reload_and_history_window(self):
        self.page.locator("#conversations").get_by_role("button", name="Old continuity reference", exact=True).click()
        self.page.reload()
        self.page.locator("#conversations").get_by_role("button", name="Old continuity reference", exact=True).click()
        self.page.locator("#question").fill("Which ticket and pull request were we discussing?")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        self.expect(self.page.locator("#messages")).to_contain_text("DEMO-8437 · PR #1257")
        self.expect(self.page.locator("#chatTitle")).to_have_text("Old continuity reference")
