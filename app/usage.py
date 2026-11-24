"""Local reported token ledger; prices are operator supplied, never invented invoices."""
import datetime as dt
import json
import math
import secrets
import time
import re


def preferences(store):
    rows = store.rows("SELECT body FROM usage_preferences WHERE id=1")
    return json.loads(rows[0]["body"]) if rows else {"monthly_usd": 0, "mode": "warn"}


def save_budget(store, body):
    value = body.get("monthly_usd") if isinstance(body, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1000000:
        raise ValueError("Use a monthly USD budget from 0 to 1,000,000; zero disables it.")
    if body.get("mode") not in {"warn", "stop"}:
        raise ValueError("Choose warn or stop.")
    saved = {"monthly_usd": value, "mode": body["mode"]}
    store.execute("INSERT OR REPLACE INTO usage_preferences VALUES (1,?)", (json.dumps(saved),))
    return saved


def reconcile(store, body):
    if not isinstance(body, dict) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(body.get("month", ""))):
        raise ValueError("Use a billing month as YYYY-MM.")
    try:
        parsed=dt.datetime.strptime(body["month"],"%Y-%m")
        if not 1900<=parsed.year<=2100: raise ValueError()
    except ValueError:
        raise ValueError("Use a valid billing month.") from None
    model, amount = body.get("model"), body.get("amount")
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 200:
        raise ValueError("Provide the invoice's exact model ID.")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or not 0 <= amount <= 1000000:
        raise ValueError("Provide a nonnegative billed USD amount.")
    key = body["month"] + ":" + model.strip()
    store.execute("INSERT OR REPLACE INTO usage_invoices VALUES (?,?,?,?)", (key, body["month"], model.strip(), amount))
    return {"saved": key}


def monthly(store, month=None):
    month = month or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m")
    first = dt.datetime.strptime(month, "%Y-%m").replace(tzinfo=dt.timezone.utc)
    start = first.timestamp()
    end = (first + dt.timedelta(days=32)).replace(day=1).timestamp()
    rates = {r["model"]: r for r in store.rows("SELECT * FROM usage_rates")}
    values, unpriced = {}, 0
    for row in store.rows("SELECT * FROM usage_events WHERE created>=? AND created<?", (start,end)):
        rate, tokens = rates.get(row["model"]), json.loads(row["tokens"])
        if rate and row["provider"] != "chatgpt":
            value = sum(tokens.get(k, 0)*rate[r] for k,r in (
                ("input_tokens","input"),("output_tokens","output"),("cache_read_input_tokens","cache_read"),
                ("cache_creation_input_tokens","cache_write"))) / 1000000
            values[row["model"]] = values.get(row["model"], 0) + value
        else:
            unpriced += 1
    invoices = []
    for row in store.rows("SELECT * FROM usage_invoices WHERE month=?", (month,)):
        estimate = values.get(row["model"], 0)
        invoices.append({**row, "estimated_usd": estimate, "difference_usd": row["amount"] - estimate})
    budget = preferences(store)
    spent = sum(values.values())
    return {"month": month, "estimated_usd": spent, "unpriced_requests": unpriced, "invoices": invoices,
            "budget": budget, "exceeded": bool(budget["monthly_usd"] and spent >= budget["monthly_usd"])}


def enforce_budget(store):
    info = monthly(store)
    if info["exceeded"] and info["budget"]["mode"] == "stop":
        raise ValueError("AiMate monthly estimated budget reached. Review Usage & billing to change your budget.")


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
            "rates": list(rates.values()), "monthly": monthly(store),
            "bill_comparisons": [item for row in store.rows("SELECT DISTINCT month FROM usage_invoices ORDER BY month DESC LIMIT 24")
                                 for item in monthly(store,row["month"])["invoices"]],
            "calls": store.rows("SELECT origin,status,count(*) AS count FROM usage_calls WHERE created>=? GROUP BY origin,status", (start,)),
            "coverage": "Chat, routing and billable connection tests are tracked. Interrupted/failed calls without provider usage appear separately; their tokens and cost are unknown. Estimates use your current rates. Monthly budgets use UTC and check before each request; they cannot cap a request already in progress or unknown/unpriced spend. Invoice amounts are manually entered for comparison, not fetched from AWS. ChatGPT plan limits and organization spend remain with your provider."}


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
