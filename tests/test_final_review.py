"""Pinned evidence, workspace preferences, metering and concurrent cancellation."""
import asyncio
import base64
import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.connectors import Services
from app.final_review import run
from app.final_review_calls import call
from app.final_review_evidence import collect, target, validate_report
from app.final_review_panel import capture, fingerprint, identity, preference, profiles, put_profile, save_preference, selected_panel
from app.store import Store
from test_app import create_app, fixture_config

HEAD, BASE = "a" * 40, "b" * 40
SOURCE = "def calculate(value):\n    return 10 / value\n"


def report():
    return {"summary": "A zero divisor needs handling.", "findings": [{
        "severity": "P2", "path": "code.py", "commit": HEAD, "line": 2,
        "quote": "return 10 / value", "claim": "Zero can raise ZeroDivisionError",
        "scenario": "A caller passes zero.", "suggestion": "Validate the denominator."}],
        "gaps": ["Runtime and unchanged call sites were not checked."]}


class Model:
    def __init__(self, config, calls, gate=None, invalid=False):
        self.config, self.calls, self.gate, self.invalid = config, calls, gate, invalid
        self.messages = self
        self.closed = False

    async def create(self, **args):
        self.calls.append((self, args))
        if self.gate:
            await self.gate.wait()
        value = report()
        if self.invalid:
            value["findings"][0]["line"] = 999
        text = "OK" if args["max_tokens"] == 256 else json.dumps(value)
        return SimpleNamespace(model=args["model"], stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)], usage={"input_tokens": 40, "output_tokens": 20})

    async def close(self):
        self.closed = True


def services(config, requests, state):
    def remote(request):
        requests.append(request)
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json=[{"filename": "code.py", "status": "modified"}])
        if "/pulls/" in request.url.path:
            return httpx.Response(200, json={"head": {"sha": state.get("head", HEAD)},
                                           "base": {"sha": BASE}, "changed_files": 1})
        if "/compare/" in request.url.path:
            return httpx.Response(200, json={"merge_base_commit": {"sha": BASE}})
        return httpx.Response(200, json={"type": "file", "encoding": "base64", "sha": "c" * 40,
                                        "content": base64.b64encode(SOURCE.encode()).decode()})
    return Services(config, httpx.MockTransport(remote))


def panel(store):
    values = []
    for name, model in (("First", "model-one"), ("Lead", "model-two")):
        profile = capture(store, {"name": name, "scope": "non-intel", "model": model})
        value = profiles(store)[profile["id"]]
        value["verified"] = fingerprint(value["ai"])
        put_profile(store, profile["id"], value)
        values.append(profile["id"])
    save_preference(store, {"reviewers": values, "lead": values[1]})
    return values


class PanelTests(unittest.TestCase):
    def test_real_user_workspaces_do_not_share_panel_or_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory); store.save_config(fixture_config())
            app = create_app(store)
            clients = []
            try:
                owner = TestClient(app); clients.append(owner)
                headers = {"X-CSRF-Token": owner.post("/api/login", json={"password": store.password}).json()["csrf"]}
                panel(store)
                for name in ("Alice", "Bob"):
                    grant = owner.post("/api/access/grants", headers=headers,
                        json={"name": name, "role": "viewer"}).json()
                    user = TestClient(app); clients.append(user)
                    login = user.post("/api/access/login", json={"role": "viewer", "code": grant["code"]}).json()
                    personal_headers = {"X-CSRF-Token": login["csrf"]}
                    state = user.get("/api/settings/final-review").json()
                    self.assertEqual(state["profiles"], []); self.assertIsNone(state["selection"])
                    config = fixture_config(); config["allow_writes"] = False
                    config["ai"]["api_key"] = name + "-own-secret"
                    self.assertEqual(user.put("/api/settings", headers=personal_headers, json=config).status_code, 200)
                    saved = user.post("/api/settings/final-review/profiles", headers=personal_headers,
                        json={"name": name, "scope": "non-intel"})
                    self.assertEqual(saved.status_code, 200, saved.text)
                    own = user.get("/api/settings/final-review")
                    self.assertNotIn("own-secret", own.text)
                    self.assertEqual([row["name"] for row in own.json()["profiles"]], [name])
                self.assertEqual(len(owner.get("/api/settings/final-review").json()["profiles"]), 2)
            finally:
                for client in clients: client.close()
                app.state.workspaces.close(); store.db.close()

    def test_selection_survives_restart_is_encrypted_and_isolated(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            store = Store(directory); store.save_config(fixture_config())
            selected = panel(store)
            ciphertext = store.rows("SELECT encrypted FROM final_review_profiles")[0]["encrypted"]
            self.assertNotIn("ai-private-token", ciphertext)
            self.assertNotIn("model-one", ciphertext)
            store.db.close()
            restored = Store(directory)
            self.assertEqual(preference(restored)["reviewers"], selected)
            self.assertEqual(len(selected_panel(restored, False)[0]), 2)
            isolated = Store(other)
            self.assertIsNone(preference(isolated))
            self.assertEqual(profiles(isolated), {})
            isolated.db.close(); restored.db.close()

    def test_scope_duplicate_routes_missing_access_and_rotated_credentials(self):
        self.assertEqual(identity("bedrock-runtime-anthropic/us.anthropic.claude-opus-5-5"),
                         identity("claude-opus-5-5"))
        self.assertEqual(identity("bedrock-runtime-openai/global.openai.gpt-6.2-sol"),
                         identity("gpt-6.2-sol"))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory); store.save_config(fixture_config())
            selected = panel(store)
            with self.assertRaisesRegex(ValueError, "Intel"):
                selected_panel(store, True)
            value = profiles(store)[selected[1]]
            value["ai"]["model"] = "global.model-one"
            value["verified"] = fingerprint(value["ai"])
            put_profile(store, selected[1], value)
            with self.assertRaisesRegex(ValueError, "same underlying"):
                save_preference(store, {"reviewers": selected, "lead": selected[1]})
            config = store.config(); config["ai"]["api_key"] = "changed-secret"; store.save_config(config)
            with self.assertRaisesRegex(ValueError, "older credential"):
                selected_panel(store, False)
            with self.assertRaisesRegex(ValueError, "Personal"):
                capture(store, {"name": "Not approved", "scope": "organization"})
            with self.assertRaisesRegex(ValueError, "credential"):
                capture(store, {"name": "Mistyped secret", "scope": "non-intel", "model": "changed-secret"})
            store.db.close()

    def test_routes_check_access_save_and_disabled_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory); store.save_config(fixture_config()); calls = []
            requests = []
            app = create_app(store, client_factory=lambda config: Model(config, calls),
                             services_factory=lambda config: services(config, requests, {}))
            with TestClient(app) as client:
                login = client.post("/api/login", json={"password": store.password}).json()
                headers = {"X-CSRF-Token": login["csrf"]}; ids = []
                for model in ("model-one", "model-two"):
                    item = client.post("/api/settings/final-review/profiles", headers=headers,
                                       json={"name": model, "model": model, "scope": "non-intel"}).json()
                    ids.append(item["id"])
                self.assertEqual(client.put("/api/settings/final-review", headers=headers,
                    json={"reviewers": ids, "lead": ids[1]}).status_code, 400)
                for ident in ids:
                    checked = client.post(f"/api/settings/final-review/profiles/{ident}/test", headers=headers)
                    self.assertEqual(checked.status_code, 200, checked.text)
                    self.assertTrue(checked.json()["ready"])
                saved = client.put("/api/settings/final-review", headers=headers,
                                  json={"reviewers": ids, "lead": ids[1]})
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertNotIn("ai-private-token", client.get("/api/settings/final-review").text)
                self.assertEqual(len(calls), 2)
                cid = client.post("/api/conversations", headers=headers, json={}).json()["id"]
                response = client.post("/api/chat", headers=headers, json={"conversation": cid,
                    "question": "Review https://github.example/team/repo/pull/7", "template_mode": "final-review"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('"event": "done"', response.text)
                self.assertIn("ZeroDivisionError", response.text)
                self.assertEqual(len(calls), 5)
                self.assertTrue(all(request.method == "GET" for request in requests))
            with patch.dict("os.environ", {"AIMATE_FINAL_REVIEW_ENABLED": "0"}):
                with TestClient(create_app(store)) as client:
                    client.post("/api/login", json={"password": store.password})
                    self.assertIn(client.get("/api/settings/final-review").status_code, {404, 405})
                    styles = client.get("/api/library/styles").json()["styles"]
                    self.assertNotIn("final-review", [row["id"] for row in styles])
            store.db.close()


class FinalReviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        config = fixture_config(); config["github"]["url"] = "https://api.github.com"
        self.store.save_config(config); self.cid = self.store.new_conversation()
        self.ids = panel(self.store); self.calls, self.requests, self.state = [], [], {}

    async def asyncTearDown(self):
        self.store.db.close(); self.directory.cleanup()

    def stream(self, question="Review https://github.com/team/repo/pull/7", **kwargs):
        return run(self.store, self.cid, question,
            client_factory=kwargs.get("factory", lambda config: Model(config, self.calls)),
            services_factory=lambda config: services(config, self.requests, self.state),
            chatgpt=None, access_check=kwargs.get("check", lambda: None))

    async def test_independent_same_packet_lead_usage_and_saved_report(self):
        events = [event async for event in self.stream()]
        self.assertEqual(events[-1]["event"], "done")
        self.assertTrue(events[-1]["completion"]["complete"])
        self.assertEqual(len(self.calls), 3)
        inputs = [json.loads(args["messages"][0]["content"]) for _, args in self.calls]
        self.assertEqual(inputs[0]["evidence"], inputs[1]["evidence"])
        self.assertEqual(inputs[1]["evidence"], inputs[2]["evidence"])
        self.assertEqual(len(inputs[2]["independent_reports"]), 2)
        self.assertTrue(all("tools" not in args for _, args in self.calls))
        self.assertTrue(all(request.method == "GET" for request in self.requests))
        self.assertEqual(sum("/contents/" in request.url.path for request in self.requests), 2)
        self.assertEqual(self.store.rows("SELECT COUNT(*) AS n FROM usage_events")[0]["n"], 3)
        self.assertEqual(self.store.rows("SELECT COUNT(*) AS n FROM actions")[0]["n"], 0)
        metadata = json.loads(self.store.rows("SELECT metadata FROM turn_usage")[0]["metadata"])
        self.assertEqual(metadata["final_review"]["snapshot"], inputs[0]["evidence"])
        self.assertEqual(metadata["usage"]["input_tokens"], 120)
        self.assertTrue(all(client.closed for client, _ in self.calls))

    async def test_empty_optional_keys_do_not_corrupt_source_metadata_or_redaction(self):
        for ident, value in profiles(self.store).items():
            value["ai"].update(aws_secret_key="", aws_session_token="")
            value["verified"] = fingerprint(value["ai"])
            put_profile(self.store, ident, value)
        events = [event async for event in self.stream()]
        self.assertTrue(events[-1]["completion"]["complete"])
        self.assertEqual(len(self.calls), 3)
        self.assertNotIn("ai-private-token", self.calls[0][1]["messages"][0]["content"])

    async def test_unclear_prompt_fetches_nothing_and_requests_input(self):
        events = [event async for event in self.stream("Review that PR")]
        self.assertIn("one full PR URL", events[0]["delta"])
        self.assertEqual(self.requests, []); self.assertEqual(self.calls, [])
        self.assertIsNone(target("https://evil.example/team/repo/pull/7", self.store.config()))

    async def test_invalid_line_report_never_reaches_lead_and_is_not_complete(self):
        events = [event async for event in self.stream(factory=lambda config: Model(config, self.calls, invalid=True))]
        self.assertFalse(events[-1]["completion"]["complete"])
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("ZeroDivisionError", next(event["delta"] for event in events if event["event"] == "text"))

    async def test_cancellation_closes_both_models_without_saving_completion(self):
        gate = asyncio.Event()
        iterator = self.stream(factory=lambda config: Model(config, self.calls, gate))
        async def drain():
            return [event async for event in iterator]
        task = asyncio.create_task(drain())
        for _ in range(200):
            if len(self.calls) == 2:
                break
            await asyncio.sleep(.01)
        self.assertEqual(len(self.calls), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(all(client.closed for client, _ in self.calls))
        self.assertEqual(self.store.rows("SELECT * FROM turns"), [])
        self.assertEqual(self.store.rows("SELECT COUNT(*) AS n FROM usage_calls")[0]["n"], 2)

    async def test_changed_head_and_revoked_profile_cannot_save_final_review(self):
        gate = asyncio.Event()
        async def drain():
            return [event async for event in self.stream(factory=lambda config: Model(config, self.calls, gate))]
        task = asyncio.create_task(drain())
        for _ in range(200):
            if len(self.calls) == 2: break
            await asyncio.sleep(.01)
        self.state["head"] = "d" * 40; gate.set()
        with self.assertRaisesRegex(ValueError, "PR changed"):
            await task
        self.assertEqual(self.store.rows("SELECT * FROM turns"), [])
        self.state.clear(); self.calls.clear(); gate.clear()
        task = asyncio.create_task(drain())
        for _ in range(200):
            if len(self.calls) == 2: break
            await asyncio.sleep(.01)
        self.store.execute("DELETE FROM final_review_profiles WHERE id=?", (self.ids[0],))
        gate.set()
        with self.assertRaisesRegex(ValueError, "revoked"):
            await task
        self.assertEqual(self.store.rows("SELECT * FROM turns"), [])

    async def test_packet_source_hash_bounds_and_wrong_citations(self):
        packet = await collect(services(self.store.config(), self.requests, self.state),
                               "team/repo", 7, self.store.config(), lambda: None)
        validate_report(json.dumps(report()), packet)
        wrong = copy.deepcopy(report()); wrong["findings"][0]["quote"] = "not in source"
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_report(json.dumps(wrong), packet)
        with patch("app.final_review_evidence.MAX_CHARACTERS", 20):
            with self.assertRaisesRegex(ValueError, "packet limit"):
                await collect(services(self.store.config(), [], self.state),
                              "team/repo", 7, self.store.config(), lambda: None)

    async def test_bedrock_responses_adapter_receives_system_and_accounts_usage(self):
        from app.bedrock_gpt import Connection
        requests = []
        def remote(request):
            requests.append(request)
            return httpx.Response(200, json={"status": "completed", "model": "us.openai.gpt-6.2-sol",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(report())}]}],
                "usage": {"input_tokens": 50, "output_tokens": 30}})
        ai = {"provider": "bedrock-openai", "model": "us.openai.gpt-6.2-sol", "api_key": "synthetic-bedrock",
              "region": "us-east-2"}
        text, usage = await call(self.store, {"ai": ai}, "Evidence packet", "Read-only review.",
            lambda config: Connection(config, transport=httpx.MockTransport(remote)), None, lambda: None)
        self.assertEqual(json.loads(text), report()); self.assertEqual(usage["input_tokens"], 50)
        payload = json.loads(requests[0].content)
        self.assertEqual(payload["input"][0]["role"], "system")
        self.assertEqual(payload["input"][0]["content"], "Read-only review.")
        self.assertNotIn("tools", payload)
        self.assertTrue(requests[0].url.path.endswith("/openai/v1/responses"))

    async def test_account_responses_adapter_never_falls_back_to_another_account(self):
        class Account:
            async def response_events(inner, payload, expected_account):
                self.assertEqual(expected_account, "chosen-account")
                self.assertNotIn("tools", payload)
                self.assertEqual(payload["instructions"], "Read-only")
                yield {"type": "response.completed", "response": {"status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
                    "usage": {"input_tokens": 5, "output_tokens": 1}}}
        text, _ = await call(self.store, {"ai": {"provider": "chatgpt", "model": "gpt-fixture",
            "account": "chosen-account"}}, "synthetic", "Read-only", None, Account(), lambda: None)
        self.assertEqual(text, "OK")

    async def test_truncated_native_report_is_metered_but_never_treated_as_completed(self):
        class Truncated(Model):
            async def create(inner, **args):
                response = await super().create(**args)
                response.stop_reason = "max_tokens"
                return response
        with self.assertRaisesRegex(ValueError, "did not finish"):
            await call(self.store, next(iter(profiles(self.store).values())), "fixture", "Read-only",
                lambda config: Truncated(config, self.calls), None, lambda: None)
        self.assertTrue(self.calls[0][0].closed)
        self.assertEqual(self.store.rows("SELECT status FROM usage_calls")[0]["status"], "reported")
