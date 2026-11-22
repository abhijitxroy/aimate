"""Local reported token ledger; prices are operator supplied, never invented invoices."""
import datetime as dt
import json
import math
import secrets
import time


def record(store, config, model, incoming, origin="Chat"):
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    tokens = {key: max(0, int(incoming.get(key, 0) or 0)) for key in keys}
    details = incoming.get("input_tokens_details", {})
    cached = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
    if cached:
        tokens["cache_read_input_tokens"] = min(tokens["input_tokens"], max(0, int(cached)))
        tokens["input_tokens"] -= tokens["cache_read_input_tokens"]
    if not any(tokens.values()):
        return
    store.execute("INSERT INTO usage_events VALUES (?,?,?,?,?,?)",
                  (secrets.token_hex(16), time.time(), config.get("ai", {}).get("provider", "anthropic"),
                   model, json.dumps(tokens), origin))


def report(store, days=30, offset=0):
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 366:
        raise ValueError("Choose 1–366 days.")
    if not -840 <= offset <= 840:
        raise ValueError("Invalid timezone offset.")
    timezone = dt.timezone(dt.timedelta(minutes=offset))
    today = dt.datetime.now(timezone).date()
    start = dt.datetime.combine(today - dt.timedelta(days=days - 1), dt.time.min, timezone).timestamp()
    rates = {r["model"]: r for r in store.rows("SELECT * FROM usage_rates")}
    daily, models = {}, {}
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    total = dict.fromkeys(keys, 0)
    total.update(requests=0, estimated_usd=0, unpriced_requests=0)
    for row in store.rows("SELECT * FROM usage_events WHERE created>=? ORDER BY created", (start,)):
        date = dt.datetime.fromtimestamp(row["created"], timezone).date().isoformat()
        model = row["model"]
        tokens = json.loads(row["tokens"])
        rate = rates.get(model)
        # ChatGPT subscription usage has no per-token invoice in this app.
        cost = (sum(tokens.get(k, 0) * rate[r] for k, r in zip(keys, ("input", "output", "cache_read", "cache_write"))) / 1_000_000
                if rate and row["provider"] != "chatgpt" else None)
        for target in (total, daily.setdefault(date, {**dict.fromkeys(keys, 0), "requests": 0, "estimated_usd": 0, "unpriced_requests": 0}),
                       models.setdefault(model, {**dict.fromkeys(keys, 0), "model": model, "requests": 0, "estimated_usd": 0, "unpriced_requests": 0})):
            for key in keys:
                target[key] += tokens.get(key, 0)
            target["requests"] += 1
            target["estimated_usd"] += cost or 0
            target["unpriced_requests"] += int(cost is None)
    return {"days": days, "timezone_offset": offset, "totals": total,
            "daily": [{"date": key, **value} for key, value in sorted(daily.items())],
            "models": sorted(models.values(), key=lambda row: row["input_tokens"] + row["output_tokens"], reverse=True),
            "rates": list(rates.values()),
            "coverage": "AiMate reported chat and routing usage only. Each entry is a reported request or an imported historical turn/model total. Connection checks and calls without a usage report are excluded. Costs are estimates at your current rates, not an invoice. ChatGPT plan limits and organization spend are managed by your provider."}


def save_rate(store, body):
    if not isinstance(body, dict) or not isinstance(body.get("model"), str) or not 1 <= len(body["model"].strip()) <= 200:
        raise ValueError("Provide a model ID.")
    values = []
    for field in ("input", "output", "cache_read", "cache_write"):
        value = body.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100000:
            raise ValueError("Use nonnegative USD rates per million tokens.")
        values.append(value)
    store.execute("INSERT OR REPLACE INTO usage_rates VALUES (?,?,?,?,?)", (body["model"].strip(), *values))
    return {"saved": body["model"].strip()}
