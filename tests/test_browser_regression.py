"""Real browser + HTTP + SSE checks against a fully isolated fixture backend."""
import os
import io
import json
import re
import socket
import subprocess
import sys
import tempfile
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
        # A PIPE that is only read after exit can fill and block the fixture's
        # event loop while logging a cancelled request. Keep diagnostics on disk.
        cls.server_output=tempfile.TemporaryFile()
        cls.server = subprocess.Popen([sys.executable, str(root / "tools/browser_test_server.py"),
                                       "--port", str(port)], cwd=root,
                                      stdout=subprocess.DEVNULL, stderr=cls.server_output)
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if cls.server.poll() is not None:
                        cls.server_output.seek(0)
                        raise RuntimeError(cls.server_output.read(10000).decode(errors="replace"))
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
            # The growing suite can send >10 requests per reused session within
            # a minute on fast runners. Isolate more sessions without weakening
            # the real chat limit or exceeding the eight-login allowance.
            for _ in range(8):
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
            cls.server_output.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.server_output.seek(0)
        diagnostics=cls.server_output.read().decode(errors="replace")
        cls.server_output.close()
        if diagnostics:sys.stderr.write("\nIsolated fixture diagnostics:\n"+diagnostics[-8000:]+"\n")

    def setUp(self):
        from playwright.sync_api import expect
        self.expect = expect
        state=self.login_states[type(self).context_counter % len(self.login_states)]
        type(self).context_counter+=1
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800}, storage_state=state)
        self.page = self.context.new_page()
        self.page.on("response", lambda response: print(
            f"Fixture chat error: HTTP {response.status} {response.text()}",
            file=sys.stderr) if response.url.endswith("/api/chat") and response.status >= 400 else None)
        if self._testMethodName == "test_generated_panels_expand_editor_and_reveal_insertions":
            # Keep legacy textarea geometry covered alongside new inline-editor checks.
            self.page.add_init_script("window.AiMateFeatures={richComposer:false}")
        self.page.goto(self.url)
        self.expect(self.page.locator("#workspace")).to_be_visible()

    def tearDown(self):
        self.context.close()

    def local_settings(self):
        self.page.locator("#headerSettings").click()
        self.page.locator('[name="ai.provider"]').select_option("local")
        self.expect(self.page.locator("#localAISettings")).to_be_visible()

    def test_incomplete_answer_checkpoint_is_visible_and_survives_reload(self):
        self.page.locator("#question").fill("Output limit fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Investigation incomplete · checkpoint saved")
        self.expect(self.page.locator("#messages")).to_contain_text("This investigation is incomplete.")
        self.page.reload()
        self.expect(self.page.locator("#messages")).to_contain_text("This investigation is incomplete.")
        self.page.locator("#question").fill("Continue")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")

    def test_empty_final_answer_recovers_findings_without_repeating_search(self):
        self.page.locator("#question").fill("Empty final fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Findings ready · review evidence gaps")
        self.expect(self.page.locator("#messages")).to_contain_text("Synthetic recovered findings")
        self.page.reload()
        self.expect(self.page.locator("#messages")).to_contain_text("Synthetic recovered findings")

    def test_user_auto_policy_quality_economy_and_reload(self):
        self.page.locator("#newChat").click()
        # Earlier provider-settings tests can leave Gemini or Bedrock selected.
        # Assert against actual configured slots, not the fixture's initial IDs.
        current_ai = self.page.request.get(self.url + "/api/state").json()["config"]["ai"]
        self.assertTrue(current_ai.get("analysis_model"))
        picker = self.page.locator("#modelMode")
        picker.select_option("auto-quality")
        self.expect(picker).to_contain_text("Auto · Quality")
        self.page.locator("#question").fill("Policy quality fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        self.page.locator(".model-info").first.locator("summary").click()
        self.expect(self.page.locator(".model-details").first).to_contain_text(current_ai["analysis_model"])
        self.page.reload()
        self.expect(self.page.locator("#modelMode")).to_have_value("auto-quality")
        self.page.locator("#modelMode").select_option("auto-economy")
        self.page.locator("#question").fill("Policy economy fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        self.page.locator(".model-info").last.locator("summary").click()
        self.expect(self.page.locator(".model-details").last).to_contain_text(current_ai["model"])

    def test_expanded_composer_retains_draft_formatting_attachments_and_restores(self):
        self.page.locator("#newChat").click()
        field = self.page.locator("#question")
        draft = "**Quarterly report**\n\n| Item | Count |\n| --- | --- |\n| Builds | 42 |\n" + "Detail\n" * 80
        field.fill(draft)
        self.page.locator("#textAttachment").set_input_files({
            "name": "sample.txt", "mimeType": "text/plain", "buffer": b"Fixture document"
        })
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("sample.txt")
        field.evaluate("(node)=>{node.selectionStart=2;node.selectionEnd=18}")
        toggle = self.page.locator("#composerExpand")
        normal_height = self.page.locator(".cm-scroller").bounding_box()["height"]
        toggle.click()
        self.expect(toggle).to_have_attribute("aria-expanded", "true")
        self.expect(self.page.locator("#chatForm")).to_have_attribute("aria-modal", "true")
        self.assertTrue(self.page.locator("#messages").evaluate("(node)=>node.inert"))
        self.assertEqual(field.evaluate("(node)=>node.value"), draft)
        self.assertEqual(field.evaluate("(node)=>[node.selectionStart,node.selectionEnd]"), [2, 18])
        self.assertGreater(self.page.locator(".cm-scroller").bounding_box()["height"], normal_height + 150)
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("sample.txt")
        self.assertGreater(self.page.locator(".cm-inline-bold").count(), 0)
        self.page.locator("#send").focus()
        self.page.keyboard.press("Tab")
        self.expect(toggle).to_be_focused()
        self.page.keyboard.press("Escape")
        self.expect(toggle).to_have_attribute("aria-expanded", "false")
        self.assertFalse(self.page.locator("#messages").evaluate("(node)=>node.inert"))
        self.assertEqual(field.evaluate("(node)=>node.value"), draft)
        self.assertEqual(field.evaluate("(node)=>[node.selectionStart,node.selectionEnd]"), [2, 18])
        self.page.set_viewport_size({"width": 390, "height": 700})
        self.page.evaluate("document.documentElement.dataset.theme='beige'")
        toggle.click()
        panel = self.page.locator("#chatForm").bounding_box()
        self.assertGreaterEqual(panel["x"], 0)
        self.assertLessEqual(panel["x"] + panel["width"], 390)
        self.expect(self.page.locator("#send")).to_be_visible()
        self.page.get_by_role("button", name="Restore editor", exact=True).click()
        self.assertEqual(field.evaluate("(node)=>node.value"), draft)

    def test_expanded_composer_plain_fallback_and_disabled_module(self):
        self.page.add_init_script("window.AiMateFeatures={richComposer:false}")
        self.page.reload()
        field = self.page.locator("#question")
        field.fill("Multiline\n" * 60)
        self.page.get_by_role("button", name="Expand editor", exact=True).click()
        self.assertGreater(field.bounding_box()["height"], 300)
        field.press("Escape")
        self.expect(field).to_have_value("Multiline\n" * 60)
        self.page.add_init_script("window.AiMateFeatures={richComposer:false,composerExpand:false}")
        self.page.reload()
        self.assertEqual(self.page.locator("#composerExpand").count(), 0)
        field.fill("Core editor still works")
        self.expect(field).to_have_value("Core editor still works")

    def test_message_rail_markers_are_compact_for_short_and_long_chats(self):
        self.page.locator("#newChat").click()
        self.page.evaluate("""() => {
            addMessage("user","First"); addMessage("assistant","Second");
        }""")
        rail = self.page.locator(".message-rail")
        self.expect(rail).to_be_visible()
        markers = rail.locator("button")
        self.assertLessEqual(rail.bounding_box()["height"], 20)
        bounds = rail.bounding_box()
        messages = self.page.locator("#messages").bounding_box()
        self.assertAlmostEqual(bounds["y"] + bounds["height"] / 2,
                               messages["y"] + messages["height"] / 2, delta=1)
        self.assertLessEqual(markers.nth(1).bounding_box()["y"] - markers.first.bounding_box()["y"], 10)
        self.page.evaluate("""() => {
            for(let i=0;i<150;i++) addMessage("assistant","Message "+i);
        }""")
        self.expect(markers).to_have_count(152)
        bounds = rail.bounding_box()
        messages = self.page.locator("#messages").bounding_box()
        self.assertAlmostEqual(bounds["y"] + bounds["height"] / 2,
                               messages["y"] + messages["height"] / 2, delta=1)
        self.assertLessEqual(bounds["y"] + bounds["height"], messages["y"] + messages["height"])
        markers.first.focus()
        markers.first.press("End")
        self.expect(markers.last).to_be_focused()
        self.expect(self.page.locator(".message-rail-preview")).to_contain_text("Message 149")

    def test_reply_glow_tracks_generation_preference_and_reduced_motion(self):
        form = self.page.locator("#chatForm")
        self.assertNotIn("composer-generating", form.get_attribute("class"))
        # Imports disable Ask too, but only an active generation exposes Stop.
        self.page.evaluate("document.querySelector('#send').disabled=true")
        self.assertNotIn("composer-generating", form.get_attribute("class"))
        self.page.evaluate("document.querySelector('#stop').hidden=false")
        self.expect(form).to_have_class(re.compile(r"composer-generating"))
        self.page.locator("#openAppearance").click()
        toggle = self.page.locator("#composerGlowToggle")
        toggle.uncheck()
        self.expect(form).not_to_have_class(re.compile(r"composer-generating"))
        toggle.check()
        self.expect(form).to_have_class(re.compile(r"composer-generating"))
        self.page.locator('[data-close="appearanceDialog"]').click()
        self.page.emulate_media(reduced_motion="reduce")
        self.assertEqual(form.evaluate("(node)=>getComputedStyle(node,'::after').animationName"), "none")
        self.page.evaluate("document.querySelector('#stop').hidden=true")
        self.expect(form).not_to_have_class(re.compile(r"composer-generating"))
        self.page.locator("#openAppearance").click()
        toggle.uncheck()
        self.page.reload()
        self.page.locator("#openAppearance").click()
        self.expect(toggle).not_to_be_checked()
        self.page.locator('[data-close="appearanceDialog"]').click()
        self.page.evaluate("document.querySelector('#stop').hidden=false")
        self.expect(form).not_to_have_class(re.compile(r"composer-generating"))

    def test_message_rail_hover_tapers_without_moving_content(self):
        self.page.locator("#newChat").click()
        self.page.evaluate("""() => {
            for(let i=0;i<15;i++) addMessage("assistant","Preview "+i);
        }""")
        markers = self.page.locator(".message-rail button")
        self.expect(markers).to_have_count(15)
        self.page.emulate_media(reduced_motion="reduce")
        before = self.page.locator("#messages").bounding_box()
        markers.nth(7).hover()
        self.expect(self.page.locator(".message-rail-preview")).to_contain_text("Preview 7")
        widths = [markers.nth(i).evaluate("(n)=>parseFloat(getComputedStyle(n,'::after').width)")
                  for i in (3, 4, 5, 6, 7, 8, 9, 10, 11)]
        self.assertEqual(widths, [6, 9, 14, 20, 28, 20, 14, 9, 6])
        self.assertEqual(self.page.locator("#messages").bounding_box(), before)
        self.page.locator("#question").click()
        self.expect(self.page.locator(".message-rail-preview")).to_be_hidden()
        self.assertEqual(markers.nth(7).evaluate("(n)=>n.style.getPropertyValue('--rail-marker-width')"), "")
        self.assertIn(markers.nth(7).evaluate("(n)=>getComputedStyle(n,'::after').width"), ("4px", "8px"))
        markers.nth(0).focus()
        self.assertEqual(markers.nth(0).evaluate("(n)=>getComputedStyle(n,'::after').width"), "28px")
        markers.nth(0).press("Escape")
        self.expect(self.page.locator(".message-rail-preview")).to_be_hidden()

    def test_clarification_choices_wait_for_user_keep_draft_and_reload(self):
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Clarify fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Waiting for your answer")
        self.expect(self.page.locator("#messages")).to_contain_text("Which build should I review?")
        choices = self.page.locator(".clarification-choices")
        self.expect(choices).to_be_visible()
        self.page.reload()
        self.expect(choices).to_be_visible()
        self.page.locator("#question").fill("Keep this note.")
        choices.get_by_role("button", name="Build 11", exact=True).click()
        self.assertTrue(self.page.locator("#question").evaluate("(n)=>n.value").startswith("Keep this note.\n\nRegarding"))
        self.assertIn("Build 11", self.page.locator("#question").evaluate("(n)=>n.value"))
        self.expect(choices).to_contain_text("Review and send.")
        self.expect(self.page.locator("#send")).to_be_enabled()

    def test_modern_tables_use_subtle_rows_and_keep_scrolling_and_fallback(self):
        self.page.locator("#newChat").click()
        self.page.evaluate("""() => addMessage("assistant",
            "| Check | Result |\\n| --- | --- |\\n| Linux | Passed |\\n| Windows | Review |")""")
        table = self.page.locator("#messages .answer-table").last
        self.expect(table).to_have_class(re.compile(r"answer-table-modern"))
        for theme in ("navy", "beige", "black-blue", "brown-gold", "life"):
            self.page.evaluate("t=>window.AiMateAppearance.apply(t)", theme)
            self.expect(table).to_have_css("border-top-width", "0px")
            self.expect(table.locator("td").first).to_have_css("border-left-width", "0px")
            self.expect(table.locator("td").first).to_have_css("border-bottom-width", "1px")
            self.expect(table.locator("th").first).to_have_css("color",
                self.page.locator("body").evaluate("(n)=>getComputedStyle(n).color"))
        self.page.evaluate("""() => {
            const headings=Array.from({length:20},(_,i)=>"Column"+i).join(" | ");
            const rules=Array(20).fill("---").join(" | ");
            const values=Array(20).fill("A long value").join(" | ");
            addMessage("assistant","| "+headings+" |\\n| "+rules+" |\\n| "+values+" |");
        }""")
        wide = self.page.locator("#messages .answer-table").last
        self.assertGreater(wide.evaluate("(n)=>n.scrollWidth"), wide.evaluate("(n)=>n.clientWidth"))
        self.page.evaluate("""() => {
            window.AiMateFeatures={modernTables:false};
            addMessage("assistant","| A | B |\\n| --- | --- |\\n| C | D |");
        }""")
        fallback = self.page.locator("#messages .answer-table").last
        self.assertNotIn("answer-table-modern", fallback.get_attribute("class"))

    def test_claude_full_catalog_and_direct_askbar_choice_preserve_slots(self):
        self.page.locator("#newChat").click()
        self.page.locator("#headerSettings").click()
        self.page.locator('[name="ai.provider"]').select_option("bedrock")
        self.page.locator('[name="ai.bedrock_mode"]').select_option("advanced")
        self.page.locator('[name="ai.region"]').fill("us-east-2")
        self.page.locator('[name="ai.api_key"]').fill("synthetic-fixture")
        self.page.locator("#bedrockModel").select_option("us.anthropic.claude-haiku-5-5")
        self.page.locator("#settingsDialog .model-selection summary").click()
        self.page.locator("#bedrockAnalysisModel").select_option("us.anthropic.claude-sonnet-5-5")
        self.page.locator("#saveConnection").click()
        self.expect(self.page.locator("#settingsStatus")).to_contain_text("Saved.")
        self.page.locator('[data-close="settingsDialog"]').click()
        self.expect(self.page.locator("#settingsDialog")).to_be_hidden()
        self.expect(self.page.locator("#modelMode")).to_contain_text("Sonnet 4.6")
        picker = self.page.locator("#modelMode")
        self.expect(picker).to_contain_text("Fable 5.2")
        chosen = "global.anthropic.claude-opus-5-5"
        picker.select_option("manual:" + chosen)
        self.expect(picker.locator('option[value="auto"]')).to_contain_text("Haiku 5.5")
        self.page.locator("#question").fill("Direct model fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        self.page.locator(".model-info").last.locator("summary").click()
        self.expect(self.page.locator(".model-details").last).to_contain_text(chosen)
        self.page.reload()
        self.expect(picker).to_have_value("manual:" + chosen)
        state = self.page.request.get(self.url + "/api/state").json()["config"]["ai"]
        self.assertEqual(state["model"], "us.anthropic.claude-haiku-5-5")
        self.assertEqual(state["analysis_model"], "us.anthropic.claude-sonnet-5-5")
        self.page.locator("#headerSettings").click()
        self.page.locator('[name="ai.bedrock_mode"]').select_option("advanced")
        self.expect(self.page.locator("#bedrockModel")).to_contain_text("US Claude Sonnet 4.6")
        self.expect(self.page.locator("#bedrockModel")).to_contain_text("Global Claude Opus 5.5")

    def test_reply_glow_real_stream_stops_and_optional_module_can_be_disabled(self):
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Glow held fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#chatForm")).to_have_class(re.compile(r"composer-generating"))
        self.expect(self.page.locator("#activity")).to_have_text("Thinking…")
        held = self.page.evaluate("cid")
        self.page.locator("#newChat").click()
        self.expect(self.page.locator("#chatForm")).not_to_have_class(re.compile(r"composer-generating"))
        self.page.evaluate("id=>openConversation(id)", held)
        self.expect(self.page.locator("#chatForm")).to_have_class(re.compile(r"composer-generating"))
        self.page.locator("#stop").click()
        self.expect(self.page.locator("#chatForm")).not_to_have_class(re.compile(r"composer-generating"))
        self.page.locator("#question").fill("Glow finished fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        self.expect(self.page.locator("#chatForm")).not_to_have_class(re.compile(r"composer-generating"))
        self.page.add_init_script("window.AiMateFeatures={composerGlow:false}")
        self.page.reload()
        self.assertEqual(self.page.locator("#composerGlowToggle").count(), 0)
        self.page.evaluate("document.querySelector('#stop').hidden=false")
        self.assertNotIn("composer-generating", self.page.locator("#chatForm").get_attribute("class"))

    def local_fixture(self):
        self.page.route("**/api/local-ai/status",lambda route:route.fulfill(status=200,content_type="application/json",
            body=json.dumps({"available":True,"models":["qwen3:4b"],"message":"Ollama reachable."})))
        stops=[]
        def stop(route):
            stops.append(route.request.post_data_json)
            route.fulfill(status=200,content_type="application/json",body=json.dumps({"message":"Stopped."}))
        self.page.route("**/api/local-ai/stop",stop)
        return stops

    def test_local_stop_unload_is_explicit_and_cloud_controls_stay_usable(self):
        stops=self.local_fixture()
        self.assertEqual(self.page.locator("#localAIToggle, #stopLocalAI, #localStopStatus").count(),0)
        self.local_settings()
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")
        self.page.locator("#saveConnection").click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")
        self.page.locator("#useLocalAI").click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("On")
        self.page.locator("#useCloudAI").click()
        self.expect(self.page.locator("#localAIMessage")).to_have_text("Local AI off. Model memory released.")
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")
        self.assertEqual(stops,[{"model":"qwen3:4b","unload":True}])
        self.page.locator('[data-close="settingsDialog"]').click()
        self.expect(self.page.locator("#send")).to_be_enabled()
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        self.local_settings()
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")

    def test_local_stop_targets_visible_request_and_immediately_releases_composer(self):
        stops=self.local_fixture()
        self.page.route("**/api/chat",lambda route:None)
        self.local_settings()
        self.page.locator("#useLocalAI").click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("On")
        self.page.locator('[data-close="settingsDialog"]').click()
        requests=[]
        for text in ("First local request","Second local request"):
            self.page.locator("#newChat").click()
            self.page.locator("#question").fill(text)
            with self.page.expect_request("**/api/chat") as sent:
                self.page.locator("#send").click()
            requests.append(sent.value.post_data_json)
            self.expect(self.page.locator("#stop")).to_be_visible()
        self.page.locator("#headerSettings").click()
        self.page.locator("#useCloudAI").click()
        self.expect(self.page.locator("#localAIMessage")).to_have_text("Local AI off. Model memory released.")
        self.assertEqual(stops,[*[{"conversation":body["conversation"],"request_id":body["request_id"],"unload":False}
            for body in requests],{"model":"qwen3:4b","unload":True}])
        self.page.locator('[data-close="settingsDialog"]').click()
        self.expect(self.page.locator("#send")).to_be_enabled()
        self.expect(self.page.locator("#stop")).to_be_hidden()
        self.assertEqual(self.page.evaluate("()=>chatRuns.size()"),0)

    def test_local_ai_choice_and_cloud_failure_offer_are_explicit_and_optional(self):
        self.local_fixture()
        requests=[]
        def chat(route):
            body=route.request.post_data_json;requests.append(body)
            events=([{ "event":"text","delta":"Local fallback answered."},{"event":"done"}]
                if body.get("local_ai") else [{"event":"error","message":"Cloud unavailable.","local_fallback":True}])
            route.fulfill(status=200,content_type="text/event-stream",
                body="".join("data: "+json.dumps(event)+"\n\n" for event in events))
        self.page.route("**/api/chat",chat)
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Local consent check")
        self.page.locator("#send").click()
        self.expect(self.page.get_by_role("button",name="Open AI connections",exact=True)).to_be_visible()
        self.assertEqual(len(requests),1)
        self.assertFalse(requests[0]["local_ai"])
        self.expect(self.page.locator("#offlineAIDialog")).to_be_hidden()
        self.page.get_by_role("button",name="Open AI connections",exact=True).click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")
        self.page.locator("#useLocalAI").click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("On")
        self.page.locator('[data-close="settingsDialog"]').click()
        self.page.locator("#question").fill("Try local explicitly")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#messages")).to_contain_text("Local fallback answered.")
        self.assertTrue(requests[-1]["local_ai"])
        self.page.evaluate("()=>{window.AiMateFeatures={...window.AiMateFeatures,localAI:false};document.dispatchEvent(new Event('aimate:state'));}")
        self.assertFalse(self.page.evaluate("()=>window.AiMateLocalAI.active()"))

    def test_connection_stop_during_enable_check_never_reactivates_local_ai(self):
        self.local_fixture()
        self.local_settings()
        self.expect(self.page.locator("#useLocalAI")).to_be_enabled()
        checks=[]
        self.page.unroute("**/api/local-ai/status")
        self.page.route("**/api/local-ai/status",lambda route:checks.append(route))
        self.page.locator("#useLocalAI").click()
        self.expect(self.page.locator("#checkLocalAI")).to_be_disabled()
        self.page.locator("#useCloudAI").click()
        self.expect(self.page.locator("#localAIMessage")).to_have_text("Local AI off. Model memory released.")
        checks[-1].fulfill(status=200,content_type="application/json",body=json.dumps({
            "available":True,"models":["qwen3:4b"],"message":"Ollama reachable."}))
        self.expect(self.page.locator("#checkLocalAI")).to_be_enabled()
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")
        self.assertFalse(self.page.evaluate("()=>window.AiMateLocalAI.active()"))

    def test_local_connection_picker_keeps_cloud_settings_and_hides_cloud_fields(self):
        self.page.route("**/api/local-ai/status",lambda route:route.fulfill(status=200,content_type="application/json",
            body=json.dumps({"available":True,"models":["qwen3:4b"],"message":"Ollama reachable."})))
        writes=[]
        self.page.route("**/api/settings/ai",lambda route:(writes.append(route.request.post_data),
            route.fulfill(status=400,content_type="application/json",body='{"detail":"Must not save local as cloud."}')))
        before=self.page.evaluate("()=>JSON.stringify(config.ai)")
        self.page.locator("#headerSettings").click()
        picker=self.page.locator('[name="ai.provider"]')
        picker.select_option("local")
        self.expect(self.page.locator("#localAISettings")).to_be_visible()
        self.expect(self.page.locator("#localAIMessage")).to_contain_text("Ollama reachable")
        for selector in ["#apiCredentials","#apiModelLabel","#chatgptConnection","#testAIButton","#settings-ai .model-selection"]:
            self.expect(self.page.locator(selector)).to_be_hidden()
        self.page.locator("#saveConnection").click()
        self.expect(self.page.locator("#settingsStatus")).to_contain_text("Cloud settings kept")
        self.assertEqual(writes,[])
        self.assertEqual(self.page.evaluate("()=>JSON.stringify(config.ai)"),before)
        self.page.locator("#useCloudAI").click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")
        self.assertFalse(self.page.evaluate("()=>window.AiMateLocalAI.active()"))
        self.page.evaluate("()=>{window.AiMateFeatures={...window.AiMateFeatures,localAI:false};document.dispatchEvent(new Event('aimate:state'));}")
        self.assertTrue(picker.locator('[value="local"]').is_disabled())
        self.expect(self.page.locator("#localAISettings")).to_be_hidden()

    def test_offline_popup_without_cloud_or_model_preserves_draft_and_never_submits(self):
        self.page.route("**/api/local-ai/status",lambda route:route.fulfill(status=200,content_type="application/json",
            body=json.dumps({"available":True,"models":[],"message":"Ollama reachable."})))
        requests=[]
        self.page.route("**/api/chat",lambda route:(requests.append(route.request.post_data),route.abort()))
        self.page.evaluate("()=>{config.ai={};}")
        self.page.locator("#question").fill("Keep this offline draft")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#offlineAIDialog")).to_be_visible()
        self.expect(self.page.locator("#offlineAIReason")).to_contain_text("No cloud AI connection")
        self.expect(self.page.locator("#offlineAIStatus")).to_contain_text("No models installed")
        self.assertEqual(self.page.locator("#continueOfflineAI").count(),0)
        self.page.locator("#cancelOfflineAI").click()
        self.expect(self.page.locator("#offlineAIDialog")).to_be_hidden()
        self.expect(self.page.locator("#question")).to_have_js_property("value","Keep this offline draft")
        self.assertEqual(requests,[])
        self.page.unroute("**/api/local-ai/status")
        self.page.route("**/api/local-ai/status",lambda route:route.fulfill(status=200,content_type="application/json",
            body=json.dumps({"available":False,"models":[],"message":"Start Ollama on this laptop."})))
        self.page.locator("#send").click()
        self.expect(self.page.locator("#offlineAIStatus")).to_contain_text("Start Ollama")
        self.assertEqual(self.page.locator("#continueOfflineAI").count(),0)
        self.page.keyboard.press("Escape")
        self.expect(self.page.locator("#offlineAIDialog")).to_be_hidden()
        self.assertEqual(requests,[])

    def test_missing_cloud_popup_uses_local_only_after_consent(self):
        self.page.route("**/api/local-ai/status",lambda route:route.fulfill(status=200,content_type="application/json",
            body=json.dumps({"available":True,"models":["qwen3:4b"],"message":"Ollama reachable."})))
        requests=[]
        def answer(route):
            requests.append(route.request.post_data_json)
            route.fulfill(status=200,content_type="text/event-stream",body='data: {"event":"text","delta":"Offline consent answered."}\n\ndata: {"event":"done"}\n\n')
        self.page.route("**/api/chat",answer)
        self.page.evaluate("()=>{config.ai={};}")
        self.page.locator("#question").fill("Use offline only when I agree")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#offlineAIConnections")).to_be_enabled()
        self.assertEqual(requests,[])
        self.page.locator("#offlineAIConnections").click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("Off")
        self.assertEqual(requests,[])
        self.page.locator("#useLocalAI").click()
        self.expect(self.page.locator("#localAIState")).to_contain_text("On")
        self.page.locator('[data-close="settingsDialog"]').click()
        self.page.locator("#send").click()
        self.expect(self.page.locator("#messages")).to_contain_text("Offline consent answered.")
        self.assertEqual(len(requests),1)
        self.assertTrue(requests[0]["local_ai"])
        self.assertEqual(requests[0]["display_question"],"Use offline only when I agree")

    def test_browser_offline_notice_does_not_switch_or_download_on_cancel(self):
        calls=[]
        self.page.route("**/api/local-ai/status",lambda route:route.fulfill(status=200,content_type="application/json",
            body=json.dumps({"available":True,"models":["qwen3:4b"],"message":"Ollama reachable."})))
        self.page.route("**/api/chat",lambda route:(calls.append(route.request.post_data),route.abort()))
        self.page.evaluate("()=>Object.defineProperty(navigator,'onLine',{configurable:true,value:false})")
        self.page.locator("#question").fill("Keep cloud until I choose")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#offlineAIReason")).to_have_text("You appear to be offline.")
        self.expect(self.page.locator("#offlineAIConnections")).to_be_enabled()
        self.page.locator("#cancelOfflineAI").click()
        self.assertFalse(self.page.evaluate("()=>window.AiMateLocalAI.active()"))
        self.expect(self.page.locator("#question")).to_have_js_property("value","Keep cloud until I choose")
        self.assertEqual(calls,[])

    def test_cancelling_offline_popup_during_recheck_never_activates_local(self):
        checks=[];calls=[]
        self.page.route("**/api/local-ai/status",lambda route:checks.append(route))
        self.page.route("**/api/chat",lambda route:(calls.append(route.request.post_data),route.abort()))
        self.page.evaluate("()=>{config.ai={};}")
        self.page.locator("#question").fill("Cancel the pending local switch")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#offlineAIDialog")).to_be_visible()
        self.page.locator("#cancelOfflineAI").click()
        checks[-1].fulfill(status=200,content_type="application/json",body=json.dumps({
            "available":True,"models":["qwen3:4b"],"message":"Ollama reachable."}))
        self.expect(self.page.locator("#checkLocalAI")).to_be_enabled()
        self.assertFalse(self.page.evaluate("()=>window.AiMateLocalAI.active()"))
        self.expect(self.page.locator("#question")).to_have_js_property("value","Cancel the pending local switch")
        self.assertEqual(calls,[])

    def test_verified_new_repo_read_offers_one_review_option_without_failure_banner(self):
        guidance={"repo":"team/new","read_verified":True,"action":"validate_repository",
            "message":"Read access verified for this question. Add this source only for later chats."}
        events=[{"event":"repository_access","guidance":guidance},
                {"event":"repository_access","guidance":guidance},
                {"event":"text","delta":"Requested PR read; saved scope is unchanged."},
                {"event":"done","usage":{"input_tokens":2,"output_tokens":3},"model":"standard-fixture","mode":"standard"}]
        self.page.route("**/api/chat",lambda route:route.fulfill(status=200,content_type="text/event-stream",
            body="".join("data: "+json.dumps(event)+"\n\n" for event in events)))
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Read team/new PR 7")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#messages .source-recovery")).to_have_count(1)
        self.expect(self.page.locator("#messages")).to_contain_text("Requested PR read")
        self.expect(self.page.get_by_role("button",name="Validate & review repository",exact=True)).to_be_visible()
        self.expect(self.page.locator("#messages .tool-failure")).to_have_count(0)

    def test_performance_baselines_measure_requests_and_optional_ui_leaves_chat_usable(self):
        self.page.evaluate("async()=>{for(let i=0;i<6;i++)await api('/api/todos');}")
        self.page.locator("#headerSettings").click()
        self.page.locator("#tab-changes").click()
        self.page.locator("#openPerformance").click()
        self.expect(self.page.locator("#performanceDialog")).to_be_visible()
        self.expect(self.page.locator("#performanceRows")).to_contain_text("To-do")
        self.expect(self.page.locator("#performanceStats")).to_contain_text("Process CPU")
        self.page.locator("#performanceBaselineLabel").fill("Browser before cache")
        self.page.locator("#performanceBaselineForm button").click()
        self.expect(self.page.locator("#performanceBaselineSummary")).to_be_visible()
        self.expect(self.page.locator("#performanceError")).to_be_empty()
        self.page.locator('[data-close="performanceDialog"]').click()
        self.page.locator('[data-close="settingsDialog"]').click()
        self.page.reload()
        self.page.locator("#headerSettings").click()
        self.page.locator("#tab-changes").click()
        self.page.locator("#openPerformance").click()
        self.expect(self.page.locator("#performanceBaseline")).to_contain_text("Browser before cache")
        self.page.locator('[data-close="performanceDialog"]').click()
        self.page.locator('[data-close="settingsDialog"]').click()
        self.page.evaluate("()=>{window.AiMateFeatures={...window.AiMateFeatures,performanceDashboard:false};document.dispatchEvent(new Event('aimate:state'));}")
        self.page.locator("#headerSettings").click()
        self.page.locator("#tab-changes").click()
        self.expect(self.page.locator("#openPerformance")).to_be_hidden()
        self.page.locator('[data-close="settingsDialog"]').click()
        self.page.locator("#question").fill("Core draft still works")
        self.expect(self.page.locator("#question")).to_have_js_property("value","Core draft still works")

    def test_recents_controls_share_one_row_and_heading_collapses_without_moving_chat(self):
        self.page.evaluate("""async () => {
            for(let i=0;i<9;i++) {
                const chat=await api('/api/conversations',{method:'POST',body:'{}'});
                await api('/api/conversations/'+chat.id,{method:'PATCH',body:JSON.stringify({title:'Recents controls '+i})});
            }
            await refreshState();
        }""")
        section=self.page.locator("#recentSection")
        self.assertTrue(section.evaluate("(node) => node.previousElementSibling.matches('hr.conversation-section-divider') && node.parentElement.id === 'conversations'"))
        heading=section.locator(":scope > summary")
        more=section.get_by_role("button",name="Show five more recent chats",exact=True)
        less=section.get_by_role("button",name="Show only three recent chats",exact=True)
        self.expect(section.locator(".conversation-link")).to_have_count(3)
        self.expect(more).to_be_enabled()
        self.expect(less).to_be_disabled()
        self.expect(section.locator(".recent-page-controls svg")).to_have_count(2)
        more.click()
        self.expect(section.locator(".conversation-link")).to_have_count(8)
        self.expect(less).to_be_enabled()
        a,b=more.bounding_box(),less.bounding_box()
        self.assertEqual(a["y"],b["y"])
        self.assertGreaterEqual(b["x"],a["x"]+a["width"])
        main=self.page.locator("main").bounding_box()
        heading.click()
        self.expect(heading).to_have_attribute("aria-expanded","false")
        self.expect(more).to_be_hidden()
        self.expect(section.locator(".conversation-link").first).to_be_hidden()
        self.assertEqual(self.page.locator("main").bounding_box(),main)
        self.page.reload()
        self.expect(heading).to_have_attribute("aria-expanded","false")
        heading.focus()
        heading.press("Enter")
        self.expect(section.locator(".conversation-link").first).to_be_visible()
        self.expect(section.locator(".conversation-link")).to_have_count(3)

    def test_format_show_hide_preserves_draft_and_remembers_visibility(self):
        field=self.page.locator("#question")
        field.fill("**Keep this draft**")
        toggle=self.page.locator("#formatToggle")
        self.expect(self.page.locator("#composerFormatting")).to_be_visible()
        toggle.click()
        self.expect(self.page.locator("#composerFormatting")).to_be_hidden()
        self.expect(field).to_have_js_property("value","**Keep this draft**")
        self.expect(toggle).to_have_attribute("title","Show formatting")
        toggle.click()
        self.expect(self.page.locator("#composerFormatting")).to_be_visible()
        self.expect(field).to_have_js_property("value","**Keep this draft**")
        toggle.click()
        self.page.reload()
        self.expect(self.page.locator("#composerFormatting")).to_be_hidden()
        self.expect(toggle).to_have_attribute("aria-expanded","false")
        toggle.click()
        self.expect(self.page.get_by_role("button",name="Bold",exact=True)).to_be_visible()

    def test_pin_stays_at_top_of_own_project_before_subprojects_and_recents_below(self):
        data=self.page.evaluate("""async () => {
            const parent=await api('/api/groups',{method:'POST',body:JSON.stringify({name:'Pin parent project'})});
            const child=await api('/api/groups',{method:'POST',body:JSON.stringify({name:'Pin subproject',parent:parent.id})});
            const other=await api('/api/groups',{method:'POST',body:JSON.stringify({name:'Other pin project'})});
            const chats=[];
            for(const title of ['Old pin fixture','New pin fixture']) {
                const c=await api('/api/conversations',{method:'POST',body:JSON.stringify({group_id:parent.id})});
                await api('/api/conversations/'+c.id,{method:'PATCH',body:JSON.stringify({title})});
                chats.push(c.id);
            }
            expandedGroups.add(parent.id);await refreshState();return {parent:parent.id,child:child.id,other:other.id,chat:chats[0]};
        }""")
        project=self.page.locator(f'[data-group="{data["parent"]}"]')
        row=project.locator(".conversation-row").filter(has_text="Old pin fixture")
        row.get_by_role("button",name="Actions for Old pin fixture",exact=True).click()
        self.page.get_by_role("menuitem",name="Pin",exact=True).click()
        self.expect(row.locator(".conversation-pin svg")).to_have_count(1)
        self.assertEqual(project.locator(":scope > .group-children").evaluate(
            "el => el.firstElementChild.querySelector('.conversation-label').textContent"),"Old pin fixture")
        state=self.context.request.get(self.url+"/api/state").json()
        self.assertEqual(next(c for c in state["conversations"] if c["id"]==data["chat"])["group_id"],data["parent"])
        self.assertTrue(project.evaluate("el => Boolean(el.compareDocumentPosition(document.querySelector('#recentConversations')) & Node.DOCUMENT_POSITION_FOLLOWING)"))
        row.get_by_role("button",name="Actions for Old pin fixture",exact=True).click()
        self.page.get_by_role("menuitem",name="Unpin",exact=True).click()
        self.expect(row.locator(".conversation-pin")).to_have_count(0)
        self.assertEqual(project.locator(":scope > .group-children").evaluate(
            "el => el.firstElementChild.dataset.group"),data["child"])

    def test_supplied_input_quality_does_not_count_user_text_as_external_verification(self):
        self.page.evaluate("""() => {
            const msg=addMessage('assistant','Supplied snippet review.',984,Date.now()/1000);
            msg.root.id='supplied-quality-fixture';
            updateModelInfo(msg,{quality:{version:1,kind:'review',assessed:true,confidence:'medium',
              coverage:'partial',basis:'Supplied input only.',gaps:['Runtime tests not run.'],
              further_investigation:true,next_step:'Run a representative test.',
              source_count:1,input_evidence:'input:current-message'}});
        }""")
        quality=self.page.locator("#supplied-quality-fixture .quality-info")
        title=quality.locator("summary").get_attribute("title")
        self.assertIn("Input evidence: Current user message",title)
        self.assertIn("External sources read: 0",title)
        self.assertIn("Accuracy: Not independently measured",title)
        quality.locator("summary").click()
        self.expect(quality.locator(".quality-details")).to_contain_text("not independent external verification")

    def test_answer_quality_is_tiny_contextual_safe_and_dismissible(self):
        self.page.evaluate("""() => {
            const msg=addMessage('assistant','Evidence-backed partial review.',987,Date.now()/1000);
            msg.root.id='quality-fixture';
            updateModelInfo(msg,{mode:'auto',model:'fixture',usage:{input_tokens:4000,output_tokens:1200},
              quality:{version:1,kind:'review',assessed:true,confidence:'medium',basis:'Source read; tests not run.',
                coverage:'partial',gaps:['<img src=x onerror=alert(1)>'],further_investigation:true,
                next_step:'Run the affected tests.',accuracy:'not_measured',source_count:2,failed_reads:1}});
        }""")
        root=self.page.locator("#quality-fixture")
        quality=root.locator(".quality-info")
        self.expect(quality.locator("summary")).to_have_text("Confidence · MediumAccuracy · UnverifiedCompletion · Not assessed")
        self.assertIn("Accuracy: Not independently measured",quality.locator("summary").get_attribute("title"))
        self.assertEqual(quality.locator("summary").evaluate("el=>getComputedStyle(el).fontSize"),"9px")
        self.assertEqual(root.locator(".message-meta").evaluate(
            "el=>Array.from(el.children).map(child=>child.className)"),
            ["model-info","quality-info model-info","message-time"])
        quality.locator("summary").click()
        self.expect(quality.locator(".quality-details")).to_be_visible()
        self.expect(quality.locator(".quality-details")).to_contain_text("Not independently measured")
        self.expect(quality.locator(".quality-details")).to_contain_text("<img src=x onerror=alert(1)>")
        self.expect(quality.locator("img")).to_have_count(0)
        self.page.locator("#chatTitle").click()
        self.assertFalse(quality.evaluate("el=>el.open"))
        quality.locator("summary").click()
        self.page.keyboard.press("Escape")
        self.assertFalse(quality.evaluate("el=>el.open"))
        self.page.evaluate("""() => {
            const msg=addMessage('assistant','Hello.',988,Date.now()/1000);msg.root.id='quality-none';
            updateModelInfo(msg,{mode:'auto',model:'fixture',usage:{input_tokens:1,output_tokens:1}});
            const search=addMessage('assistant','Source lookup.',989,Date.now()/1000);search.root.id='quality-search';
            updateModelInfo(search,{mode:'standard',model:'fixture',quality:{version:1,kind:'search',assessed:true,
                confidence:'low',basis:'One source, not corroborated.',source_count:1}});
            window.AiMateFeatures={...window.AiMateFeatures,answerQuality:false};
            window.AiMateAnswerQuality.update(search,{version:1,kind:'review',assessed:false});
        }""")
        self.expect(self.page.locator("#quality-none .quality-info")).to_have_count(0)
        self.expect(self.page.locator("#quality-search .quality-info")).to_have_count(0)
        self.expect(self.page.locator("#quality-search > .message-meta > .model-info")).to_have_count(1)
        self.page.evaluate("""() => {
            window.AiMateFeatures.answerQuality=true;
            const msg=addMessage('assistant','A source lookup.',990,Date.now()/1000);msg.root.id='quality-search-visible';
            updateModelInfo(msg,{mode:'auto',model:'fixture',quality:{version:1,kind:'search',assessed:true,
                confidence:'low',basis:'One source, not corroborated.',source_count:1}});
        }""")
        search=self.page.locator("#quality-search-visible .quality-info")
        search.locator("summary").click()
        self.expect(search.locator(".quality-details")).to_contain_text("Not independently measured")
        self.assertNotIn("Further investigation",search.locator(".quality-details").inner_text())
        self.assertNotIn("Coverage",search.locator(".quality-details").inner_text())

    def test_quality_percentages_show_colours_and_auditable_checklists(self):
        self.page.evaluate("""() => {
            const msg=addMessage('assistant','Partial fix.',994,Date.now()/1000);msg.root.id='quality-score-fixture';
            updateModelInfo(msg,{quality:{version:1,kind:'analysis',assessed:true,confidence:'medium',
              coverage:'partial',basis:'Source checked.',gaps:['One task pending.'],further_investigation:true,
              accuracy_percent:60,completion_percent:80,checks:[{claim:'Claim',supported:true,source:'fixture:source'}],
              work_items:[{task:'Run live tests',completed:false}]}});
        }""")
        root=self.page.locator("#quality-score-fixture")
        scores=root.locator(".quality-score")
        self.expect(scores.nth(0)).to_have_text("Accuracy · ~60%")
        self.expect(scores.nth(0)).to_have_attribute("data-band","partial")
        self.expect(scores.nth(1)).to_have_text("Completion · 80%")
        self.expect(scores.nth(1)).to_have_attribute("data-band","good")
        self.assertNotEqual(scores.nth(0).evaluate("e=>getComputedStyle(e).color"),
                            scores.nth(1).evaluate("e=>getComputedStyle(e).color"))
        root.locator(".quality-info > summary").click()
        self.expect(root.locator(".quality-details")).to_contain_text("not independently measured accuracy")
        self.expect(root.locator(".quality-details")).to_contain_text("Pending: Run live tests")

    def test_pasted_numbered_prompt_has_compact_layout_without_losing_intentional_breaks(self):
        source = "Review the flow.\n\n\n1. Read the journal.\n\n2. Check `package_failure_import.py`.\n\n3. Verify storage.\n\n\nKeep separate paragraphs.\n\nAnd literal code:\n\n```python\nx=1\n\n\nprint(x)\n```"
        self.page.evaluate("""source => {
            const data=new DataTransfer();data.setData('text/plain',source);
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
              {clipboardData:data,bubbles:true,cancelable:true}));
        }""", source)
        field = self.page.locator("#question")
        value = field.evaluate("e=>e.value")
        self.assertIn("1. Read the journal.\n2. Check", value)
        self.assertIn("storage.\n\nKeep separate paragraphs.\n\nAnd literal", value)
        self.assertIn("x=1\n\n\nprint(x)", value)
        # Also render the original loose-list source, as already saved chats
        # must improve without modifying the user's historical records.
        self.page.evaluate("""source => {
            addMessage('user',source).root.id='spacing-saved';
            addMessage('user','First line.\\n\\nSecond paragraph.').root.id='spacing-plain';
        }""", source)
        root = self.page.locator("#spacing-saved")
        self.expect(root.locator("li")).to_have_count(3)
        self.assertEqual(root.locator(".body").evaluate("e=>getComputedStyle(e).whiteSpace"), "normal")
        distance = root.locator("li").evaluate_all("""items=>
            items[1].getBoundingClientRect().top-items[0].getBoundingClientRect().top""")
        self.assertLess(distance, 36)
        self.expect(root.locator("pre code")).to_have_text("x=1\n\n\nprint(x)\n")
        self.assertEqual(self.page.locator("#spacing-plain .body").evaluate(
            "e=>getComputedStyle(e).whiteSpace"), "pre-wrap")
        self.expect(self.page.locator("#spacing-plain .body")).to_have_text("First line.\n\nSecond paragraph.")

    def test_pasted_prose_removes_empty_bullets_and_excess_spacing_but_preserves_code(self):
        field=self.page.locator("#question")
        field.fill("")
        self.page.evaluate("""() => {
            const data=new DataTransfer();data.setData('text/plain','Hello,\\n\\n\\n\\nContext:\\n\\n- First\\n-\\n\\n- Second\\n\\n\\nThanks.');
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
              {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(field).to_have_js_property("value","Hello,\n\nContext:\n\n- First\n- Second\n\nThanks.")
        field.fill("")
        self.page.evaluate("""() => {
            const data=new DataTransfer();data.setData('text/plain','```python\\nx=1\\n\\n\\nprint(x)\\n```');
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
              {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(field).to_have_js_property("value","```python\nx=1\n\n\nprint(x)\n```")
        field.fill("")
        self.page.evaluate("""() => {
            window.AiMateFeatures={...window.AiMateFeatures,pasteCleanup:false};
            const data=new DataTransfer();data.setData('text/plain','Keep\\n\\n\\nspacing');
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
              {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(field).to_have_js_property("value","Keep\n\n\nspacing")

    def test_message_actions_are_below_borderless_replies_with_theme_aware_highlights(self):
        self.page.evaluate("""() => {
            const user=addMessage('user','Please review the evidence.',900);user.root.id='footer-user';
            const reply=addMessage('assistant',
              '### Next step\\n\\n[tone:success]**Recommended:** check the preserved evidence.[/tone]\\n\\n[tone:warning]Coverage gap: runtime tests were not run.[/tone]\\n\\n<img src=x onerror=alert(1)>',901);
            reply.root.id='footer-assistant';
        }""")
        for role in ("user","assistant"):
            root=self.page.locator("#footer-"+role)
            self.expect(root.locator(".message-heading button")).to_have_count(0)
            self.expect(root.locator(".message-actions button")).to_have_count(3)
            positions=root.evaluate("""el=>({bodyBottom:el.querySelector('.body').getBoundingClientRect().bottom,
                actionsTop:el.querySelector('.message-actions').getBoundingClientRect().top,
                actionsRight:el.querySelector('.message-actions').getBoundingClientRect().right,
                rootRight:el.getBoundingClientRect().right})""")
            self.assertGreaterEqual(positions["actionsTop"],positions["bodyBottom"])
            self.assertAlmostEqual(positions["actionsRight"],positions["rootRight"],delta=1)
        root=self.page.locator("#footer-assistant")
        self.expect(root.locator(".answer-tone-success")).to_contain_text("Recommended:")
        self.expect(root.locator(".answer-tone-warning")).to_contain_text("Coverage gap")
        self.expect(root.locator("img")).to_have_count(0)
        for theme in ("navy","beige","black-blue","life","brown-gold"):
            self.page.evaluate("theme=>window.AiMateAppearance.apply(theme)",theme)
            values=root.locator(".body").evaluate("""el=>{const style=getComputedStyle(el);
                return {border:style.borderTopWidth,background:style.backgroundColor,shadow:style.boxShadow,
                    text:style.color,success:getComputedStyle(el.querySelector('.answer-tone-success')).color}}""")
            self.assertEqual(values["border"],"0px")
            self.assertEqual(values["background"],"rgba(0, 0, 0, 0)")
            self.assertEqual(values["shadow"],"none")
            self.assertNotEqual(values["text"],values["success"])

    def test_local_evidence_owner_connect_validation_and_disconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            self.page.locator("#headerSettings").click()
            self.page.locator("#tab-changes").click()
            self.page.locator("#openLocalEvidence").click()
            self.expect(self.page.locator("#localEvidenceDialog")).to_be_visible()
            self.page.locator("#localEvidenceName").fill("fixture-local")
            self.page.locator("#localEvidencePath").fill(str(Path(folder)/"missing"))
            self.page.get_by_role("button",name="Connect folder",exact=True).click()
            self.expect(self.page.locator("#localEvidenceError")).to_contain_text("existing")
            self.page.locator("#localEvidencePath").fill(folder)
            self.page.get_by_role("button",name="Connect folder",exact=True).click()
            self.expect(self.page.locator("#localEvidenceStatus")).to_contain_text("read-only")
            self.expect(self.page.locator("#localEvidenceSources")).to_contain_text("fixture-local")
            state=self.context.request.get(self.url+"/api/state").json()
            self.assertNotIn("_local_evidence_roots",state["config"])
            self.page.locator("#localEvidenceSources").get_by_role("button",name="Disconnect",exact=True).click()
            self.expect(self.page.locator("#localEvidenceStatus")).to_contain_text("disconnected")
            self.expect(self.page.locator("#localEvidenceSources")).to_contain_text("No local folders")

    def test_selected_knowledge_index_import_and_safe_paged_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                subprocess.run(["git", "-c", "core.hooksPath=", "-C", folder, *args],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")})
            git("init")
            git("config", "user.email", "fixture@example.test")
            git("config", "user.name", "Fixture")
            text = "---\ntitle: Fixture reference\nstatus: active\n---\n<img src=x onerror=alert(1)>\n" + "pinned evidence " * 350
            (root / "reference.md").write_text(text, encoding="utf-8")
            git("add", "reference.md")
            git("-c", "commit.gpgsign=false", "commit", "-m", "fixture")
            self.page.locator("#headerSettings").click()
            self.page.locator("#tab-changes").click()
            self.page.locator("#openLocalEvidence").click()
            self.page.locator("#localEvidenceName").fill("knowledge-fixture")
            self.page.locator("#localEvidencePath").fill(folder)
            self.page.get_by_role("button", name="Connect folder", exact=True).click()
            self.expect(self.page.locator("#localEvidenceStatus")).to_contain_text("read-only")
            self.page.locator("#knowledgeIndexSection > summary").click()
            self.page.locator("#knowledgeIndexSource").select_option("knowledge-fixture")
            self.page.locator("#knowledgeIndexPaths").fill("reference.md")
            self.page.get_by_role("button", name="Index selected documents", exact=True).click()
            self.expect(self.page.locator("#knowledgeIndexStatus")).to_contain_text("1 documents")
            self.page.locator("#knowledgeIndexEntries summary").click()
            self.page.get_by_role("button", name="Read document", exact=True).click()
            self.expect(self.page.locator("#knowledgeIndexEntries pre")).to_have_text(text)
            self.expect(self.page.locator("#knowledgeIndexEntries img")).to_have_count(0)
            self.page.locator("#localEvidenceSources").get_by_role("button", name="Disconnect", exact=True).click()
            self.expect(self.page.locator("#localEvidenceStatus")).to_contain_text("disconnected")

    def test_token_badge_includes_cache_reads_writes_and_restores_saved_breakdown(self):
        self.page.locator("#newChat").click()
        self.page.locator("#modelMode").select_option("standard")
        self.page.locator("#question").fill("Cache token fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        badge=self.page.locator(".message.assistant .model-info summary").last
        self.expect(badge).to_contain_text("568")
        badge.click()
        self.expect(self.page.locator(".message.assistant .model-token-counts")).to_contain_text("Cache read")
        self.expect(self.page.locator(".message.assistant .model-token-counts")).to_contain_text("400")
        self.expect(self.page.locator(".message.assistant .model-token-counts")).to_contain_text("Cache write")
        self.page.reload()
        self.expect(badge).to_contain_text("568")
    def test_task_priorities_persist_filter_and_respect_edit_lock(self):
        if not self.page.locator("#openTodos").is_visible():
            self.page.locator("#sidebarTools summary").click()
        self.page.locator("#openTodos").click()
        self.expect(self.page.locator("#todoPriority")).to_be_visible()
        self.page.locator("#todoTitle").fill("Priority fixture\nKeep multiline notes")
        self.page.locator("#todoPriority").select_option("P1")
        self.page.locator("#saveTodo").click()
        row=self.page.locator(".todo-row").filter(has_text="Priority fixture")
        self.expect(row.locator(".todo-priority")).to_have_text("P1")
        self.expect(row.get_by_role("button",name="Edit",exact=True)).to_be_disabled()
        self.page.locator("#todosEditLock").click()
        row.get_by_role("button",name="Edit",exact=True).click()
        self.expect(self.page.locator("#todoPriority")).to_have_value("P1")
        self.page.locator("#todoPriority").select_option("P0")
        self.page.locator("#saveTodo").click()
        self.page.locator("#todoPriorityFilter").select_option("P0")
        self.expect(row.locator(".todo-priority")).to_have_text("P0")
        row.get_by_role("button",name="Edit",exact=True).click()
        self.page.locator("#todosEditLock").click()
        self.expect(self.page.locator("#todoPriority")).to_be_disabled()
        self.page.locator("#cancelTodoEdit").click()
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        if not self.page.locator("#openTodos").is_visible():
            self.page.locator("#sidebarTools summary").click()
        self.page.locator("#openTodos").click()
        self.page.locator("#todoPriorityFilter").select_option("P0")
        self.expect(row.locator(".todo-priority")).to_have_text("P0")
        self.page.evaluate("window.AiMateFeatures={todoPriorities:false};loadTodos()")
        self.expect(self.page.locator("#todoPriority")).to_be_hidden()
        self.expect(row.locator(".todo-priority")).to_have_count(0)
        self.expect(row.get_by_role("button",name="Copy",exact=True)).to_be_visible()

    def test_recents_section_pages_three_then_five_and_does_not_duplicate_chats(self):
        self.page.evaluate("""async () => {
            for(let i=0;i<13;i++) {
                const chat=await api('/api/conversations',{method:'POST',body:'{}'});
                await api('/api/conversations/'+chat.id,{method:'PATCH',body:JSON.stringify({title:'Paging recent '+i})});
            }
            await refreshState();
        }""")
        recents=self.page.locator("#recentConversations")
        self.expect(recents.locator(".conversation-link")).to_have_count(3)
        self.expect(recents.get_by_role("button",name="Paging recent 12",exact=True)).to_be_visible()
        recents.get_by_role("button",name="Show five more recent chats",exact=True).click()
        self.expect(recents.locator(".conversation-link")).to_have_count(8)
        recents.get_by_role("button",name="Show five more recent chats",exact=True).click()
        self.expect(recents.locator(".conversation-link")).to_have_count(13)
        recents.get_by_role("button",name="Show only three recent chats",exact=True).click()
        self.expect(recents.locator(".conversation-link")).to_have_count(3)
        self.page.locator("#conversations").get_by_role("button",name="Paging recent 12",exact=True).click()
        self.expect(self.page.locator("#chatTitle")).to_have_text("Paging recent 12")
        before=self.context.request.get(self.url+"/api/state").json()["conversations"]
        self.page.reload()
        self.expect(recents.locator(".conversation-link")).to_have_count(3)
        after=self.context.request.get(self.url+"/api/state").json()["conversations"]
        self.assertEqual({c["id"] for c in before},{c["id"] for c in after})

    def test_message_time_follows_tokens_uses_saved_timestamp_and_survives_reload(self):
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Timestamp display check")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        ident=self.page.evaluate("cid")
        turn=self.context.request.get(self.url+"/api/conversations/"+ident).json()["turns"][-1]
        expected=self.page.evaluate("seconds => new Date(seconds*1000).toISOString()",turn["created"])
        clock=self.page.locator(".message.assistant .message-time").last
        self.expect(clock).to_have_attribute("datetime",expected)
        self.expect(clock).to_have_attribute("title",re.compile(r".*\d.*"))
        self.expect(clock).to_have_css("font-size","9px")
        self.expect(self.page.locator(".message.assistant .model-info + .message-time")).to_be_visible()
        self.page.reload()
        self.expect(clock).to_have_attribute("datetime",expected)
        self.expect(self.page.locator(".message.user .message-time").last).to_have_attribute("datetime",expected)
        self.page.evaluate("""() => {
            window.AiMateFeatures={messageTime:false};
            const msg=addMessage('assistant','Disabled timestamp fixture');
            updateModelInfo(msg,{mode:'auto',model:'fixture',usage:{input_tokens:1,output_tokens:1}});
            msg.root.id='disabled-clock-fixture';
        }""")
        self.expect(self.page.locator("#disabled-clock-fixture .message-time")).to_have_count(0)
        self.expect(self.page.locator("#disabled-clock-fixture .model-info")).to_be_visible()

    def test_recent_chats_show_more_less_keeps_open_chat_and_saved_history(self):
        gid=self.page.evaluate("""async () => {
            const folder=await api('/api/groups',{method:'POST',body:JSON.stringify({name:'Recent chats fixture'})});
            for(let i=0;i<8;i++) {
                const chat=await api('/api/conversations',{method:'POST',body:JSON.stringify({group_id:folder.id})});
                await api('/api/conversations/'+chat.id,{method:'PATCH',body:JSON.stringify({title:'Recent fixture '+i})});
            }
            expandedGroups.add(folder.id);await refreshState();return folder.id;
        }""")
        folder=self.page.locator(f'[data-group="{gid}"]')
        self.expect(folder.locator(".conversation-link")).to_have_count(5)
        folder.get_by_role("button",name="Show more chats in Recent chats fixture",exact=True).click()
        self.expect(folder.locator(".conversation-link")).to_have_count(8)
        folder.get_by_role("button",name="Recent fixture 0",exact=True).click()
        self.expect(self.page.locator("#chatTitle")).to_have_text("Recent fixture 0")
        folder.get_by_role("button",name="Show less chats in Recent chats fixture",exact=True).click()
        self.expect(folder.locator(".conversation-link")).to_have_count(6)
        self.expect(folder.get_by_role("button",name="Recent fixture 0",exact=True)).to_be_visible()
        state=self.context.request.get(self.url+"/api/state").json()
        self.assertEqual(len([c for c in state["conversations"] if c.get("group_id")==gid]),8)
        self.page.evaluate("window.AiMateFeatures={recentChats:false};refreshState()")
        self.expect(folder.locator(".conversation-link")).to_have_count(8)
        self.expect(folder.locator(".recent-chats-toggle")).to_have_count(0)

    def test_chat_timestamp_and_type_help_do_not_change_group_creation(self):
        chat = self.page.locator("#conversations").get_by_role(
            "button", name="Old continuity reference", exact=True)
        self.expect(chat).to_have_attribute("title", re.compile(r"Old continuity reference\nCreated: .+"))
        self.page.locator("#newGroup").click()
        help_button = self.page.get_by_role("button", name="About projects and workspaces", exact=True)
        self.expect(self.page.locator("#groupKind")).to_have_count(0)
        self.expect(self.page.locator("#groupDialogTitle")).to_have_text("New project")
        self.expect(self.page.locator("#projectHelp")).to_be_hidden()
        help_button.click()
        self.expect(self.page.locator("#projectHelp")).to_be_visible()
        self.expect(self.page.locator("#projectHelp")).to_contain_text("Project: organizes chats here.")
        self.page.locator("#groupName").click()
        self.page.locator("#groupName").fill("Timestamp help project")
        self.expect(self.page.locator("#projectHelp")).to_be_hidden()
        self.page.locator("#saveGroup").click()
        self.expect(self.page.locator("#groupDialog")).to_be_hidden()
        self.page.wait_for_function("conversationGroups.some(g => g.name === 'Timestamp help project')")
        self.page.evaluate("openGroupDialog(conversationGroups.find(g => g.name === 'Timestamp help project').id)")
        self.expect(self.page.locator("#groupDialogTitle")).to_have_text("Project settings")
        self.assertEqual(self.page.evaluate(
            "conversationGroups.find(g => g.name === 'Timestamp help project').kind"), "group")
        self.page.locator("#groupName").fill("Timestamp help renamed")
        self.page.locator("#saveGroup").click()
        self.expect(self.page.locator("#groupDialog")).to_be_hidden()

    def test_bedrock_gpt_settings_presets_and_switching_preserve_claude_controls(self):
        self.page.evaluate("activeSettings='ai';openSettings()")
        provider = self.page.locator('select[name="ai.provider"]')
        provider.select_option("bedrock-openai")
        self.expect(self.page.locator("#bedrockGPTModel")).to_have_value("us.openai.gpt-6.2-sol")
        self.expect(self.page.locator("#bedrockSettings")).to_be_hidden()
        self.expect(self.page.locator("#chatgptConnection")).to_be_hidden()
        self.page.locator("#bedrockGPTModel").select_option("us.openai.gpt-6.1-sol")
        self.expect(self.page.locator('input[name="ai.model"]')).to_have_value("us.openai.gpt-6.1-sol")
        self.page.locator('select[name="ai.bedrock_mode"]').select_option("advanced")
        self.expect(self.page.locator('input[name="ai.region"]')).to_be_visible()
        self.expect(self.page.locator("#bedrockAuthLabel")).to_be_hidden()
        self.expect(self.page.locator("#bedrockEndpointLabel")).to_be_hidden()
        self.page.locator(".model-selection summary").click()
        self.expect(self.page.locator('input[name="ai.analysis_model"]')).to_be_visible()
        provider.select_option("bedrock")
        self.expect(self.page.locator("#bedrockGPTModels")).to_be_hidden()
        self.expect(self.page.locator("#bedrockAuthLabel")).to_be_visible()
        self.expect(self.page.locator("#bedrockEndpointLabel")).to_be_visible()
        self.expect(self.page.locator('input[name="ai.model"]')).not_to_have_value("us.openai.gpt-6.1-sol")

    def test_opencode_presets_download_and_provider_switching(self):
        self.page.evaluate("activeSettings='ai';openSettings()")
        provider=self.page.locator('select[name="ai.provider"]')
        provider.select_option("opencode")
        self.expect(self.page.locator("#opencodeModel")).to_have_value("bedrock-runtime-openai/us.openai.gpt-6.2-sol")
        self.expect(self.page.locator("#opencodeAnalysis")).to_have_value("")
        self.expect(self.page.locator("#bedrockSettings")).to_be_hidden()
        self.expect(self.page.locator("#apiModelLabel")).to_be_hidden()
        choices=self.page.locator("#opencodeModel option").all_text_contents()
        self.assertTrue(any("Kimi" in item for item in choices))
        self.assertTrue(any("GLM" in item and "text only" in item for item in choices))
        self.assertTrue(any("premium" in item for item in choices))
        self.page.locator("#opencodeAnalysis").select_option("bedrock-runtime-anthropic/us.anthropic.claude-sonnet-5-5")
        self.expect(self.page.locator('input[name="ai.analysis_model"]')).to_have_value(
            "bedrock-runtime-anthropic/us.anthropic.claude-sonnet-5-5")
        with self.page.expect_download() as download:
            self.page.locator("#downloadOpenCode").click()
        self.assertEqual(download.value.suggested_filename,"opencode.json")
        data=json.loads(Path(download.value.path()).read_text())
        for connection in data["provider"].values():
            self.assertEqual(connection["options"]["apiKey"],"{env:AWS_BEARER_TOKEN_BEDROCK}")
        provider.select_option("bedrock-openai")
        self.expect(self.page.locator("#opencodeModels")).to_be_hidden()
        self.expect(self.page.locator("#bedrockGPTModels")).to_be_visible()
        provider.select_option("bedrock")
        self.expect(self.page.locator("#opencodeModels")).to_be_hidden()

    def test_tools_toggle_keeps_chat_and_composer_fixed_with_long_sidebar(self):
        self.page.locator("#conversations").get_by_role("button",name="Old continuity reference",exact=True).click()
        self.expect(self.page.locator("#chatTitle")).to_have_text("Old continuity reference")
        self.page.evaluate("""() => {
            const nav=document.querySelector('#conversations');
            for(let i=0;i<35;i++) nav.append(nav.firstElementChild.cloneNode(true));
            addMessage('assistant','Saved conversation line.\\n\\n'.repeat(120));
        }""")
        for width,height in [(1280,800),(1280,480),(2560,720),(700,500)]:
            self.page.set_viewport_size({"width":width,"height":height})
            self.page.locator("#sidebarTools").evaluate("(el) => { el.open = false; }")
            self.page.locator("#messages").evaluate("(el) => { el.style.scrollBehavior='auto'; el.scrollTop = 125; }")
            measure="""() => {
                const rect = selector => {
                    const r=document.querySelector(selector).getBoundingClientRect();
                    return [r.x,r.y,r.width,r.height];
                };
                return {main:rect('main'),composer:rect('.composer-wrap'),
                    scroll:document.querySelector('#messages').scrollTop,
                    pageHeight:document.documentElement.scrollHeight,viewport:innerHeight};
            }"""
            before=self.page.evaluate(measure)
            self.page.locator("#sidebarTools summary").click()
            self.expect(self.page.locator("#openKnowledge")).to_be_visible()
            after=self.page.evaluate(measure)
            self.assertEqual(before["main"],after["main"],(width,height))
            self.assertEqual(before["composer"],after["composer"],(width,height))
            self.assertEqual(before["scroll"],after["scroll"],(width,height))
            self.assertLessEqual(after["pageHeight"],height,(width,height,after))
            self.page.locator("#sidebarTools summary").click()
            self.assertEqual(self.page.evaluate(measure)["composer"],before["composer"])

    def test_scrollbars_are_thin_transparent_and_scrolling_still_works(self):
        self.page.locator("#conversations").get_by_role("button",name="Old continuity reference",exact=True).click()
        self.expect(self.page.locator("#chatTitle")).to_have_text("Old continuity reference")
        for theme in ("navy","beige","black-blue"):
            self.page.evaluate("theme=>document.documentElement.dataset.theme=theme",theme)
            self.expect(self.page.locator("#messages")).to_have_css("scrollbar-width","thin")
            self.assertNotEqual(self.page.locator("#messages").evaluate(
                "(el)=>getComputedStyle(el).scrollbarColor"),"auto")
            self.assertEqual(self.page.locator("#messages").evaluate(
                "(el)=>getComputedStyle(el,'::-webkit-scrollbar-track').backgroundColor"),"rgba(0, 0, 0, 0)")
        self.page.locator("#messages").evaluate("(el)=>el.scrollTop=el.scrollHeight")
        self.assertGreater(self.page.locator("#messages").evaluate("(el)=>el.scrollTop"),0)

    def test_sidebar_has_no_horizontal_scroll_and_nested_controls_remain_inside(self):
        self.page.evaluate("""() => {
            let parent=document.querySelector("#conversations");
            for(let i=0;i<8;i++) {
                const group=document.createElement("details");group.className="conversation-group";group.open=true;
                group.innerHTML='<summary><span class="group-name">A very long nested project name '+i+
                    '</span><button class="group-action">+</button><button class="group-action">⋯</button></summary>';
                const children=document.createElement("div");children.className="group-children";
                group.append(children);parent.append(group);parent=children;
            }
        }""")
        for width in (224,320):
            self.page.locator("#workspace").evaluate("(el,width)=>el.style.setProperty('--sidebar-width',width+'px')",width)
            self.page.locator("#sidebarTools").evaluate("(el)=>el.open=true")
            sizes=self.page.evaluate("""() => ['.sidebar','.sidebar nav','.sidebar-tools'].map(selector=>{
                const el=document.querySelector(selector);
                return {scroll:el.scrollWidth,client:el.clientWidth,x:getComputedStyle(el).overflowX};
            })""")
            self.assertTrue(all(item["scroll"]<=item["client"]+1 and item["x"]=="hidden" for item in sizes),sizes)
            right=self.page.locator(".sidebar").bounding_box()["width"]
            for control in self.page.locator(".conversation-group .group-action").all():
                rect=control.bounding_box()
                self.assertLessEqual(rect["x"]+rect["width"],right)

    def test_message_rail_preview_jump_bookmark_and_navigation_isolation(self):
        self.page.locator("#conversations").get_by_role("button",name="Old continuity reference",exact=True).click()
        self.expect(self.page.locator("#chatTitle")).to_have_text("Old continuity reference")
        rail=self.page.locator(".message-rail")
        self.expect(rail).to_be_visible()
        markers=rail.locator("button")
        self.assertEqual(markers.count(),self.page.locator("#messages article.message").count())
        target=self.page.evaluate("""() => [...document.querySelectorAll("#messages article.message")]
            .findIndex(node=>node.querySelector(".body")?.textContent==="Follow-up detail 17")""")
        self.assertGreaterEqual(target,0)
        marker=markers.nth(target)
        marker.hover()
        preview=self.page.locator(".message-rail-preview")
        self.expect(preview).to_be_visible()
        self.expect(preview).to_contain_text("Follow-up detail 17")
        preview.get_by_role("button",name="Pin message",exact=True).click()
        self.expect(preview.get_by_role("button",name="Unpin message",exact=True)).to_have_attribute("aria-pressed","true")
        favorites=self.context.request.get(self.url+"/api/favorites").json()["entries"]
        self.assertTrue(any("Follow-up detail 17" in row["text"] for row in favorites))
        marker.click()
        self.expect(preview).to_be_hidden()
        self.page.wait_for_function("document.querySelector('#messages').scrollTop>0")
        markers.first.focus()
        markers.first.press("ArrowDown")
        self.expect(markers.nth(1)).to_be_focused()
        self.expect(preview).to_be_visible()
        markers.nth(1).press("Escape")
        self.expect(preview).to_be_hidden()
        marker.hover()
        self.page.locator("#question").click()
        self.expect(preview).to_be_hidden()
        # A new chat clears the old marker targets and hover text.
        self.page.locator("#newChat").click()
        self.expect(rail).to_be_hidden()
        self.expect(preview).to_be_hidden()

    def test_message_rail_disable_and_plain_text_preview_are_safe(self):
        self.page.evaluate("""() => {
            addMessage("user",'<img src=x onerror="window.railUnsafe=true">');
            addMessage("assistant","Safe reply");
        }""")
        self.page.locator(".message-rail button").first.hover()
        preview=self.page.locator(".message-rail-preview")
        self.expect(preview).to_be_visible()
        self.assertEqual(preview.locator("img").count(),0)
        self.assertFalse(self.page.evaluate("Boolean(window.railUnsafe)"))
        self.page.add_init_script("window.AiMateFeatures={messageNavigation:false}")
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        self.assertEqual(self.page.locator(".message-rail").count(),0)
        self.expect(self.page.locator("#question")).to_be_visible()

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

    def test_shift_enter_turns_three_dashes_into_an_inline_horizontal_rule(self):
        field=self.page.locator("#question")
        field.fill("First paragraph\n---")
        field.press("Shift+Enter")
        self.expect(field).to_have_js_property("value","First paragraph\n***\n")
        rule=field.get_by_role("separator",name="Horizontal rule")
        self.expect(rule).to_be_visible()
        self.assertEqual(rule.evaluate("e=>getComputedStyle(e).borderBottomStyle"),"solid")
        self.expect(self.page.locator("#questionSource")).to_have_value("First paragraph\n***\n")
        self.assertEqual(rule.evaluate("e=>getComputedStyle(e).marginTop"),"0px")
        self.assertEqual(rule.evaluate("e=>getComputedStyle(e).marginBottom"),"0px")
        field.press("Control+z")
        self.expect(field).to_have_js_property("value","First paragraph\n---")
        self.expect(rule).to_have_count(0)
        field.press("Shift+Enter")
        field.press_sequentially("Next paragraph")
        self.expect(field).to_have_js_property("value","First paragraph\n***\nNext paragraph")
        self.expect(rule).to_have_count(1)
        self.expect(self.page.locator("#welcome")).to_be_visible() # No request was submitted.
        field.fill("```text\n---")
        field.press("Shift+Enter")
        self.expect(rule).to_have_count(0)
        self.assertTrue(field.evaluate("e=>e.value").startswith("```text\n---\n"))
        self.page.evaluate("window.AiMateFeatures={...window.AiMateFeatures,horizontalRule:false}")
        field.fill("---")
        field.press("Shift+Enter")
        self.expect(field).to_have_js_property("value","---\n")
        self.expect(rule).to_have_count(0)

    def test_askbar_caret_uses_readable_theme_colour_even_in_coloured_text(self):
        field=self.page.locator("#question")
        field.fill("[colour:#eb0f46]Hello[/colour]")
        for theme in ("navy","beige","black-blue","life","brown-gold"):
            self.page.evaluate("theme=>window.AiMateAppearance.apply(theme)",theme)
            styles=field.evaluate("""e=>({
                caret:getComputedStyle(e).caretColor,text:getComputedStyle(e).color,
                colouredCaret:getComputedStyle(e.querySelector('[data-rich-colour]')).caretColor,
                colouredText:getComputedStyle(e.querySelector('[data-rich-colour]')).color})""")
            self.assertEqual(styles["caret"],styles["text"],theme)
            self.assertEqual(styles["colouredCaret"],styles["text"],theme)
            self.assertNotEqual(styles["colouredCaret"],styles["colouredText"],theme)

    def test_foreground_replaces_or_resets_colour_and_repairs_existing_nested_tags(self):
        field=self.page.locator("#question")
        button=self.page.get_by_role("button",name="Foreground",exact=True)
        field.fill("Hello")
        field.evaluate("e=>{e.setSelectionRange(0,5);e.dispatchEvent(new Event('select'))}")
        button.click()
        self.expect(field).to_have_js_property("value","[colour:#79baff]Hello[/colour]")
        button.click()
        self.expect(field).to_have_js_property("value","Hello")
        self.expect(button).to_have_attribute("aria-pressed","false")
        button.click()
        self.page.get_by_label("Foreground colour",exact=True).evaluate(
            "e=>{e.value='#eb0f46';e.dispatchEvent(new Event('input',{bubbles:true}))}")
        button.click()
        self.expect(field).to_have_js_property("value","[colour:#eb0f46]Hello[/colour]")
        self.expect(field.locator("[data-rich-colour]")).to_have_css("color","rgb(235, 15, 70)")
        button.click()
        self.expect(field).to_have_js_property("value","Hello")
        nested="[colour:#79baff][colour:#eb0f46][colour:#eb0f46][colour:#eb0f46]text[/colour][/colour][/colour][/colour]"
        field.fill(nested)
        field.evaluate("e=>{const p=e.value.indexOf('text');e.setSelectionRange(p,p+4);e.dispatchEvent(new Event('select'))}")
        button.click()
        self.expect(field).to_have_js_property("value","text")
        self.expect(field.locator("[data-rich-colour]")).to_have_count(0)

    def test_inline_editor_formats_without_preview_and_keeps_strict_csp(self):
        self.page.add_init_script("""window.richPolicyViolations=[];
            document.addEventListener('securitypolicyviolation',e=>richPolicyViolations.push(e.violatedDirective));""")
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        field=self.page.locator("#question")
        self.assertEqual(field.evaluate("(el)=>el.tagName"),"DIV")
        field.fill("Bold Test")
        field.press("Control+a")
        field.press("Control+b")
        self.expect(field).to_have_js_property("value","**Bold Test**")
        self.expect(field.locator("strong")).to_have_text("Bold Test")
        self.expect(field.locator("strong")).to_have_css("font-weight","700")
        self.expect(self.page.locator("#composerPreview")).to_be_hidden()
        field.fill("*Italic* ++Underline++ [colour:#ff7aaf]Colour[/colour]")
        self.expect(field.locator("em")).to_have_text("Italic")
        self.expect(field.locator("u")).to_have_text("Underline")
        self.expect(field.locator("[data-rich-colour]")).to_have_css("color","rgb(255, 122, 175)")
        self.expect(self.page.locator("#questionSource")).to_be_hidden()
        self.assertEqual(self.page.evaluate("richPolicyViolations"),[])
        field.fill("```text\n**literal** ++literal++ [colour:#ff7aaf]literal[/colour]\n```")
        self.assertEqual(field.locator("strong,u,[data-rich-colour]").count(),0)

    def test_space_after_bold_keeps_word_formatted_and_exits_to_plain_text(self):
        field = self.page.locator("#question")
        field.fill("Bold word")
        field.press("Control+a")
        field.press("Control+b")
        field.press("ArrowRight")
        field.press("Space")
        field.type("normal")
        self.expect(field).to_have_js_property("value", "**Bold word** normal")
        self.expect(field.locator("strong")).to_have_text("Bold word")
        self.assertNotIn("**", field.inner_text())
        self.expect(self.page.get_by_role("button", name="Bold", exact=True)).to_have_attribute("aria-pressed", "false")
        field.press("Control+z")
        self.expect(field.locator("strong")).to_have_text("Bold word")

    def test_inline_space_boundary_preserves_nested_formats_internal_spaces_and_code(self):
        field = self.page.locator("#question")
        for source in ("*word*", "++word++", "***word***",
                       "[colour:#ff7aaf]word[/colour]",
                       "***++[colour:#ff7aaf]word[/colour]++***"):
            with self.subTest(source=source):
                field.fill(source)
                position = source.index("word") + 4
                field.evaluate("(e,pos)=>e.setSelectionRange(pos,pos)", position)
                field.press("Space")
                field.type("plain")
                self.expect(field).to_have_js_property("value", source + " plain")
                self.assertNotIn("[/colour]", field.inner_text())
        field.fill("**word**")
        field.evaluate("e=>e.setSelectionRange(4,4)")
        field.press("Space")
        self.expect(field).to_have_js_property("value", "**wo rd**")
        source = "```text\n**word**\n```"
        field.fill(source)
        position = source.index("word") + 4
        field.evaluate("(e,pos)=>e.setSelectionRange(pos,pos)", position)
        field.press("Space")
        self.expect(field).to_have_js_property("value", source[:position] + " " + source[position:])
        self.assertEqual(field.locator("strong").count(), 0)
        self.page.evaluate("window.AiMateFeatures={inlineFormatBoundary:false}")
        field.fill("**word**")
        field.evaluate("e=>e.setSelectionRange(6,6)")
        field.press("Space")
        self.expect(field).to_have_js_property("value", "**word **")

    def test_inline_editor_enter_sends_portable_markdown_and_clears_draft(self):
        field=self.page.locator("#question")
        field.fill("**Inline saved bold**")
        field.press("Enter")
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        self.expect(field).to_have_js_property("value","")
        self.expect(self.page.locator("#messages .message.user strong").last).to_have_text("Inline saved bold")
        ident=self.page.evaluate("cid")
        saved=self.context.request.get(self.url+"/api/conversations/"+ident).json()
        self.assertEqual(saved["turns"][-1]["messages"][0]["content"],"**Inline saved bold**")
        self.page.reload()
        self.page.evaluate("id=>openConversation(id)",ident)
        self.expect(self.page.locator("#messages .message.user strong").last).to_have_text("Inline saved bold")

    def test_inline_editor_undo_and_plain_paste_exclude_html(self):
        field=self.page.locator("#question")
        field.fill("Undo me")
        field.press("Control+a");field.press("Control+b")
        self.expect(field).to_have_js_property("value","**Undo me**")
        field.press("Control+z")
        self.expect(field).to_have_js_property("value","Undo me")
        field.fill("")
        self.page.evaluate("""() => {
            const data=new DataTransfer();
            data.setData('text/plain','Safe plain text');
            data.setData('text/html','<img src=x onerror="window.richUnsafe=true">');
            document.querySelector('#question').dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(field).to_have_js_property("value","Safe plain text")
        self.assertEqual(field.locator("img").count(),0)
        self.assertFalse(self.page.evaluate("Boolean(window.richUnsafe)"))

    def test_inline_editor_large_paste_and_long_panels_keep_composer_visible(self):
        field=self.page.locator("#question")
        self.page.evaluate("""() => {
            const data=new DataTransfer();data.setData('text/plain','Large pasted record.\\n'.repeat(300));
            document.querySelector('#question').dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("Pasted text.txt")
        self.expect(field).to_have_js_property("value","")
        self.page.locator("#attachmentCards .attachment-remove").click()
        field.fill("Earlier source line\n"*60+"Selected warning")
        field.evaluate("""el=>{el.setSelectionRange(el.value.indexOf('Selected warning'),el.value.length);
            el.dispatchEvent(new Event('select'));}""")
        self.page.get_by_role("button",name="More formatting",exact=True).click()
        self.page.get_by_role("button",name="Warning panel",exact=True).click()
        self.assertIn("> [!WARNING]\n> Selected warning",field.evaluate("(el)=>el.value"))
        self.expect(self.page.locator("#composerPreview")).to_be_hidden()
        self.assertGreater(field.evaluate("(el)=>el.scrollTop"),0)
        for width,height in ((1280,800),(390,720)):
            self.page.set_viewport_size({"width":width,"height":height})
            self.assertLessEqual(self.page.locator(".rich-composer .cm-scroller").bounding_box()["height"],240)
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),width)
            self.expect(self.page.locator("#send")).to_be_in_viewport()

    def test_large_paste_inside_rich_editor_line_preserves_every_character(self):
        text="# Synthetic package review\n\n"+"- Preserve this evidence exactly.\n"*180
        field=self.page.locator("#question")
        field.fill("Review this attachment")
        self.page.evaluate("""text=>{
            const data=new DataTransfer();data.setData('text/plain',text);
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:data,bubbles:true,cancelable:true}));
        }""",text)
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("Pasted text.txt")
        self.expect(field).to_have_js_property("value","Review this attachment")
        self.assertEqual(self.page.evaluate("pendingAttachments[0].text"),text)
        self.assertEqual(self.page.locator("#attachmentCards .attachment-card").count(),1)
        # A short paste in the same inner line is inserted once, never converted
        # or reinserted by the document-level handler.
        field.fill("")
        self.page.evaluate("""()=>{
            const data=new DataTransfer();data.setData('text/plain','Short safe paste');
            data.setData('text/html','<img src=x onerror="window.pasteUnsafe=true">');
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(field).to_have_js_property("value","Short safe paste")
        self.assertEqual(self.page.locator("#attachmentCards .attachment-card").count(),1)
        self.assertFalse(self.page.evaluate("Boolean(window.pasteUnsafe)"))

    def test_nested_rich_editor_paste_shows_limit_without_losing_existing_draft(self):
        field=self.page.locator("#question");field.fill("Keep my draft")
        self.page.evaluate("""()=>{
            document.querySelector('#attachText').dataset.documentBytes='5000';
            const data=new DataTransfer();data.setData('text/plain','Over limit evidence.\\n'.repeat(300));
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(self.page.locator("#activity")).to_contain_text("Use a document up to")
        self.expect(self.page.locator("#attachmentCards")).to_be_hidden()
        self.expect(field).to_have_js_property("value","Keep my draft")

    def test_file_paste_inside_rich_editor_line_creates_one_attachment(self):
        field=self.page.locator("#question");field.fill("Keep this question")
        self.page.evaluate("""()=>{
            const data=new DataTransfer();
            data.items.add(new File(['Nested clipboard file\\nKeep every line.'],'clipboard.txt',{type:'text/plain'}));
            document.querySelector('#question .cm-line').dispatchEvent(new ClipboardEvent('paste',
                {clipboardData:data,bubbles:true,cancelable:true}));
        }""")
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("clipboard.txt")
        self.assertEqual(self.page.locator("#attachmentCards .attachment-card").count(),1)
        self.assertEqual(self.page.evaluate("pendingAttachments[0].text"),"Nested clipboard file\nKeep every line.")
        self.expect(field).to_have_js_property("value","Keep this question")

    def test_disabling_inline_editor_retains_plain_formatting_and_core_chat(self):
        self.page.add_init_script("window.AiMateFeatures={richComposer:false}")
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        field=self.page.locator("#question")
        self.assertEqual(field.evaluate("(el)=>el.tagName"),"TEXTAREA")
        field.fill("Plain fallback");field.press("Control+a");field.press("Control+b")
        self.expect(field).to_have_js_property("value","**Plain fallback**")
        self.expect(self.page.locator("#composerPreview strong")).to_have_text("Plain fallback")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")

    def test_composer_format_preview_send_and_history_reload(self):
        self.page.get_by_role("button",name="Preview formatted message",exact=True).click()
        self.page.evaluate("async () => {await refreshState();document.dispatchEvent(new Event('aimate:state'));}")
        self.expect(self.page.get_by_role("button",name="Preview formatted message",exact=True)).to_have_attribute("aria-pressed","true")
        self.page.locator("#newChat").click()
        self.expect(self.page.get_by_role("button",name="Bold",exact=True)).to_be_visible()
        field = self.page.locator("#question")
        field.fill("Formatted")
        field.evaluate("(el) => { el.setSelectionRange(0,el.value.length); el.dispatchEvent(new Event('select')); }")
        self.page.get_by_role("button",name="Bold",exact=True).click()
        self.expect(field).to_have_js_property("value","**Formatted**")
        self.expect(self.page.locator("#composerPreview strong")).to_have_text("Formatted")
        self.page.get_by_role("button",name="More formatting",exact=True).click()
        self.page.get_by_role("button",name="Toggle line wrapping",exact=True).click()
        self.expect(field).to_have_js_property("wrap","off")
        field.fill("one\ntwo")
        field.evaluate("(el) => { el.setSelectionRange(0,el.value.length); el.dispatchEvent(new Event('select')); }")
        self.page.get_by_role("button",name="Bullet list",exact=True).click()
        self.expect(field).to_have_js_property("value","- one\n- two")
        self.page.get_by_role("button",name="Indent",exact=True).click()
        self.expect(field).to_have_js_property("value","    - one\n    - two")
        self.page.get_by_role("button",name="Outdent",exact=True).click()
        self.expect(field).to_have_js_property("value","- one\n- two")
        field.fill("**Formatted**\n\n++Underline++\n\n[colour:#ff7850]Colour[/colour]\n\n| Item | Value |\n| --- | --- |\n| Test | 1 |\n\n> [!WARNING]\n> Check this")
        self.expect(self.page.locator("#composerPreview .prompt-underline")).to_have_text("Underline")
        self.expect(self.page.locator("#composerPreview [data-prompt-colour]")).to_have_css("color","rgb(255, 120, 80)")
        self.expect(self.page.locator("#composerPreview .answer-callout.warning")).to_contain_text("Check this")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        existing=self.page.evaluate("cid")
        self.page.reload()
        self.page.evaluate("id => openConversation(id)",existing)
        self.expect(self.page.locator("#messages .message.user strong")).to_have_text("Formatted")
        self.expect(self.page.locator("#messages .message.user table")).to_contain_text("Test")

    def test_every_composer_format_control_and_shortcuts_without_sending(self):
        self.page.get_by_role("button",name="Preview formatted message",exact=True).click()
        submitted=[]
        self.page.on("request",lambda request: submitted.append(request.url) if request.method=="POST" and request.url.endswith("/api/chat") else None)
        field=self.page.locator("#question")
        self.expect(self.page.locator("#composerAdvanced")).not_to_be_visible()
        for title in ("Bold","Italic","Underline","Foreground","Bullet list","Numbered list","Code block"):
            self.expect(self.page.get_by_role("button",name=title,exact=True)).to_be_visible()
        self.page.get_by_role("button",name="More formatting",exact=True).click()
        cases=[
            ("Bold","**Example**","strong"),
            ("Italic","*Example*","em"),
            ("Underline","++Example++",".prompt-underline"),
            ("Foreground","[colour:#79baff]Example[/colour]","[data-prompt-colour]"),
            ("Heading","## Example","h2"),
            ("Paragraph","\n\nExample\n\n",None),
            ("Bullet list","- Example","ul"),
            ("Numbered list","1. Example","ol"),
            ("Indent","    Example","pre"),
            ("Code block","```text\nExample\n```","pre"),
            ("Quote","> Example","blockquote"),
            ("Information panel","\n\n> [!NOTE]\n> Example\n\n",".answer-callout.note"),
            ("Warning panel","\n\n> [!WARNING]\n> Example\n\n",".answer-callout.warning"),
        ]
        for title,expected,selector in cases:
            field.fill("Example")
            field.evaluate("(el) => {el.setSelectionRange(0,el.value.length);el.dispatchEvent(new Event('select'));}")
            self.page.get_by_role("button",name=title,exact=True).click()
            self.expect(field).to_have_js_property("value",expected)
            if selector:
                self.expect(self.page.locator("#composerPreview "+selector)).to_be_visible()
            else:
                self.expect(self.page.locator("#composerPreview")).to_contain_text("Example")
        field.fill("    Example")
        field.evaluate("(el) => {el.setSelectionRange(0,el.value.length);el.dispatchEvent(new Event('select'));}")
        self.page.get_by_role("button",name="Outdent",exact=True).click()
        self.expect(field).to_have_js_property("value","Example")
        field.fill("")
        field.evaluate("(el) => el.dispatchEvent(new Event('select'))")
        self.page.get_by_role("button",name="Horizontal rule",exact=True).click()
        self.expect(self.page.locator("#composerPreview hr")).to_be_visible()
        field.fill("Example")
        field.evaluate("(el) => {el.setSelectionRange(0,el.value.length);el.dispatchEvent(new Event('select'));}")
        self.page.get_by_role("button",name="Insert table",exact=True).click()
        self.expect(self.page.locator("#composerPreview table")).to_contain_text("Example")
        for key,expected in (("b","**Example**"),("i","*Example*"),("u","++Example++")):
            field.fill("Example")
            field.press("Control+a")
            field.press("Control+"+key)
            self.expect(field).to_have_js_property("value",expected)
        self.page.get_by_role("button",name="Preview formatted message",exact=True).click()
        self.expect(self.page.locator("#composerPreview")).not_to_be_visible()
        self.page.get_by_role("button",name="More formatting",exact=True).click()
        self.expect(self.page.locator("#composerAdvanced")).not_to_be_visible()
        self.expect(self.page.get_by_role("button",name="Bold",exact=True)).to_be_visible()
        self.page.set_viewport_size({"width":390,"height":720})
        self.assertLessEqual(self.page.locator("#composerToolbar").bounding_box()["width"],390)
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),390)
        self.assertEqual(submitted,[])

    def test_combined_inline_formats_render_colour_and_persist_after_send(self):
        self.page.get_by_role("button",name="Preview formatted message",exact=True).click()
        field=self.page.locator("#question")
        field.fill("Hello")
        field.evaluate("(el) => {el.setSelectionRange(0,el.value.length);el.dispatchEvent(new Event('select'));}")
        for name in ("Bold","Italic","Underline"):
            self.page.get_by_role("button",name=name,exact=True).click()
        self.page.locator('#composerToolbar input[type="color"]').evaluate(
            "(el) => {el.value='#ff7aaf';el.dispatchEvent(new Event('input'));}")
        self.page.get_by_role("button",name="Foreground",exact=True).click()
        self.expect(field).to_have_js_property("value","***++[colour:#ff7aaf]Hello[/colour]++***")
        preview=self.page.locator("#composerPreview")
        self.expect(preview).to_have_text("Hello")
        self.expect(preview.locator("strong")).to_have_text("Hello")
        self.expect(preview.locator("em")).to_have_text("Hello")
        formatted=preview.locator(".prompt-underline [data-prompt-colour]")
        self.expect(formatted).to_have_css("color","rgb(255, 122, 175)")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        existing=self.page.evaluate("cid")
        self.page.reload()
        self.page.evaluate("id => openConversation(id)",existing)
        saved=self.page.locator("#messages .message.user .prompt-underline [data-prompt-colour]")
        self.expect(saved).to_have_text("Hello")
        self.expect(saved).to_have_css("color","rgb(255, 122, 175)")

    def test_format_indicators_follow_selection_toggle_and_actual_view_state(self):
        self.page.get_by_role("button",name="Preview formatted message",exact=True).click()
        field=self.page.locator("#question")
        bold=self.page.get_by_role("button",name="Bold",exact=True)
        field.fill("Hello")
        field.evaluate("(el) => {el.setSelectionRange(0,el.value.length);el.dispatchEvent(new Event('select'));}")
        neutral=bold.evaluate("(el) => getComputedStyle(el).backgroundColor")
        for name in ("Bold","Italic","Underline","Foreground"):
            button=self.page.get_by_role("button",name=name,exact=True)
            button.click()
            self.expect(button).to_have_attribute("aria-pressed","true")
            self.assertNotEqual(button.evaluate("(el) => getComputedStyle(el).backgroundColor"),neutral)
        bold.click()
        self.expect(bold).to_have_attribute("aria-pressed","false")
        self.expect(self.page.get_by_role("button",name="Italic",exact=True)).to_have_attribute("aria-pressed","true")
        self.expect(self.page.get_by_role("button",name="Underline",exact=True)).to_have_attribute("aria-pressed","true")
        self.expect(self.page.locator("#composerPreview strong")).to_have_count(0)
        self.expect(self.page.locator("#composerPreview em .prompt-underline [data-prompt-colour]")).to_have_text("Hello")
        self.page.get_by_role("button",name="Underline",exact=True).click()
        self.expect(self.page.locator("#composerPreview .prompt-underline")).to_have_count(0)
        self.expect(self.page.locator("#composerPreview em [data-prompt-colour]")).to_have_text("Hello")
        field.fill("**Bold** plain")
        field.evaluate("(el) => {el.setSelectionRange(2,6);el.dispatchEvent(new Event('select'));}")
        self.expect(bold).to_have_attribute("aria-pressed","true")
        field.evaluate("(el) => {el.setSelectionRange(el.value.length,el.value.length);el.dispatchEvent(new Event('select'));}")
        self.expect(bold).to_have_attribute("aria-pressed","false")
        more=self.page.get_by_role("button",name="More formatting",exact=True)
        more.click()
        self.expect(more).to_have_attribute("aria-expanded","true")
        wrap=self.page.get_by_role("button",name="Toggle line wrapping",exact=True)
        self.expect(wrap).to_have_attribute("aria-pressed","true")
        wrap.click()
        self.expect(wrap).to_have_attribute("aria-pressed","false")
        preview=self.page.get_by_role("button",name="Preview formatted message",exact=True)
        self.expect(preview).to_have_attribute("aria-pressed","true")
        preview.click()
        self.expect(preview).to_have_attribute("aria-pressed","false")
        field.fill("```text\n**Literal**\n```")
        field.evaluate("(el) => {const at=el.value.indexOf('Literal');el.setSelectionRange(at,at+7);el.dispatchEvent(new Event('select'));}")
        self.expect(bold).to_have_attribute("aria-pressed","false")
        self.expect(self.page.get_by_role("button",name="Code block",exact=True)).to_have_attribute("aria-pressed","true")
        field.fill("")
        self.expect(self.page.get_by_role("button",name="Code block",exact=True)).to_have_attribute("aria-pressed","false")

    def test_generated_panels_expand_editor_and_reveal_insertions(self):
        self.page.get_by_role("button",name="Preview formatted message",exact=True).click()
        field=self.page.locator("#question")
        field.fill("")
        compact=field.bounding_box()["height"]
        self.page.get_by_role("button",name="More formatting",exact=True).click()
        self.page.get_by_role("button",name="Warning panel",exact=True).click()
        self.expect(field).to_have_js_property("value","\n\n> [!WARNING]\n> text\n\n")
        self.expect(self.page.locator("#composerPreview .answer-callout.warning")).to_contain_text("text")
        self.assertGreater(field.bounding_box()["height"],compact)
        self.assertTrue(field.evaluate("(el) => el.scrollHeight <= el.clientHeight + 1"))
        field.fill("Earlier source line\n"*60+"Selected warning")
        field.evaluate("""(el) => {
            el.setSelectionRange(el.value.indexOf('Selected warning'),el.value.length);
            el.scrollTop=0;el.dispatchEvent(new Event('select'));
        }""")
        self.page.get_by_role("button",name="Warning panel",exact=True).click()
        self.assertGreater(field.evaluate("(el) => el.scrollTop"),0)
        self.assertLessEqual(field.bounding_box()["height"],240)
        self.expect(self.page.locator("#send")).to_be_in_viewport()
        self.page.set_viewport_size({"width":390,"height":720})
        self.expect(field).to_have_css("height",re.compile(r"172\.\d+px"))
        self.assertLessEqual(field.bounding_box()["height"],173)
        self.expect(self.page.locator("#send")).to_be_in_viewport()
        field.fill("")
        self.assertLessEqual(field.bounding_box()["height"],compact+1)

    def test_disabling_formatter_module_keeps_the_core_askbar_working(self):
        self.page.add_init_script("window.AiMateFeatures={composerFormatting:false};")
        self.page.reload()
        self.expect(self.page.locator("#composerFormatting")).not_to_be_visible()
        self.page.locator("#newChat").click()
        self.page.locator("#question").fill("Explain my project")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        self.expect(self.page.locator("#messages .message.user")).to_contain_text("Explain my project")

    def test_investigation_checkpoint_reopens_and_continue_does_not_submit(self):
        self.page.locator("#conversations").get_by_role("button", name="Old continuity reference", exact=True).click()
        self.page.locator("#chatMenu summary").click()
        self.page.locator("#openInvestigation").click()
        self.page.locator("#investigationPreset").select_option("debug")
        self.page.locator("#investigationTarget").fill("Synthetic build #11")
        self.page.locator("#investigationNotes").fill("Read first page.\nNext: remaining log pages.")
        self.page.locator("#investigationSteps input").first.check()
        self.page.get_by_role("button",name="Save checkpoint",exact=True).click()
        self.expect(self.page.locator("#investigationStatus")).to_contain_text("Checkpoint saved")
        existing=self.page.evaluate("cid")
        self.page.reload()
        self.page.evaluate("id => openConversation(id)",existing)
        self.expect(self.page.locator("#chatTitle")).to_have_text("Old continuity reference")
        self.page.locator("#chatMenu summary").click()
        self.page.locator("#openInvestigation").click()
        self.expect(self.page.locator("#investigationNotes")).to_have_value("Read first page.\nNext: remaining log pages.")
        self.expect(self.page.locator("#investigationSteps input").first).to_be_checked()
        before=len(self.context.request.get(self.url+f"/api/conversations/{existing}").json()["turns"])
        self.page.get_by_role("button",name="Continue in askbar",exact=True).click()
        self.page.wait_for_function("() => document.querySelector('#question').value.includes('Synthetic build #11')")
        self.assertEqual(len(self.context.request.get(self.url+f"/api/conversations/{existing}").json()["turns"]),before)

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
        self.page.locator("#messages .evidence summary").last.click()
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
        self.expect(self.page.locator("#question")).to_have_js_property("value",text)
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
        self.page.locator("#todosEditLock").click()
        row=self.page.locator(".todo-row").filter(has_text="Typed task")
        row.get_by_role("button",name="Edit",exact=True).click()
        self.expect(self.page.locator("#todoType")).to_have_value("bug")
        self.expect(self.page.locator("#todoTitle")).to_have_value("Typed task\n- Keep details")
        self.page.locator("#todoType").select_option("triage")
        self.page.locator("#saveTodo").click()
        self.page.locator("#todoTypeFilter").select_option("triage")
        self.expect(self.page.locator(".todo-row").filter(has_text="Typed task").locator(".todo-kind")).to_have_text("Triage")

    def test_personal_record_locks_guard_updates_and_delete_and_reset_on_reopen(self):
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openTodos").click()
        self.page.locator("#todoTitle").fill("Protected task")
        self.page.locator("#saveTodo").click()
        row=self.page.locator(".todo-row").filter(has_text="Protected task")
        for action in ("Edit","Delete"):
            self.expect(row.get_by_role("button",name=action,exact=True)).to_be_disabled()
        self.expect(row.locator("input[type=checkbox]")).to_be_disabled()
        self.expect(row.get_by_role("button",name="Copy",exact=True)).to_be_enabled()
        self.page.locator("#todosEditLock").click()
        row.get_by_role("button",name="Edit",exact=True).click()
        self.page.locator("#todoTitle").fill("Updated protected task")
        self.page.locator("#todosEditLock").click()
        self.expect(self.page.locator("#saveTodo")).to_be_disabled()
        self.expect(self.page.locator("#todoTitle")).not_to_be_editable()
        self.page.locator("#todoForm").evaluate("(el) => el.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))")
        self.expect(self.page.locator("#todoError")).to_contain_text("Unlock")
        saved=self.context.request.get(self.url+"/api/todos").json()["tasks"]
        self.assertTrue(any(t["title"]=="Protected task" for t in saved))
        self.assertFalse(any(t["title"]=="Updated protected task" for t in saved))
        self.page.locator("#todosEditLock").click()
        self.page.locator("#saveTodo").click()
        self.expect(self.page.locator(".todo-row").filter(has_text="Updated protected task")).to_be_visible()
        self.page.locator('[data-close="todoDialog"]').click()
        self.page.locator("#openTodos").click()
        row=self.page.locator(".todo-row").filter(has_text="Updated protected task")
        self.expect(row.get_by_role("button",name="Delete",exact=True)).to_be_disabled()
        self.page.locator("#todosEditLock").click()
        row.get_by_role("button",name="Delete",exact=True).click()
        self.expect(row).to_have_count(0)
        self.page.locator('[data-close="todoDialog"]').click()
        self.page.locator("#openKnowledge").click()
        self.page.locator("#manageKnowledge").click()
        self.page.locator("#recordKey").fill("Protected diary")
        self.page.locator("#recordValue").fill("Keep this value")
        self.page.locator("#knowledgeForm [type=submit]").click()
        card=self.page.locator("#knowledgeCards .knowledge-card").filter(has_text="Protected diary")
        self.expect(card.get_by_role("button",name="Edit Protected diary",exact=True)).to_be_disabled()
        self.page.locator("#diaryEditLock").click()
        card.get_by_role("button",name="Edit Protected diary",exact=True).click()
        self.page.locator("#recordValue").fill("Updated value\nKeep formatting")
        self.page.locator("#diaryEditLock").click()
        self.expect(self.page.locator("#knowledgeForm [type=submit]")).to_be_disabled()
        self.expect(self.page.locator("#deleteRecord")).to_be_disabled()
        self.expect(self.page.locator("#recordValue")).not_to_be_editable()
        self.page.locator("#knowledgeForm").evaluate("(el) => el.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true}))")
        self.expect(self.page.locator("#knowledgeError")).to_contain_text("Unlock")
        saved=self.context.request.get(self.url+"/api/knowledge").json()["records"]
        self.assertEqual(next(t["value"] for t in saved if t["key"]=="Protected diary"),"Keep this value")
        self.page.locator("#diaryEditLock").click()
        self.page.locator("#knowledgeForm [type=submit]").click()
        self.expect(card).to_contain_text("Updated value")
        self.page.locator('[data-close="knowledgeDialog"]').click()
        self.page.locator("#openKnowledge").click()
        self.expect(card.get_by_role("button",name="Edit Protected diary",exact=True)).to_be_disabled()
        self.page.locator("#diaryEditLock").click()
        card.get_by_role("button",name="Edit Protected diary",exact=True).click()
        self.page.locator("#deleteRecord").click()
        self.expect(card).to_have_count(0)
        self.page.reload()
        self.page.locator("#sidebarTools").evaluate("(el) => { el.open = true; }")
        self.page.locator("#openTodos").click()
        self.expect(self.page.locator("#todosEditLock")).to_have_attribute("data-locked","true")

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
        saved=self.context.request.get(self.url+"/api/conversations/"+self.page.evaluate("cid")).json()
        exported=self.page.evaluate("chat => conversationMarkdown(chat)",saved)
        self.assertIn("Explain the screenshot",exported)
        self.assertIn("Attachment: Screenshot\\.png",exported)
        self.expect(self.page.locator("#messages .attachment-card")).to_contain_text("Screenshot.png")

    def test_document_upload_over_four_mb_uses_server_limit_and_card(self):
        self.expect(self.page.locator("#attachText")).to_have_attribute("title","Attach a file · documents up to 20 MB")
        self.page.locator("#textAttachment").set_input_files({
            "name":"large.dat","mimeType":"application/octet-stream","buffer":b"\xff"*(5*1024*1024)})
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("large.dat")
        self.expect(self.page.locator("#activity")).to_contain_text("Metadata only")
        self.page.locator("#question").fill("Describe this file's metadata")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#messages .attachment-card")).to_contain_text("large.dat")
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")

    def test_attachment_progress_cancellation_errors_and_disabled_module(self):
        self.page.route("**/api/attachments/document",lambda route:None)
        self.page.locator("#textAttachment").set_input_files({
            "name":"wait.txt","mimeType":"text/plain","buffer":b"Evidence"})
        self.expect(self.page.locator(".import-progress")).to_be_visible()
        self.expect(self.page.locator(".import-progress-caption")).to_contain_text("Validating wait.txt")
        self.expect(self.page.locator(".import-progress-track")).not_to_have_attribute("aria-valuenow",re.compile(".+"))
        self.expect(self.page.locator("#send")).to_be_disabled()
        self.page.locator(".import-progress button").click()
        self.expect(self.page.locator("#activity")).to_have_text("Attachment import cancelled.")
        self.expect(self.page.locator(".import-progress")).to_be_hidden()
        self.expect(self.page.locator("#attachmentCards")).to_be_hidden()
        self.page.unroute("**/api/attachments/document")
        self.page.route("**/api/attachments/document",lambda route:route.fulfill(status=413,content_type="application/json",body='{"detail":"Document upload exceeds the 20 MB file limit."}'))
        self.page.locator("#textAttachment").set_input_files({
            "name":"rejected.txt","mimeType":"text/plain","buffer":b"Evidence"})
        self.expect(self.page.locator("#activity")).to_contain_text("20 MB file limit")
        self.expect(self.page.locator(".import-progress")).to_be_hidden()
        self.page.unroute("**/api/attachments/document")
        self.page.evaluate("window.AiMateFeatures={importProgress:false}")
        self.page.locator("#textAttachment").set_input_files({
            "name":"optional.txt","mimeType":"text/plain","buffer":b"Evidence"})
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("optional.txt")
        self.expect(self.page.locator(".import-progress")).to_be_hidden()

    def test_keyboard_format_shortcuts_apply_to_selected_text(self):
        field=self.page.locator("#question")
        field.fill("Selected text")
        field.select_text()
        field.press("Control+b")
        self.expect(field).to_have_js_property("value","**Selected text**")
        self.expect(self.page.get_by_role("button",name="Bold",exact=True)).to_have_attribute("aria-pressed","true")

    def test_message_favorite_restores_and_opens_original_chat_and_unpins(self):
        self.page.locator("#newChat").click()
        self.page.locator("#modelMode").select_option("standard")
        self.page.locator("#question").fill("Favorite reply fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#send")).to_be_enabled(timeout=15000)
        pin=self.page.get_by_role("button",name="Pin AiMate reply",exact=True)
        inactive=pin.evaluate("(el)=>getComputedStyle(el).backgroundColor")
        self.page.get_by_role("button",name="Pin AiMate reply",exact=True).click()
        self.expect(self.page.get_by_role("button",name="Unpin AiMate reply",exact=True)).to_have_attribute("aria-pressed","true")
        self.assertNotEqual(inactive,self.page.get_by_role("button",name="Unpin AiMate reply",exact=True).evaluate("(el)=>getComputedStyle(el).backgroundColor"))
        self.page.reload()
        self.expect(self.page.get_by_role("button",name="Unpin AiMate reply",exact=True)).to_have_attribute("aria-pressed","true")
        self.page.locator("#sidebarTools > summary").click()
        self.page.locator("#openFavorites").click()
        self.expect(self.page.locator("#favoriteMessages")).to_contain_text("Favorite reply fixture")
        self.page.locator("#favoriteMessages").get_by_role("button",name="Open chat",exact=True).click()
        self.expect(self.page.locator("#favoritesDialog")).to_be_hidden()
        self.page.locator("#openFavorites").click()
        self.expect(self.page.locator("#favoriteMessages").get_by_role("button",name="Unpin",exact=True)).to_be_disabled()
        self.page.locator("#favoritesEditLock").click()
        self.page.locator("#favoriteMessages").get_by_role("button",name="Unpin",exact=True).click()
        self.expect(self.page.locator("#favoriteMessages .knowledge-card")).to_have_count(0)
        self.page.locator('[data-close="favoritesDialog"]').click()
        self.expect(self.page.get_by_role("button",name="Pin AiMate reply",exact=True)).to_be_visible()
        self.page.mouse.move(0,0)
        self.page.wait_for_function("""colour=>getComputedStyle(document.querySelector(
            '[data-message-favorite="assistant"]')).backgroundColor===colour""",arg=inactive)
        self.page.add_init_script("window.AiMateFeatures={messageFavorites:false}")
        self.page.reload()
        self.expect(self.page.locator("[data-message-favorite]")).to_have_count(0)
        self.expect(self.page.locator("#openFavorites")).to_be_hidden()

    def test_ai_connection_layout_separates_personal_intel_and_keeps_controls_visible(self):
        self.page.locator("#headerSettings").click()
        provider=self.page.locator('[name="ai.provider"]')
        self.expect(provider.locator('optgroup:not([label="This laptop"])')).to_have_count(3)
        self.expect(provider.locator('optgroup[label="This laptop"] option')).to_have_text("Local LLM · offline")
        self.expect(provider.locator('option[value="chatgpt"]')).to_have_text("Personal ChatGPT")
        provider.select_option("chatgpt")
        self.expect(self.page.locator(".ai-connection-context")).to_have_text("Personal · your ChatGPT account and plan.")
        self.expect(self.page.locator("#connectChatGPT")).to_be_visible()
        self.expect(self.page.locator("#chatgptAccount")).to_be_visible()
        self.expect(self.page.locator(".ai-plan-details")).not_to_have_attribute("open","")
        self.page.set_viewport_size({"width":390,"height":844})
        self.expect(self.page.locator("#connectChatGPT")).to_be_visible()
        for selector in ("#chatgptAccount","#connectChatGPT"):
            bounds=self.page.locator(selector).bounding_box()
            self.assertGreaterEqual(bounds["x"],0)
            self.assertLessEqual(bounds["x"]+bounds["width"],390)
        provider.select_option("bedrock-openai")
        self.expect(self.page.locator(".ai-connection-context")).to_contain_text("Intel / Bedrock")
        self.expect(self.page.locator("#chatgptConnection")).to_be_hidden()
        self.expect(self.page.locator('#apiCredentials input[name="ai.api_key"]')).to_be_visible()

    def test_ai_connection_layout_can_be_disabled_without_removing_provider_controls(self):
        self.page.add_init_script("window.AiMateFeatures={aiConnectionLayout:false}")
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        self.page.locator("#headerSettings").click()
        provider=self.page.locator('[name="ai.provider"]')
        self.expect(provider.locator('optgroup:not([label="This laptop"])')).to_have_count(0)
        self.expect(self.page.locator(".ai-connection-context")).to_have_count(0)
        provider.select_option("chatgpt")
        self.expect(self.page.locator("#connectChatGPT")).to_be_visible()
        provider.select_option("bedrock-openai")
        self.expect(self.page.locator('#apiCredentials input[name="ai.api_key"]')).to_be_visible()

    def test_gemini_secure_json_import_preserves_models_and_masks_saved_credentials(self):
        from test_gemini_vertex import GeminiTests
        GeminiTests.setUpClass()
        self.page.locator("#headerSettings").click()
        self.page.locator('[name="ai.provider"]').select_option("gemini")
        self.expect(self.page.locator("#geminiModel")).to_contain_text("Gemini 4 Hydrogen")
        secret=self.page.locator('[name="ai.gcp_credentials"]')
        self.expect(secret).to_have_attribute("type","password")
        self.expect(self.page.locator("#apiCredentials")).to_be_hidden()
        self.expect(self.page.locator("#settings-ai .model-selection")).to_be_hidden()
        self.page.locator("#geminiCredentialFile").set_input_files({
            "name":"synthetic-service-account.json","mimeType":"application/json",
            "buffer":json.dumps(GeminiTests.info).encode()})
        self.expect(self.page.locator("#geminiHint")).to_contain_text("JSON loaded")
        self.page.locator("#geminiModel").select_option("gemini-4-carbon")
        self.page.locator("#geminiAnalysisModel").select_option("gemini-4-neon")
        self.page.locator("#saveConnection").click()
        self.expect(secret).to_have_value("")
        response=self.context.request.get(self.url+"/api/state")
        state=response.json()["config"]["ai"]
        self.assertTrue(state["gcp_credentials_configured"])
        self.assertNotIn("gcp_credentials",state)
        self.assertNotIn("PRIVATE KEY",response.text())
        self.assertEqual(state["model"],"gemini-4-carbon")
        self.assertEqual(state["analysis_model"],"gemini-4-neon")
        self.assertEqual(state["gcp_location"],"global")
        self.page.locator('[data-close="settingsDialog"]').click()
        self.page.locator("#headerSettings").click()
        self.expect(secret).to_have_attribute("placeholder","Saved · leave blank to keep")
        self.expect(self.page.locator("#geminiModel")).to_have_value("gemini-4-carbon")
        self.page.locator("#geminiCredentialFile").set_input_files({
            "name":"too-large.json","mimeType":"application/json","buffer":b" " * 20001})
        self.expect(self.page.locator("#geminiHint")).to_contain_text("20 KB")
        self.page.locator("#geminiCredentialFile").set_input_files({
            "name":"invalid.json","mimeType":"application/json","buffer":b'{"type":"other"}'})
        self.expect(self.page.locator("#geminiHint")).to_contain_text("complete Google")
        self.page.locator('[name="ai.provider"]').select_option("bedrock-openai")
        self.expect(self.page.locator("#settings-ai .model-selection")).to_be_visible()

    def test_gemini_ui_can_be_disabled_while_other_connections_remain_usable(self):
        self.page.add_init_script("window.AiMateFeatures={geminiVertex:false}")
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        self.page.locator("#headerSettings").click()
        self.expect(self.page.locator('option[value="gemini"]')).to_be_disabled()
        self.page.locator('[name="ai.provider"]').select_option("bedrock-openai")
        self.expect(self.page.locator("#geminiSettings")).to_be_hidden()
        self.expect(self.page.locator('#apiCredentials input[name="ai.api_key"]')).to_be_visible()

    def test_temporary_day_chat_survives_reload_and_session_close_is_page_scoped(self):
        self.page.locator("#privateToggle").click()
        self.expect(self.page.locator("#temporaryLifetime")).to_be_visible()
        self.page.locator("#temporaryLifetime").select_option("day")
        self.page.locator("#question").fill("Temporary day browser fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        chat=self.page.evaluate("cid")
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        state=self.context.request.get(self.url+"/api/state").json()
        self.assertTrue(any(c["id"]==chat and c["temporary"]=="day" for c in state["conversations"]))
        self.page.evaluate("""async () => {
            const settings=AiMateTemporaryChats.options();
            window.syntheticTemporary=await api('/api/conversations',{method:'POST',body:JSON.stringify({
                private:true,temporary:{...settings,lifetime:'session'}})});
            await api('/api/conversations/temporary-close',{method:'POST',body:JSON.stringify({page:settings.page})});
        }""")
        closed=self.page.evaluate("syntheticTemporary.id")
        self.assertEqual(self.context.request.get(self.url+"/api/conversations/"+closed).status,400)
        self.assertEqual(self.context.request.get(self.url+"/api/conversations/"+chat).status,200)

    def test_temporary_session_pagehide_cleanup_and_disabled_lifetime_control(self):
        self.page.locator("#privateToggle").click()
        self.page.locator("#question").fill("Temporary session browser fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")
        chat=self.page.evaluate("cid")
        with self.page.expect_response(lambda response: response.url.endswith("/api/conversations/temporary-close")):
            self.page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false}))")
        self.assertEqual(self.context.request.get(self.url+"/api/conversations/"+chat).status,400)
        self.page.add_init_script("window.AiMateFeatures={temporaryChats:false}")
        self.page.reload()
        self.expect(self.page.locator("#workspace")).to_be_visible()
        self.page.locator("#privateToggle").click()
        self.expect(self.page.locator("#temporaryLifetime")).to_have_count(0)
        self.page.locator("#question").fill("Legacy private browser fixture")
        self.page.locator("#send").click()
        self.expect(self.page.locator("#activity")).to_have_text("Answer complete")

    def test_feedback_review_reply_confirmed_task_and_disabled_ui(self):
        self.page.locator("#conversations").get_by_role("button",name="Old continuity reference",exact=True).click()
        self.page.locator("#messages").get_by_role("button",name="Feedback",exact=True).click()
        self.page.locator("#feedbackNegative").click()
        self.page.locator("#feedbackComment").fill("Feedback review browser fixture")
        self.page.locator("#feedbackForm").get_by_role("button",name="Save feedback",exact=True).click()
        self.expect(self.page.locator("#activity")).to_have_text("Feedback saved. Thank you.")
        self.page.locator("#headerSettings").click()
        self.page.locator("#tab-changes").click()
        self.page.locator("#openFeedbackLog").click()
        self.expect(self.page.locator("#feedbackReviewsDialog")).to_be_visible()
        entries=self.context.request.get(self.url+"/api/feedback/reviews").json()["entries"]
        ident=next(row["id"] for row in entries if row["comment"]=="Feedback review browser fixture")
        card=self.page.locator(f'[data-feedback-id="{ident}"]')
        card.locator("summary").click()
        card.get_by_label("Feedback state",exact=True).select_option("investigating")
        card.get_by_label("Reviewer assessment",exact=True).select_option("confirmed_issue")
        card.get_by_label("Reviewer reply",exact=True).fill("Reproduced. A fix is planned.")
        card.get_by_role("button",name="Save review",exact=True).click()
        self.expect(card.locator('[role="alert"]')).to_contain_text("Add evidence")
        card.get_by_label("Review evidence",exact=True).fill("Browser regression fixture")
        card.get_by_role("button",name="Save review",exact=True).click()
        self.expect(card.get_by_role("button",name="Add to To-do",exact=True)).to_be_enabled()
        card.get_by_role("button",name="Add to To-do",exact=True).click()
        self.expect(card.get_by_role("button",name="Open To-do",exact=True)).to_be_visible()
        task=self.context.request.get(self.url+"/api/todos").json()["tasks"]
        self.assertTrue(any("Feedback review browser fixture" in row["title"] for row in task))
        self.page.add_init_script("window.AiMateFeatures={feedbackReview:false}")
        self.page.reload()
        self.expect(self.page.locator("#openMyFeedback")).to_be_hidden()
        self.expect(self.page.locator("#question")).to_be_visible()

    def test_extra_themes_import_validation_persistence_and_disabled_feature(self):
        self.page.locator("#openAppearance").click()
        self.page.locator('[data-theme-choice="life"]').click()
        self.expect(self.page.locator("html")).to_have_attribute("data-theme","life")
        self.page.locator('[data-theme-choice="brown-gold"]').click()
        self.assertEqual(self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"),"#241a14")
        self.expect(self.page.locator("#send")).to_have_css("background-color","rgb(242, 199, 110)")
        theme=self.page.evaluate("({version:1,name:'My gold',colors:AiMateThemes.palettes['brown-gold']})")
        upload=self.page.locator(".theme-import-row input")
        upload.set_input_files({"name":"my-theme.json","mimeType":"application/json","buffer":json.dumps(theme).encode()})
        self.expect(self.page.locator("html")).to_have_attribute("data-theme","custom")
        self.expect(self.page.locator("#appearanceDialog")).to_contain_text("Theme imported: My gold")
        self.page.reload()
        self.expect(self.page.locator("html")).to_have_attribute("data-theme","custom")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"),"#241a14")
        self.page.locator("#openAppearance").click()
        self.page.locator(".theme-import-row input").set_input_files({
            "name":"unsafe.json","mimeType":"application/json","buffer":json.dumps({**theme,"css":"url(https://outside)"}).encode()})
        self.expect(self.page.locator("#appearanceDialog .error")).to_contain_text("nine required colour tokens")
        self.expect(self.page.locator("html")).to_have_attribute("data-theme","custom")
        self.page.add_init_script("window.AiMateFeatures={extraThemes:false}")
        self.page.reload()
        self.expect(self.page.locator("html")).to_have_attribute("data-theme","navy")
        self.expect(self.page.locator(".theme-import-row")).to_have_count(0)
        self.expect(self.page.locator("#question")).to_be_visible()

    def test_large_paste_is_a_document_card_and_saved_message_keeps_card(self):
        self.page.evaluate("""() => {
            const transfer = new DataTransfer();
            transfer.setData("text/plain", "Large pasted evidence\\n".repeat(400));
            document.querySelector("#question").dispatchEvent(new ClipboardEvent("paste", {clipboardData:transfer,bubbles:true,cancelable:true}));
        }""")
        self.expect(self.page.locator("#attachmentCards")).to_contain_text("Pasted text.txt")
        self.expect(self.page.locator("#question")).to_have_js_property("value","")
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
        self.expect(card).to_be_hidden()
        self.assertEqual(card.locator("pre").count(), 0)
        self.expect(self.page.locator("#activity")).to_contain_text("Change completed")
        self.assertEqual(card.get_by_role("button", name="Confirm change", exact=True).count(), 0)
        self.page.evaluate("action => drawAction(action, document.querySelector('#messages'))", action)
        self.assertEqual(card.count(), 1)
        self.assertEqual(card.locator("pre").count(), 0)
        # refreshState replaces the reports; supply the saved verification for navigation.
        self.page.evaluate("""() => { connectionReports.github = {status: "passed",
            message: "Read access verified.", targets: [{target: "demo/project", ok: true,
            message: "Accessible", details: ["Default branch: main"]}]}; }""")
        self.page.evaluate("activeSettings='github';openSettings()")
        self.expect(self.page.locator("#settingsDialog")).to_be_visible()
        self.expect(self.page.locator('[data-settings-tab="github"]')).to_have_attribute("aria-selected", "true")
        self.page.locator("#test-github .connection-details > summary").click()
        self.page.locator("#test-github .connection-target > summary").first.click()
        self.expect(self.page.locator("#test-github .connection-target p").first).to_be_visible()
        self.expect(self.page.locator("#test-github")).to_contain_text("demo/project")
        # History reconstruction uses the same compact completed view.
        self.page.evaluate("""action => {
            document.querySelector("#settingsDialog").close();
            document.querySelector("#messages").replaceChildren();
            drawAction(action, document.querySelector("#messages"));
        }""", completed)
        self.expect(self.page.locator(".action-completed")).to_be_hidden()
        self.assertEqual(self.page.locator(".action-completed pre").count(), 0)
        # Failed confirmations still retain their diagnostic preview.
        self.page.evaluate("action => drawAction({...action, id: 'failed-change', status: 'failed'}, document.querySelector('#messages'))", action)
        self.expect(self.page.locator('[data-action="failed-change"] pre')).to_be_visible()

    def test_repository_recovery_dismisses_after_confirm_and_diagnostics_stay_collapsed(self):
        action={"id":"recovery-test","service":"settings","operation":"update_github_repositories",
                "status":"pending","preview":{"repository":"demo/recovery"}}
        self.page.route("**/repository-proposal",lambda route:route.fulfill(json=action))
        self.page.route("**/api/actions/recovery-test/confirm",
                        lambda route:route.fulfill(json={**action,"status":"completed"}))
        self.page.evaluate("""() => {
            addMessage("user","Add demo/recovery");
            const bot=addMessage("assistant","Repository access can be reviewed.");
            bot.conversationId=cid || "synthetic-chat";
            const guidance={repo:"demo/recovery",action:"validate_repository",message:"Outside saved repository scope."};
            addToolFailure(bot,"Repository is outside your configured scope",guidance);
            addToolFailure(bot,"Repository is outside your configured scope",guidance);
        }""")
        user=self.page.locator("#messages .message.user").last
        bot=self.page.locator("#messages .message.assistant").last
        self.expect(bot.locator(".evidence")).not_to_have_attribute("open","")
        self.assertEqual(bot.locator(".tool-error").count(),1)
        self.assertEqual(bot.locator(".source-recovery").count(),1)
        self.expect(bot.locator(".source-recovery")).to_be_hidden()
        self.assertLess(user.bounding_box()["y"],bot.bounding_box()["y"])
        bot.locator(".evidence summary").click()
        bot.get_by_role("button",name="Validate & review repository",exact=True).click()
        self.expect(bot.locator(".source-recovery")).to_contain_text("Access verified")
        bot.get_by_role("button",name="Confirm change",exact=True).click()
        self.expect(bot.locator('[data-action="recovery-test"]')).to_have_class("action-card action-completed")
        self.expect(bot.locator(".action-completed")).to_be_hidden()
        self.assertEqual(bot.locator(".source-recovery").count(),0)
        self.assertEqual(bot.get_by_role("button",name="Confirm change",exact=True).count(),0)
        bot.locator(".evidence summary").click()
        self.expect(bot.locator(".tool-error")).to_be_hidden()
        self.page.evaluate("""action => {
            const root=document.querySelector("#messages .assistant:last-child");
            const bot={root,body:root.querySelector(".body"),conversationId:cid};
            renderGitHubGuidance(bot,{repo:"demo/recovery",action:"validate_repository",message:"Check access"});
            drawAction(action,root);
        }""",action)
        self.assertEqual(bot.locator(".source-recovery").count(),0)

    def test_saved_proposal_keeps_its_original_turn_and_answer_order(self):
        action={"id":"history-repo","service":"settings","operation":"update_github_repositories",
                "status":"completed","preview":{"repository":"demo/history"}}
        saved={"id":"history-order","title":"History order","private":False,"actions":[action],"turns":[
            {"id":301,"created":1700000000,"messages":[
                {"role":"user","content":"First question"},
                {"role":"assistant","content":[{"type":"text","text":"First reply"},
                 {"type":"tool_use","id":"configure1","name":"configure_repository","input":{"repo":"demo/history"}}]},
                {"role":"user","content":[{"type":"tool_result","tool_use_id":"configure1",
                 "content":json.dumps({"proposal":"history-repo","status":"pending"})}]}]},
            {"id":302,"created":1700000001,"messages":[
                {"role":"user","content":"Second question"},
                {"role":"assistant","content":[{"type":"text","text":"Second reply"}]}]}]}
        self.page.route("**/api/conversations/history-order",lambda route:route.fulfill(json=saved))
        self.page.route("**/api/conversations/history-order/actions",lambda route:route.fulfill(json={"actions":[action]}))
        self.page.evaluate("openConversation('history-order','History order')")
        self.expect(self.page.locator("#chatTitle")).to_have_text("History order")
        messages=self.page.locator("#messages > .message")
        self.assertEqual(messages.count(),4)
        self.assertEqual(messages.locator(".who").all_text_contents(),["YOU","AiMate","YOU","AiMate"])
        self.expect(messages.nth(1).locator(".action-completed")).to_be_hidden()
        self.assertEqual(messages.nth(3).locator("[data-action]").count(),0)
        self.assertLess(messages.nth(0).bounding_box()["y"],messages.nth(1).bounding_box()["y"])
        self.assertLess(messages.nth(1).bounding_box()["y"],messages.nth(2).bounding_box()["y"])

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
