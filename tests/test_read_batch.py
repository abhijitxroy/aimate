import asyncio
import json
import unittest
import tempfile
from types import SimpleNamespace

from app.read_batch import prefetch_reads, read_evidence


class ReadBatchTests(unittest.IsolatedAsyncioTestCase):
    def source(self, fail=None):
        class Source:
            calls = 0
            active = 0
            maximum = 0
            async def read(self, service, path, params):
                self.calls += 1
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                try:
                    await asyncio.sleep(.01)
                    if path == fail:
                        raise ValueError("Synthetic source failure")
                    return {"source": "https://example.test" + path, "data": {"path": path, "text": "evidence " * 3000}}
                finally:
                    self.active -= 1
        return Source()

    def calls(self, count):
        return [{"name": "api_read", "input": {"service": "github", "path": f"/repos/team/repo/issues/{i}"}}
                for i in range(count)]

    async def test_parallelism_is_bounded_and_results_keep_original_order(self):
        source = self.source()
        calls = self.calls(12)
        result = await prefetch_reads(calls, source, {})
        self.assertEqual(source.maximum, 4)
        self.assertEqual(source.calls, 12)
        self.assertEqual([value["data"]["path"] for value in result], [call["input"]["path"] for call in calls])

    async def test_duplicate_concurrent_reads_fetch_once_and_reuse_compact_evidence(self):
        source = self.source()
        call = self.calls(1)[0]
        result = await prefetch_reads([call] * 4, source, {})
        self.assertEqual(source.calls, 1)
        self.assertTrue(all(value["data"]["reused_this_turn"] for value in result[1:]))
        self.assertLess(len(json.dumps(result[1])), len(json.dumps(result[0])) // 5)

    async def test_errors_remain_per_read_and_are_not_cached(self):
        calls = self.calls(3)
        source = self.source(calls[1]["input"]["path"])
        cache = {}
        result = await prefetch_reads(calls, source, cache)
        self.assertIsInstance(result[1], ValueError)
        self.assertEqual(result[2]["data"]["path"], calls[2]["input"]["path"])
        with self.assertRaises(ValueError):
            await read_evidence(source, calls[1]["input"], cache)
        self.assertEqual(source.calls, 4)

    async def test_mixed_writes_and_invalid_namespaces_never_prefetch(self):
        source = self.source()
        self.assertIsNone(await prefetch_reads(self.calls(1) + [{"name": "propose_action"}], source, {}))
        calls = self.calls(2)
        calls[0]["namespace"] = "untrusted"
        self.assertIsNone(await prefetch_reads(calls, source, {}))
        self.assertEqual(source.calls, 0)

    async def test_responses_arguments_and_cancellation_cleanup(self):
        source = self.source()
        calls = [{"name": "api_read", "namespace": "project", "arguments": json.dumps(call["input"])}
                 for call in self.calls(6)]
        result = await prefetch_reads(calls, source, {}, responses=True)
        self.assertEqual(len(result), 6)
        cache = {}
        task = asyncio.create_task(prefetch_reads(self.calls(12), source, cache))
        await asyncio.sleep(.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(source.active, 0)
        self.assertFalse(any(isinstance(key, tuple) for key in cache))

    async def test_agent_uses_parallel_reads_and_preserves_tool_result_ids(self):
        from test_app import Store, fixture_config, FakeBlock
        from app.agent import run_turn
        source, calls = self.source(), self.calls(4)
        class Stream:
            def __init__(self, stage): self.stage = stage
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            @property
            def text_stream(self):
                async def chunks():
                    if self.stage: yield "Four sources checked."
                return chunks()
            async def get_final_message(self):
                blocks = ([FakeBlock(type="tool_use", id=f"read-{i}", **call) for i,call in enumerate(calls)]
                          if self.stage == 0 else [FakeBlock(type="text", text="Four sources checked.")])
                return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=30, output_tokens=10))
        class AI:
            def __init__(self, config): self.messages, self.stage = self, 0
            def stream(self, **kwargs):
                stream = Stream(self.stage); self.stage += 1; return stream
            async def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.save_config(fixture_config())
                cid = store.new_conversation()
                events = [event async for event in run_turn(store, cid, "Read four sources",
                          client_factory=AI, services_factory=lambda config: source, model_mode="standard")]
                self.assertEqual(source.maximum, 4)
                self.assertEqual(events[-1]["event"], "done")
                results = [block["tool_use_id"] for message in store.history(cid)
                           if isinstance(message.get("content"), list) for block in message["content"]
                           if block.get("type") == "tool_result"]
                self.assertEqual(results, [f"read-{i}" for i in range(4)])
            finally:
                store.db.close()
