"""Bound local CPU work and suppress thinking without delaying plain answers."""
import asyncio
import time
import unittest
from unittest.mock import patch
import httpx

from app.local_inference import ThoughtFilter, options
from app.ollama_local import Client, DEFAULT_MODEL


class LocalInferenceTests(unittest.TestCase):
    def test_context_and_output_adapt_without_unbounded_cpu_threads(self):
        small,large=options(1000,4096),options(64000,4096)
        self.assertEqual(small,{"num_ctx":8192,"num_predict":1024,"num_thread":4})
        self.assertEqual(large["num_ctx"],32768)

    def test_thought_filter_handles_every_split_and_plain_answer_immediately(self):
        raw="<think>Hidden internal thought</think>Ready."
        for cut in range(len(raw)+1):
            f=ThoughtFilter()
            self.assertEqual(f.feed(raw[:cut])+f.feed(raw[cut:])+f.finish(),"Ready.")
        f=ThoughtFilter()
        self.assertEqual(f.feed("Plain answer."),"Plain answer.")
        self.assertEqual(f.finish(),"")
        f.feed("<think>Still thinking")
        with self.assertRaisesRegex(ValueError,"No incomplete answer"):f.finish()
        self.assertEqual(f.finish(tool_calls=True),"")

    def test_stream_wall_clock_timeout_closes_response_even_when_chunks_keep_arriving(self):
        class Slow(httpx.AsyncByteStream):
            closed=False
            async def __aiter__(self):
                while True:
                    await asyncio.sleep(.01)
                    yield b'{"message":{"content":"<think>"},"done":false}\n'
            async def aclose(self):self.closed=True
        slow=Slow()
        async def remote(request):
            if request.url.path=="/api/tags":
                return httpx.Response(200,json={"models":[{"name":DEFAULT_MODEL}]})
            if request.url.path=="/api/show":
                return httpx.Response(200,json={"model_info":{"general.architecture":"qwen3"},
                    "details":{"format":"gguf"}})
            return httpx.Response(200,stream=slow)
        async def run():
            client=Client({"ai":{"model":DEFAULT_MODEL}},httpx.MockTransport(remote))
            try:
                with patch("app.ollama_local.MAX_SECONDS",.05):
                    with self.assertRaisesRegex(ValueError,"2 minutes"):
                        async with client.stream(model=DEFAULT_MODEL,system="Test",messages=[
                                {"role":"user","content":"Hello"}],tools=[]) as stream:
                            async for _ in stream.text_stream:pass
                self.assertTrue(slow.closed)
            finally:await client.close()
        asyncio.run(run())

    def test_timeout_budget_is_shared_across_model_calls(self):
        client=Client({"ai":{"model":DEFAULT_MODEL}},httpx.MockTransport(lambda r:httpx.Response(200)))
        client.started=time.monotonic()-121
        try:
            with self.assertRaisesRegex(ValueError,"2 minutes"):client.remaining()
        finally:asyncio.run(client.close())
