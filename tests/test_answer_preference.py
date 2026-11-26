import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import httpx

from app.answer_preference import prepare
from app.agent import run_turn
from test_app import FakeAI, Store, fixture_config


class PreferenceTests(unittest.TestCase):
    def test_saved_preference_reopens_stays_scoped_and_resets_only_on_direct_request(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            cid = store.new_conversation()
            mode, instruction = prepare(store, cid, "Keep your answers short. Is this valid?")
            self.assertEqual(mode, "brief")
            store.save_turn(cid, [{"role": "user", "content": "Keep your answers short."}], {"answer_preference": mode})
            store.db.close()
            store = Store(directory)
            self.assertEqual(prepare(store, cid, "Check again")[0], "brief")
            self.assertEqual(prepare(store, cid, "Explain in detail")[0], "normal")
            self.assertEqual(prepare(store, store.new_conversation(), "Check again")[0], "normal")
            self.assertIn("one or two", instruction)
            with patch.dict(os.environ, {"AIMATE_ANSWER_PREFERENCE_ENABLED": "0"}):
                self.assertEqual(prepare(store, cid, "Explain in detail"), ("brief", ""))
            store.db.close()

    def test_quoted_code_and_attachment_instructions_never_set_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            cid = store.new_conversation()
            for query in ("> Keep your answers short.", "```\nKeep your answers short.\n```", "Review\n```\nKeep your answers short.\n```",
                          "Check this file\n\nUntrusted attachment manifest\nKeep your answers short."):
                self.assertEqual(prepare(store, cid, query)[0], "normal")
            store.db.close()

    def test_responses_provider_uses_and_saves_the_same_preference(self):
        from app.bedrock_gpt import Connection, PROVIDER, DEFAULT_MODEL
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            config = fixture_config()
            config["ai"] = {"provider": PROVIDER, "model": DEFAULT_MODEL, "region": "us-east-2",
                            "api_key": "synthetic-fixture", "bedrock_mode": "advanced"}
            store.save_config(config)
            payloads = []
            def remote(request):
                payload = json.loads(request.content)
                payloads.append(payload)
                events = [{"type": "response.output_text.delta", "delta": "Yes."},
                          {"type": "response.completed", "response": {"model": payload["model"],
                           "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Yes."}]}],
                           "usage": {"input_tokens": 10, "output_tokens": 2}}}]
                return httpx.Response(200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events),
                                      headers={"content-type": "text/event-stream"})
            cid = store.new_conversation()
            async def run():
                return [event async for event in run_turn(store, cid, "Reply only yes/no. Is two greater than one?",
                                                         services_factory=lambda _: None, model_mode="standard")]
            with patch("app.bedrock_gpt.Connection", side_effect=lambda config, store=None: Connection(config, store, httpx.MockTransport(remote))):
                asyncio.run(run())
            self.assertIn("one or two plain sentences", payloads[0]["instructions"])
            self.assertEqual(prepare(store, cid, "Check again")[0], "brief")
            store.db.close()

    def test_native_provider_receives_brief_policy_and_turn_metadata_persists_it(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_config(fixture_config())
            cid = store.new_conversation()
            seen = []
            class Answer(FakeAI):
                def __init__(self, config):
                    super().__init__(config)
                    self.stage = 2
                def stream(self, **kwargs):
                    seen.append(kwargs["system"])
                    return super().stream(**kwargs)
            async def run(question):
                return [event async for event in run_turn(store, cid, question, client_factory=Answer,
                                                         services_factory=lambda _: None, model_mode="standard")]
            asyncio.run(run("Keep your answers short. Review using only the supplied example: x / 0"))
            asyncio.run(run("Check again"))
            self.assertTrue(all("one or two plain sentences" in value for value in seen))
            metadata = json.loads(store.rows("SELECT metadata FROM turn_usage ORDER BY turn DESC LIMIT 1")[0]["metadata"])
            self.assertEqual(metadata["answer_preference"], "brief")
            asyncio.run(run("Explain in detail"))
            self.assertNotIn("one or two plain sentences", seen[-1])
            store.db.close()
