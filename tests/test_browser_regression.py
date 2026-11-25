"""Real browser + HTTP + SSE checks against a fully isolated fixture backend."""
import os
import io
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
            from playwright.sync_api import expect
            cls.login_states=[]
            cls.context_counter=0
            # Independent sessions keep the real login/chat rate limits enabled.
            for _ in range(4):
                login_context = cls.browser.new_context()
                login_page = login_context.new_page()
                login_page.goto(cls.url)
                login_page.locator("#password").fill("browser-regression-password")
                login_page.locator("#loginForm button[type=submit]").click()
                expect(login_page.locator("#workspace")).to_be_visible()
                cls.login_states.append(login_context.storage_state())
                login_context.close()
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
        state=self.login_states[type(self).context_counter % len(self.login_states)]
        type(self).context_counter+=1
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800}, storage_state=state)
        self.page = self.context.new_page()
        self.page.goto(self.url)
        self.expect(self.page.locator("#workspace")).to_be_visible()

    def tearDown(self):
        self.context.close()

    def test_monogram_colour_picker_persists_and_theme_reset(self):
        self.page.evaluate("openConversationIcon(conversationList.find(t => t.title === 'Old continuity reference'))")
        self.page.locator("#monogramIconMode").click()
        self.page.locator("#conversationIconValue").fill("CI")
        self.page.locator("#monogramColour").evaluate("(el) => { el.value='#ff7850'; el.dispatchEvent(new Event('input')); }")
        self.page.get_by_role("button", name="Save icon", exact=True).click()
        badge=self.page.get_by_role("button",name="Old continuity reference",exact=True).locator(".conversation-monogram")
        self.expect(badge).to_have_css("color","rgb(255, 120, 80)")
        self.page.reload()
        self.expect(badge).to_have_css("color","rgb(255, 120, 80)")
        self.page.evaluate("openConversationIcon(conversationList.find(t => t.title === 'Old continuity reference'))")
        self.expect(self.page.locator("#monogramColour")).to_have_value("#ff7850")
        self.page.locator("#monogramThemeColour").check()
        self.page.get_by_role("button", name="Save icon", exact=True).click()
        self.expect(badge).not_to_have_css("color","rgb(255, 120, 80)")

    def test_usage_budget_and_bill_comparison_persist(self):
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openUsage").click()
        self.expect(self.page.locator("#usageBilling")).to_contain_text("UTC")
        self.page.locator("#usageBudgetForm").locator("..").evaluate("(el) => { el.open = true; }")
        self.page.locator("#usageBudget").fill("12")
        self.page.locator("#usageBudgetMode").select_option("stop")
        self.page.get_by_role("button",name="Save budget",exact=True).click()
        self.expect(self.page.locator("#usageBilling")).to_contain_text("$12")
        self.page.locator("#usageInvoiceForm").locator("..").evaluate("(el) => { el.open = true; }")
        self.page.locator("#invoiceModel").fill("standard-fixture")
        self.page.locator("#invoiceAmount").fill("0.5")
        self.page.get_by_role("button",name="Save comparison",exact=True).click()
        self.expect(self.page.locator("#usageBilling")).to_contain_text("billed $0.50")
        self.expect(self.page.locator("#usageError")).to_have_text("")

    def test_admin_diagnostics_opens_sanitized_request_information(self):
        self.page.evaluate("openSettings()")
        self.page.locator("#tab-changes").click()
        self.page.locator("#openDiagnostics").click()
        self.expect(self.page.locator("#auditDialog")).to_be_visible()
        self.expect(self.page.locator("#auditContent")).to_contain_text("duration_ms")
        self.expect(self.page.locator("#auditContent")).not_to_contain_text("browser-regression-password")

    def test_github_scope_recovery_creates_review_card_without_model_request(self):
        action={"id":"scope-review","service":"settings","operation":"update_github_repositories",
                "status":"pending","preview":{"repository":"demo/new","before":[],"after":["demo/new"]}}
        self.page.route("**/api/conversations/*/repository-proposal",lambda route:route.fulfill(json=action))
        self.page.evaluate("""() => {
            cid="existing-conversation";
            const message=addMessage("assistant","The repository is outside scope.");
            renderGitHubGuidance(message,{repo:"demo/new",action:"validate_repository",message:"Validate access before adding."});
        }""")
        self.page.get_by_role("button",name="Validate & review repository",exact=True).click()
        self.expect(self.page.locator('[data-action="scope-review"]')).to_be_visible()
        self.expect(self.page.get_by_role("button",name="Confirm change",exact=True)).to_be_visible()
        self.expect(self.page.get_by_role("button",name="Access verified · confirm below",exact=True)).to_be_disabled()

    def test_cleanup_requires_preview_then_explicit_confirmation(self):
        plan={"documents":[{"id":"orphan","name":"old.txt","bytes":100}],"expired_cache":[],"logs":[],
              "estimated_bytes":100,"fingerprint":"reviewed","notice":"Referenced data is protected."}
        self.page.route("**/api/maintenance",lambda route:route.fulfill(json=plan))
        self.page.route("**/api/maintenance/cleanup",lambda route:route.fulfill(json={
            "removed":{"documents":1,"expired_cache":0,"logs":0,"skipped_logs":0}}))
        self.page.evaluate("openSettings()");self.page.locator("#tab-changes").click()
        self.page.locator("#openMaintenance").click()
        self.expect(self.page.locator("#cleanupItems")).to_contain_text("old.txt")
        self.expect(self.page.locator("#confirmCleanup")).to_be_enabled()
        self.page.locator("#confirmCleanup").click()
        self.expect(self.page.locator("#cleanupError")).to_contain_text("Completed")

    def test_saved_prompt_preserves_multiline_text_and_inserts_into_composer(self):
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openKnowledge").click();self.page.locator("#openLibrary").click()
        self.page.locator("#libraryTitle").fill("Evidence review")
        text="Summarize this work.\n\n- Evidence\n- Open questions"
        self.page.locator("#libraryBody").fill(text)
        self.page.locator("#saveLibrary").click()
        card=self.page.locator("#libraryItems .knowledge-card").filter(has_text="Evidence review")
        self.expect(card).to_contain_text("Open questions")
        card.get_by_role("button",name="Insert",exact=True).click()
        self.expect(self.page.locator("#question")).to_have_value(text)
        self.expect(self.page.locator("#libraryDialog")).not_to_be_visible()

    def test_custom_analysis_template_can_be_selected_as_request_style(self):
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openKnowledge").click();self.page.locator("#openLibrary").click()
        self.page.locator("#libraryKind").select_option("template")
        self.page.locator("#libraryTitle").fill("Concise review")
        self.page.locator("#libraryBody").fill("Return findings and coverage in a short table.")
        self.page.locator("#saveLibrary").click()
        card=self.page.locator("#libraryItems .knowledge-card").filter(has_text="Concise review")
        self.expect(card.get_by_role("button",name="Use style",exact=True)).to_be_visible()
        card.get_by_role("button",name="Use style",exact=True).click()
        self.expect(self.page.locator("#analysisStyle option:checked")).to_have_text("Concise review")
        self.page.locator("#question").fill("Review this change")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)

    def test_task_type_column_filter_and_edit_preserve_multiline_text(self):
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openTodos").click()
        self.page.locator("#todoType").select_option("bug")
        self.page.locator("#todoTitle").fill("Typed task\n- Keep details")
        self.page.locator("#saveTodo").click()
        row=self.page.locator(".todo-row").filter(has_text="Typed task")
        self.expect(row.locator(".todo-kind")).to_have_text("Bug")
        self.page.locator("#todoTypeFilter").select_option("feature")
        self.expect(self.page.locator(".todo-row").filter(has_text="Typed task")).to_have_count(0)
        self.page.locator("#todoTypeFilter").select_option("bug")
        row=self.page.locator(".todo-row").filter(has_text="Typed task")
        row.get_by_role("button",name="Edit",exact=True).click()
        self.expect(self.page.locator("#todoType")).to_have_value("bug")
        self.expect(self.page.locator("#todoTitle")).to_have_value("Typed task\n- Keep details")
        self.page.locator("#todoType").select_option("triage")
        self.page.locator("#saveTodo").click()
        self.page.locator("#todoTypeFilter").select_option("triage")
        self.expect(self.page.locator(".todo-row").filter(has_text="Typed task").locator(".todo-kind")).to_have_text("Triage")

    def test_screenshot_message_and_card_survive_reload_with_real_image_provider_blocks(self):
        from PIL import Image
        raw=io.BytesIO();Image.new("RGB",(40,30),"navy").save(raw,"PNG")
        self.page.locator("#textAttachment").set_input_files({"name":"Screenshot.png","mimeType":"image/png","buffer":raw.getvalue()})
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("Screenshot.png")
        self.page.locator("#question").fill("Explain the screenshot")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        self.page.reload()
        self.expect(self.page.locator("#messages .message.user")).to_contain_text("Explain the screenshot")
        self.expect(self.page.locator("#messages .attachment-card")).to_contain_text("Screenshot.png")

    def test_large_paste_is_a_document_card_and_saved_message_keeps_card(self):
        self.page.evaluate("""() => {
            const transfer = new DataTransfer();
            transfer.setData("text/plain", "Large pasted evidence\\n".repeat(400));
            document.querySelector("#question").dispatchEvent(new ClipboardEvent("paste", {clipboardData:transfer,bubbles:true,cancelable:true}));
        }""")
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("Pasted text.txt")
        self.expect(self.page.locator("#question")).to_have_value("")
        self.page.locator("#question").fill("Summarize the attachment")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#messages .attachment-card")).to_contain_text("Pasted text.txt")
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")

    def test_parallel_chats_keep_answers_and_stop_is_scoped_to_visible_chat(self):
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Parallel first")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Thinking…")
        first=self.page.evaluate("cid")
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Parallel second")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#workspace")).to_have_attribute("data-answering","2")
        second=self.page.evaluate("cid")
        self.assertNotEqual(first,second)
        self.page.evaluate("id => openConversation(id)",first)
        self.page.locator("#stop").click()
        self.expect(self.page.locator("#activity")).to_contain_text("Stopped")
        self.page.evaluate("id => openConversation(id)",second)
        self.page.evaluate("() => api('/api/test/parallel/release',{method:'POST'})")
        self.expect(self.page.locator("#messages")).to_contain_text("Reply: Parallel second")
        self.expect(self.page.locator("#messages")).not_to_contain_text("Reply: Parallel first")
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        self.expect(self.page.locator("#workspace")).to_have_attribute("data-answering","0")

    def test_todo_expansion_preserves_text_and_visible_controls(self):
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openTodos").click()
        row = self.page.locator(".todo-row").filter(has_text="Long task")
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

    def test_confirmed_repository_change_collapses_and_opens_github_details(self):
        action = {"id": "browser-repo-change", "service": "settings",
                  "operation": "update_github_repositories", "status": "pending",
                  "preview": {"repository": "demo/project", "before": [], "after": ["demo/project"]}}
        completed = dict(action, status="completed", result={"saved": True})
        self.page.route("**/api/actions/browser-repo-change/confirm",
                        lambda route: route.fulfill(json=completed))
        self.page.evaluate("""action => {
            connectionReports.github = {status: "passed", message: "Read access verified.",
                targets: [{target: "demo/project", ok: true, message: "Accessible",
                           details: ["Default branch: main"]}]};
            drawAction(action, document.querySelector("#messages"));
            drawAction(action, document.querySelector("#messages"));
        }""", action)
        card = self.page.locator('[data-action="browser-repo-change"]')
        self.assertEqual(card.count(), 1)
        self.expect(card.locator("pre")).to_be_visible()
        card.get_by_role("button", name="Confirm change", exact=True).click()
        self.expect(card).to_have_class("action-card action-completed")
        self.expect(card).to_contain_text("Completed")
        self.assertEqual(card.locator("pre").count(), 0)
        self.assertEqual(card.get_by_role("button", name="Confirm change", exact=True).count(), 0)
        self.page.evaluate("action => drawAction(action, document.querySelector('#messages'))", action)
        self.assertEqual(card.count(), 1)
        self.assertEqual(card.locator("pre").count(), 0)
        # refreshState replaces the reports; supply the saved verification for navigation.
        self.page.evaluate("""() => { connectionReports.github = {status: "passed",
            message: "Read access verified.", targets: [{target: "demo/project", ok: true,
            message: "Accessible", details: ["Default branch: main"]}]}; }""")
        card.get_by_role("button", name="Check connection", exact=True).click()
        self.expect(self.page.locator("#settingsDialog")).to_be_visible()
        self.expect(self.page.locator('[data-settings-tab="github"]')).to_have_attribute("aria-selected", "true")
        self.expect(self.page.locator("#test-github .connection-target p").first).to_be_visible()
        self.expect(self.page.locator("#test-github")).to_contain_text("demo/project")
        # History reconstruction uses the same compact completed view.
        self.page.evaluate("""action => {
            document.querySelector("#settingsDialog").close();
            document.querySelector("#messages").replaceChildren();
            drawAction(action, document.querySelector("#messages"));
        }""", completed)
        self.expect(self.page.locator(".action-completed")).to_be_visible()
        self.assertEqual(self.page.locator(".action-completed pre").count(), 0)
        # Failed confirmations still retain their diagnostic preview.
        self.page.evaluate("action => drawAction({...action, id: 'failed-change', status: 'failed'}, document.querySelector('#messages'))", action)
        self.expect(self.page.locator('[data-action="failed-change"] pre')).to_be_visible()

    def test_other_obsolete_proposal_collapses_when_confirmation_refreshes_actions(self):
        first = {"id": "first-review", "service": "settings", "operation": "update_github_repositories",
                 "status": "pending", "preview": {"repository": "demo/first"}}
        second = dict(first, id="second-review", preview={"repository": "demo/second"})
        completed = dict(first, status="completed")
        obsolete = dict(second, status="superseded")
        self.page.route("**/api/actions/first-review/confirm", lambda route: route.fulfill(json=completed))
        self.page.route("**/api/conversations/browser-reviews/actions",
                        lambda route: route.fulfill(json={"actions": [completed, obsolete]}))
        self.page.evaluate("""cards => {
            cid = 'browser-reviews';
            for (const card of cards) drawAction(card, document.querySelector('#messages'));
        }""", [first, second])
        self.page.locator('[data-action="first-review"]').get_by_role("button", name="Confirm change", exact=True).click()
        stale = self.page.locator('[data-action="second-review"]')
        self.expect(stale).to_contain_text("Settings changed")
        self.expect(stale).to_be_hidden()
        self.assertEqual(self.page.locator(".action-card pre").count(), 0)
        self.assertEqual(self.page.get_by_role("button", name="Confirm change", exact=True).count(), 0)
        # A genuinely separate, valid pending request still needs approval.
        self.page.evaluate("card => drawAction(card, document.querySelector('#messages'))",
                           dict(second, id="valid-new-review"))
        self.expect(self.page.locator('[data-action="valid-new-review"]').get_by_role("button", name="Confirm change", exact=True)).to_be_visible()

    def test_private_mode_active_colour_in_all_themes(self):
        toggle = self.page.locator("#privateToggle")
        for theme in ("navy", "beige", "black-blue"):
            self.page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            toggle.click()
            self.expect(toggle).to_have_attribute("aria-pressed", "true")
            self.page.wait_for_function("() => getComputedStyle(document.querySelector('#privateToggle')).backgroundColor === 'rgb(117, 38, 60)'")
            toggle.click()
            self.expect(toggle).to_have_attribute("aria-pressed", "false")

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

    def test_early_ask_waits_for_chat_restore_without_creating_duplicate(self):
        button = self.page.locator("#conversations").get_by_role("button", name="Old continuity reference", exact=True)
        button.click()
        self.expect(self.page.locator("#chatTitle")).to_have_text("Old continuity reference")
        before = self.context.request.get(self.url + "/api/state").json()["conversations"]
        existing = self.page.evaluate("cid")
        turns = len(self.context.request.get(self.url + "/api/conversations/" + existing).json()["turns"])
        # Hold the real navigation fetch while submitting a follow-up twice.
        self.page.evaluate("""() => {
            const original = window.fetch;
            window.fetch = async (...args) => {
                if (/^\\/api\\/conversations\\/[^/]+$/.test(String(args[0])))
                    await new Promise(resolve => setTimeout(resolve, 350));
                return original(...args);
            };
            cid = null;
            restoreConversation();
            ask('Which ticket and pull request were we discussing?');
            ask('Which ticket and pull request were we discussing?');
        }""")
        self.expect(self.page.locator("#messages")).to_contain_text("DEMO-8437 · PR #1257", timeout=15000)
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        after = self.context.request.get(self.url + "/api/state").json()["conversations"]
        self.assertEqual({row["id"] for row in before}, {row["id"] for row in after})
        self.assertEqual(self.page.evaluate("cid"), existing)
        self.assertEqual(len(self.context.request.get(self.url + "/api/conversations/" + existing).json()["turns"]), turns + 1)

    def test_edit_resend_keeps_chat_and_group(self):
        self.page.locator("#conversations").get_by_role("button", name="Old continuity reference", exact=True).click()
        self.expect(self.page.locator("#chatTitle")).to_have_text("Old continuity reference")
        existing = self.page.evaluate("cid")
        before = self.context.request.get(self.url + "/api/state").json()["conversations"]
        self.page.get_by_role("button", name="Edit your message", exact=True).last.click()
        self.page.get_by_role("textbox", name="Edit message", exact=True).fill("Debug my corrected task.")
        self.page.get_by_role("button", name="Save & resend", exact=True).click()
        self.expect(self.page.locator("#messages")).to_contain_text("Debug my corrected task.", timeout=15000)
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        after = self.context.request.get(self.url + "/api/state").json()["conversations"]
        self.assertEqual({row["id"] for row in before}, {row["id"] for row in after})
        self.assertEqual(self.page.evaluate("cid"), existing)

    def test_vault_requires_unlock_and_explicit_lock_clears_revealed_values(self):
        self.page.locator("#headerSettings").click()
        self.page.locator('[data-settings-tab="changes"]').click()
        self.page.locator("#openVault").click()
        self.expect(self.page.locator("#vaultUnlockForm")).to_be_visible()
        self.page.locator("#vaultVerification").fill("browser-regression-password")
        self.page.locator("#vaultUnlockForm button").click()
        self.expect(self.page.locator("#lockVault")).to_be_visible()
        self.page.locator("#vaultEditor summary").click()
        self.page.locator("#vaultName").fill("Browser synthetic entry")
        self.page.locator("#vaultValue").fill("synthetic-browser-secret")
        self.page.locator("#vaultForm button").click()
        card = self.page.locator("#vaultEntries .knowledge-card").filter(has_text="Browser synthetic entry")
        card.get_by_role("button", name="Reveal", exact=True).click()
        self.expect(card.locator(".vault-revealed")).to_have_text("synthetic-browser-secret")
        self.page.locator("#lockVault").click()
        self.expect(self.page.locator("#vaultEntries")).to_be_empty()
        self.expect(self.page.locator("#vaultUnlockForm")).to_be_visible()
        self.assertFalse(self.context.request.get(self.url + "/api/vault/status").json()["unlocked"])
