"""Slow SDK initialization must not freeze other requests on the event loop."""
import asyncio
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

from app.agent import run_turn
from app.connection_checks import check_connection
from app.store import Store

def fixture_config():
    return {"ai": {"provider": "anthropic", "model": "test", "api_key": "synthetic-test-key"},
            "github": {"url": "https://api.github.com", "repos": ["example/repo"], "token": ""},
            "jira": {"url": "", "projects": []},
            "jenkins": {"url": "", "jobs": []}, "allow_writes": False}


class ClientInitializationTests(unittest.IsolatedAsyncioTestCase):
    async def assert_responsive(self, operation):
        released = threading.Event()
        async def close():
            pass
        async def create(**kwargs):
            return SimpleNamespace(model="test", content=[])
        def slow_factory(config):
            released.wait(2)
            return SimpleNamespace(close=close, messages=SimpleNamespace(create=create))
        fallback = threading.Timer(2, released.set)
        fallback.start()
        started = time.monotonic()
        task = asyncio.create_task(operation(slow_factory))
        try:
            await asyncio.sleep(.05)
            self.assertLess(time.monotonic() - started, 1,
                            "SDK loading blocked the server event loop")
        finally:
            released.set()
            await task
            fallback.cancel()

    async def test_connection_check_initialization_does_not_block(self):
        async def operation(factory):
            result = await check_connection("ai", fixture_config(), None, factory, None)
            self.assertTrue(result["ok"])
        await self.assert_responsive(operation)

    async def test_chat_initialization_does_not_block(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            store.save_config(fixture_config())
            cid = store.new_conversation()
            async def operation(factory):
                events = run_turn(store, cid, "Hello", model_mode="standard",
                                  client_factory=factory,
                                  services_factory=lambda config: SimpleNamespace())
                try:
                    self.assertEqual((await anext(events))["event"], "model")
                finally:
                    await events.aclose()
            try:
                await self.assert_responsive(operation)
            finally:
                store.db.close()
