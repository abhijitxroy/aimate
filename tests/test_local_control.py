"""Cancellation ownership, cleanup and local-only memory release."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.local_control import Controls
from app.ollama_local import Client, DEFAULT_MODEL
import test_local_ai as fixtures
from test_app import create_app


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_closes_stream_and_is_scoped_to_session_and_exact_request(self):
        controls = Controls()
        ready = asyncio.Event()
        closed = asyncio.Event()
        handle = controls.reserve("owner", "chat", DEFAULT_MODEL, "request-1234567890")
        other = controls.reserve("other", "chat", DEFAULT_MODEL)

        async def generate():
            async with controls.running(handle):
                try:
                    ready.set()
                    await asyncio.Event().wait()
                finally:
                    closed.set()
        task = asyncio.create_task(generate())
        await ready.wait()
        await controls.stop("other", "chat", handle[0][2])
        await controls.stop("owner", "chat", "old-request-123456")
        self.assertFalse(task.done())
        await controls.stop("owner", "chat", handle[0][2])
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(closed.is_set())
        self.assertNotIn(handle[0], controls.runs)
        self.assertIn(other[0], controls.runs)

    async def test_early_stop_never_starts_inference_and_busy_unload_protects_other_chat(self):
        controls = Controls()
        handle = controls.reserve("owner", "chat", DEFAULT_MODEL)
        await controls.stop("owner", "chat", handle[0][2])
        with self.assertRaises(HTTPException):
            await controls.unload(DEFAULT_MODEL)
        with self.assertRaises(asyncio.CancelledError):
            async with controls.running(handle):
                self.fail("Cancelled request must not start inference")
        self.assertFalse(controls.runs)
        controls.unloading.add(DEFAULT_MODEL)
        with self.assertRaises(HTTPException):
            controls.reserve("owner", "chat", DEFAULT_MODEL)

    async def test_unload_uses_no_prompt_no_credentials_and_verifies_memory_release(self):
        requests = []
        def remote(request):
            requests.append(request)
            self.assertEqual(request.url.host, "127.0.0.1")
            self.assertNotIn("authorization", request.headers)
            data = {"/api/tags": {"models": [{"name": DEFAULT_MODEL}]},
                    "/api/show": {"model_info": {"general.architecture": "qwen3"}, "details": {"format": "gguf"}},
                    "/api/ps": {"models": []}}.get(request.url.path, {})
            return httpx.Response(200, json=data)
        with patch("app.local_control.Client", side_effect=lambda cfg: Client(cfg, httpx.MockTransport(remote))):
            controls = Controls()
            await controls.unload(DEFAULT_MODEL)
        body = json.loads(next(r.content for r in requests if r.url.path == "/api/generate"))
        self.assertEqual(body, {"model": DEFAULT_MODEL, "keep_alive": 0})
        self.assertFalse(controls.unloading)

    async def test_unload_rejects_cloud_and_does_not_claim_success_while_model_remains_loaded(self):
        controls = Controls()
        with self.assertRaisesRegex(ValueError, "cloud"):
            await controls.unload("qwen3:cloud")
        def remote(request):
            return httpx.Response(200, json={
                "models": [{"name": DEFAULT_MODEL}],
                "model_info": {"general.architecture": "qwen3"}, "details": {"format": "gguf"}})
        with patch("app.local_control.Client", side_effect=lambda cfg: Client(cfg, httpx.MockTransport(remote))):
            with self.assertRaisesRegex(HTTPException, "still has"):
                await controls.unload(DEFAULT_MODEL)
        self.assertFalse(controls.unloading)


class ControlRouteTests(unittest.TestCase):
    setUp = fixtures.LocalAITests.setUp
    tearDown = fixtures.LocalAITests.tearDown
    client = fixtures.LocalAITests.client

    def test_server_stop_closes_ollama_request_saves_no_reply_and_releases_chat_lock(self):
        async def run():
            ready = asyncio.Event()
            class Slow(httpx.AsyncByteStream):
                closed = False
                async def __aiter__(self):
                    ready.set()
                    await asyncio.Event().wait()
                    yield b""
                async def aclose(self):
                    self.closed = True
            slow = Slow()
            def remote(request):
                if request.url.path == "/api/chat":
                    return httpx.Response(200, stream=slow)
                return httpx.Response(200, json={
                    "models": [{"name": DEFAULT_MODEL}],
                    "model_info": {"general.architecture": "qwen3"}, "details": {"format": "gguf"}})
            app = create_app(self.store, client_factory=fixtures.FakeAI)
            cid = self.store.new_conversation()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://127.0.0.1") as client:
                response = await client.post("/api/login", json={"password": self.store.password})
                headers = {"x-csrf-token": response.json()["csrf"]}
                with patch("app.ollama_local.Client", side_effect=lambda cfg: Client(cfg, httpx.MockTransport(remote))):
                    task = asyncio.create_task(client.post("/api/chat", headers=headers, json={
                        "conversation": cid, "question": "Hello", "local_ai": True,
                        "request_id": "local-request-123456"}))
                    await asyncio.wait_for(ready.wait(), 3)
                    stopped = await client.post("/api/local-ai/stop", headers=headers, json={
                        "conversation": cid, "request_id": "local-request-123456", "unload": False})
                    self.assertEqual(stopped.status_code, 200)
                    try:
                        await task
                    except (asyncio.CancelledError, AssertionError):
                        # ASGITransport cannot finish a deliberately cancelled SSE body.
                        pass
                self.assertTrue(slow.closed)
                self.assertEqual(self.store.rows("SELECT id FROM turns WHERE conversation=?", (cid,)), [])
                retry = await client.post("/api/chat", headers=headers, json={"conversation": cid, "question": "Hello"})
                self.assertEqual(retry.status_code, 200)
                self.assertIn('"event": "done"', retry.text)
        asyncio.run(run())

    def test_routes_require_login_csrf_loopback_and_allow_disabling(self):
        client, headers = self.client()
        body = {"model": DEFAULT_MODEL, "unload": True}
        with client:
            self.assertEqual(client.post("/api/local-ai/stop", json=body).status_code, 403)
            with patch("app.local_control.Controls.unload", new=lambda *_: asyncio.sleep(0)):
                self.assertEqual(client.post("/api/local-ai/stop", headers=headers, json=body).status_code, 200)
            self.assertEqual(client.post("/api/local-ai/stop", headers=headers,
                                        json={"unload": "yes"}).status_code, 400)
            self.assertTrue(client.get("/api/state").json()["local_control"])
        app = create_app(self.store)
        with TestClient(app, base_url="http://127.0.0.1", client=("192.0.2.10", 1234)) as remote:
            csrf = remote.post("/api/login", json={"password": self.store.password}).json()["csrf"]
            self.assertEqual(remote.post("/api/local-ai/stop", headers={"x-csrf-token": csrf}, json=body).status_code, 403)
        with TestClient(app, base_url="http://127.0.0.1") as anonymous:
            self.assertEqual(anonymous.post("/api/local-ai/stop", json=body).status_code, 401)
        with patch.dict(os.environ, {"AIMATE_LOCAL_CONTROL_ENABLED": "0"}):
            client, headers = self.client()
            with client:
                self.assertFalse(client.get("/api/state").json()["local_control"])
                self.assertEqual(client.post("/api/local-ai/stop", headers=headers, json=body).status_code, 404)
