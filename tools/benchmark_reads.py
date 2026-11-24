"""Offline synthetic read benchmark; no credentials, provider calls or billing."""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.read_batch import prefetch_reads, read_evidence


class Source:
    active = 0
    maximum = 0
    calls = 0

    async def read(self, service, path, params):
        self.active += 1
        self.calls += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(.02)
            return {"source": "https://example.test" + path, "data": {"text": "synthetic evidence " * 2000}}
        finally:
            self.active -= 1


async def benchmark():
    calls = [{"name": "api_read", "input": {"service": "github", "path": f"/repos/example/demo/issues/{i}"}}
             for i in range(12)]
    sequential, parallel = [], []
    for _ in range(5):
        source, cache = Source(), {}
        started = time.perf_counter()
        for call in calls:
            await read_evidence(source, call["input"], cache)
        sequential.append((time.perf_counter() - started) * 1000)
        source, cache = Source(), {}
        started = time.perf_counter()
        await prefetch_reads(calls, source, cache)
        parallel.append((time.perf_counter() - started) * 1000)
        assert source.maximum == 4 and source.calls == 12
    observed_parallel = source.maximum
    source = Source()
    repeats = await prefetch_reads([calls[0]] * 4, source, {})
    full, compact = len(json.dumps(repeats[0])), len(json.dumps(repeats[1]))
    return {"fixture": "12 independent 20ms source reads; 5 samples; offline only",
            "sequential_p50_ms": round(statistics.median(sequential), 2),
            "parallel_p50_ms": round(statistics.median(parallel), 2),
            "sequential_p95_ms": round(max(sequential), 2),
            "parallel_p95_ms": round(max(parallel), 2),
            "median_speedup": round(statistics.median(sequential) / statistics.median(parallel), 2),
            "max_parallel": observed_parallel, "duplicate_reads_fetched": source.calls,
            "repeat_context_reduction_percent": round((1 - compact / full) * 100, 2)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(benchmark())
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
