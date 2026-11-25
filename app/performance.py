"""Observed section timings and operator-labelled baselines, without prompt data."""
import json
import math
import os
import re
import secrets
import time
from fastapi import Depends, HTTPException, Request
from app.connectors import scrub

PREFIXES = (
    ("/api/chat", "Chat"), ("/api/conversations", "Conversations"),
    ("/api/groups", "Projects"), ("/api/todos", "To-do"),
    ("/api/knowledge", "My Diary"), ("/api/library", "Prompts"),
    ("/api/attachments", "Attachments"), ("/api/connections", "Connections"),
    ("/api/settings", "Settings"), ("/api/usage", "Usage"),
    ("/api/chatgpt", "Models"), ("/api/gemini", "Models"),
    ("/api/bedrock", "Models"), ("/api/opencode", "Models"),
    ("/api/state", "Workspace"), ("/api/access", "Access"),
    ("/api/login", "Access"), ("/api/logout", "Access"),
)


def enabled():
    return os.environ.get("AIMATE_PERFORMANCE_ENABLED") != "0"


def install(store):
    store.db.execute("""CREATE TABLE IF NOT EXISTS performance_baselines
        (id TEXT PRIMARY KEY, label TEXT NOT NULL, created REAL NOT NULL, body TEXT NOT NULL)""")


def section(route):
    return next((name for prefix, name in PREFIXES if route == prefix or route.startswith(prefix + "/")), "Other")


def percentile(values, percent):
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * percent) - 1)], 2) if values else None


def summarize(records):
    grouped = {}
    ignored = 0
    valid = []
    for record in records:
        if not isinstance(record, dict):
            ignored += 1
            continue
        route, status, duration = record.get("route"), record.get("status"), record.get("duration_ms")
        if (not isinstance(route, str) or not route.startswith("/api/") or "?" in route
                or type(status) is not int or not 100 <= status <= 599
                or type(duration) not in (int, float) or not math.isfinite(duration) or not 0 <= duration <= 86_400_000
                or type(record.get("complete")) is not bool):
            ignored += 1
            continue
        valid.append(record)
        grouped.setdefault(section(route), []).append(record)
    rows = []
    for name, entries in sorted(grouped.items()):
        times = [float(r["duration_ms"]) for r in entries if r["complete"]]
        failures = sum(r["status"] >= 400 for r in entries)
        stamps = [r["created"] for r in entries if type(r.get("created")) in (int, float)
                  and math.isfinite(r["created"])]
        span = max(stamps) - min(stamps) if len(stamps) > 1 else 0
        rows.append({"section": name, "requests": len(entries), "complete": len(times),
                     "incomplete": len(entries) - len(times), "errors": failures,
                     "error_percent": round(failures / len(entries) * 100, 2),
                     "sample_minutes": round(span / 60, 2),
                     "requests_per_minute": round(len(entries) / (span / 60), 2) if span >= 60 else None,
                     "p50_ms": percentile(times, .5), "p95_ms": percentile(times, .95)})
    times = [float(r["duration_ms"]) for r in valid if r["complete"]]
    return {"requests": len(valid), "incomplete": len(valid) - len(times), "ignored": ignored,
            "p50_ms": percentile(times, .5), "p95_ms": percentile(times, .95), "sections": rows}


def observations(directory):
    root = directory.resolve()
    records = []
    for name in ("requests.jsonl.1", "requests.jsonl"):
        path = root / name
        if not path.is_file() or path.is_symlink() or path.resolve().parent != root:
            continue
        # The logger rotates at 1 MB. Bound even a manually replaced file.
        try:
            if path.stat().st_size > 2_000_000:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
            except ValueError:
                continue
    return summarize(records[-200:])


def usage(store, since):
    totals = {key: 0 for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    reported, invalid = 0, 0
    for row in store.rows("SELECT tokens FROM usage_events WHERE created>=?", (since,)):
        try:
            values = json.loads(row["tokens"])
            if not isinstance(values, dict) or any(type(values.get(key, 0)) is not int or values.get(key, 0) < 0 for key in totals):
                raise ValueError()
            for key in totals:
                totals[key] += values.get(key, 0)
            reported += 1
        except (ValueError, TypeError):
            invalid += 1
    return {**totals, "reported_calls": reported, "invalid_records": invalid}


def compare(current, baseline):
    previous = {row["section"]: row for row in baseline.get("sections", [])}
    result = []
    for row in current["sections"]:
        old = previous.get(row["section"])
        enough = bool(old and old["complete"] >= 5 and row["complete"] >= 5)
        delta = None
        if enough and old["p95_ms"]:
            delta = round((row["p95_ms"] / old["p95_ms"] - 1) * 100, 2)
        result.append({**row, "baseline_p95_ms": old["p95_ms"] if old else None,
                       "p95_change_percent": delta, "comparable_sample": enough})
    return result


def snapshot(store, directory):
    result = observations(directory)
    result.update(created=time.time(), reported_tokens_24h=usage(store, time.time() - 86400),
                  resources=resources())
    return result


def resources():
    result = {"cpu_seconds": round(time.process_time(), 3), "memory_mb": None, "memory_kind": "unavailable"}
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            class Memory(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("page_faults", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
                        "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), wintypes.DWORD]
            memory = Memory()
            memory.cb = ctypes.sizeof(memory)
            if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb):
                result.update(memory_mb=round(memory.working / 1048576, 2), memory_kind="working set")
        else:
            import resource
            import sys
            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            result.update(memory_mb=round(value / (1048576 if sys.platform == "darwin" else 1024), 2),
                          memory_kind="peak RSS")
    except (ImportError, OSError, AttributeError):
        pass
    return result


def save_baseline(store, directory, body):
    if not isinstance(body, dict) or set(body) != {"label"}:
        raise ValueError("Provide only a baseline label; measurements are taken by the server.")
    label = body["label"]
    if (not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}", label)
            or scrub(label, store.config()) != label):
        raise ValueError("Use a short label without secrets or URLs.")
    if store.rows("SELECT count(*) AS n FROM performance_baselines")[0]["n"] >= 25:
        raise ValueError("Keep up to 25 baselines. Remove an unused baseline before adding another.")
    data = snapshot(store, directory)
    if not data["requests"]:
        raise ValueError("No request measurements are available yet.")
    ident = secrets.token_hex(16)
    store.execute("INSERT INTO performance_baselines VALUES (?,?,?,?)",
                  (ident, label, time.time(), json.dumps(data)))
    return {"id": ident}


def register(app, owner, store, auth, config_lock):
    def permitted(session):
        if not enabled():
            raise HTTPException(404, "Performance dashboard is disabled.")
        if session.get("role") not in {"admin", "developer"}:
            raise HTTPException(403, "Administrator or developer access required.")

    @app.get("/api/performance")
    def report(baseline: str = "", session=Depends(auth)):
        permitted(session)
        current = snapshot(store, owner.directory)
        baselines = store.rows("SELECT id,label,created FROM performance_baselines ORDER BY created DESC")
        compared = []
        selected = None
        if baseline:
            old = store.rows("SELECT body FROM performance_baselines WHERE id=?", (baseline,))
            if not old:
                raise ValueError("Choose an existing baseline.")
            selected = json.loads(old[0]["body"])
            compared = compare(current, selected)
        return {"current": current, "baselines": baselines, "comparison": compared, "baseline_snapshot": selected,
                "notice": "Last 200 app-wide HTTP requests; streamed latency includes the whole response. Token totals cover this workspace's reported calls in the last 24 hours. Baselines use different samples, so changes are observations rather than proof that a code change caused an improvement."}

    @app.post("/api/performance/baselines")
    async def save(request: Request, session=Depends(auth)):
        permitted(session)
        async with config_lock:
            return save_baseline(store, owner.directory, await request.json())

    @app.delete("/api/performance/baselines/{ident}")
    async def remove(ident: str, session=Depends(auth)):
        permitted(session)
        async with config_lock:
            if not store.rows("SELECT id FROM performance_baselines WHERE id=?", (ident,)):
                raise ValueError("Baseline was not found.")
            store.execute("DELETE FROM performance_baselines WHERE id=?", (ident,))
        return {"deleted": ident}
