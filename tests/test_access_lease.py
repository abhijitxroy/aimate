import asyncio
import tempfile
import time
import unittest
from types import SimpleNamespace

from test_app import Store, fixture_config, FakeBlock
from app.access import issue
from app.access_lease import lease
from app.agent import run_turn
from app.connectors import Services
import httpx


class AccessLeaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.store.save_config(fixture_config())
        self.grant = issue(self.store, {"name": "Synthetic developer", "role": "developer"})
        self.session = {"token": "synthetic-session", "created": time.time(),
                        "role": "developer", "grant": self.grant["id"]}
        self.sessions = {self.session["token"]: self.session}
        self.check = lease(self.store, self.sessions, self.session)

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def test_revocation_role_change_expiry_and_logout_stop_existing_lease(self):
        self.check()
        for column, value, message in [
            ("role", "viewer", "role changed"), ("revoked", 1, "revoked"),
            ("expires", time.time() - 1, "expired")]:
            self.store.execute(f"UPDATE access_grants SET {column}=? WHERE id=?", (value, self.grant["id"]))
            with self.assertRaisesRegex(ValueError, message):
                self.check()
            self.store.execute("UPDATE access_grants SET role='developer',revoked=0,expires=? WHERE id=?",
                               (time.time() + 1000, self.grant["id"]))
        self.sessions.clear()
        with self.assertRaisesRegex(ValueError, "Session ended"):
            self.check()

    def test_role_downgrade_during_model_call_prevents_following_tool_read(self):
        store, grant = self.store, self.grant
        reads = []
        closed = []

        class Source:
            def __init__(self, config): pass
            async def read(self, *args):
                reads.append(args)
                return {"source": "https://example.test", "data": "private evidence"}
            async def aclose(self): closed.append("source")

        class Stream:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            @property
            def text_stream(self):
                async def chunks():
                    if False: yield ""
                return chunks()
            async def get_final_message(self):
                store.execute("UPDATE access_grants SET role='viewer' WHERE id=?", (grant["id"],))
                return SimpleNamespace(content=[FakeBlock(type="tool_use", id="read", name="api_read",
                    input={"service": "github", "path": "/repos/team/repo"})],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5))

        class AI:
            def __init__(self, config): self.messages = self
            def stream(self, **kwargs): return Stream()
            async def close(self): closed.append("model")

        cid = store.new_conversation()
        async def run():
            return [event async for event in run_turn(store, cid, "Read the repo",
                client_factory=AI, services_factory=Source, model_mode="standard",
                role="developer", access_check=self.check)]
        with self.assertRaisesRegex(ValueError, "role changed"):
            asyncio.run(run())
        self.assertEqual(reads, [])
        self.assertEqual(store.history(cid), [])
        self.assertIn("source", closed)
        self.assertIn("model", closed)

    def test_revocation_during_http_call_blocks_result_and_following_request(self):
        calls = []
        def response(request):
            calls.append(request.url.path)
            self.store.execute("UPDATE access_grants SET revoked=1 WHERE id=?", (self.grant["id"],))
            return httpx.Response(200, json={"private": "should not be forwarded"})

        async def run():
            source = Services(fixture_config(), transport=httpx.MockTransport(response))
            source.access_check = self.check
            try:
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, "revoked"):
                        await source.read("github", "/repos/team/repo")
            finally:
                await source.aclose()
        asyncio.run(run())
        self.assertEqual(len(calls), 1)
