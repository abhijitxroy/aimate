"""Bounded independent reads, ordered results and same-turn single-flight reuse."""
import asyncio
import json

MAX_CONCURRENCY = 4


def reused(result):
    return {"source": result["source"], "data": {"reused_this_turn": True,
            "note": "This exact source was already read in this turn. Use the earlier full result.",
            "excerpt": json.dumps(result["data"], ensure_ascii=False)[:1200]}}


async def read_evidence(services, args, cache):
    key = json.dumps([args["service"], args["path"], args.get("params")], sort_keys=True)
    if key in cache:
        return reused(cache[key])
    pending_key = ("pending", key)
    if pending_key in cache:
        result, error = await asyncio.shield(cache[pending_key])
        if error:
            raise error
        return reused(result)
    pending = asyncio.get_running_loop().create_future()
    cache[pending_key] = pending
    try:
        result = await services.read(args["service"], args["path"], args.get("params"))
        if len(cache) < 40:
            cache[key] = result
        pending.set_result((result, None))
        return result
    except BaseException as error:
        if not pending.done():
            pending.set_result((None, error))
        raise
    finally:
        cache.pop(pending_key, None)


async def prefetch_reads(calls, services, cache, *, responses=False):
    """Prefetch only an all-read round; mixed read/write rounds stay sequential."""
    if len(calls) < 2 or any(call.get("name") != "api_read" or
                            call.get("namespace") not in {None, "project"} for call in calls):
        return None
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def read(call):
        async with semaphore:
            args = json.loads(call["arguments"]) if responses else call.get("input", {})
            if not isinstance(args, dict):
                raise ValueError("Tool arguments must be an object")
            return await read_evidence(services, args, cache)

    return await asyncio.gather(*(read(call) for call in calls), return_exceptions=True)
