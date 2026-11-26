"""Optional deterministic saved-reference ranking; no embeddings or network calls."""
import os
import re

STOP = set("""a an the is are was were be been to of in on at by as if or and for
what when where which please could would should this that with from your have
tell about more again check recheck continue same explain why you can how does
will any all use work need me my it our we do did give find show look up search
review investigate analysis debug""".split())
ISSUE = re.compile(r"\b[a-z][a-z0-9_]{1,24}-[1-9]\d{0,9}\b", re.I)
PR = re.compile(r"(?:\bpr\s*#?\s*|\bpull request\s*#?\s*|/pull/)([1-9]\d{0,9})\b", re.I)
SHA = re.compile(r"\b[0-9a-f]{40}\b", re.I)


def enabled():
    return os.environ.get("AIMATE_RETRIEVAL_RANKING_ENABLED") != "0"


def identifiers(value):
    value = value.casefold()
    return set(ISSUE.findall(value)) | {"pr#" + number for number in PR.findall(value)} | set(SHA.findall(value))


def terms(query):
    query = re.sub(r"\bpr([1-9]\d*)\b", r"PR \1", query, flags=re.I)
    return list(dict.fromkeys(word for word in re.findall(r"[^\W_]+", query.casefold())
                             if word not in STOP))[:12]


def score(query, text, title=""):
    wanted = terms(query)
    ids = identifiers(query)
    body_words = set(re.findall(r"[^\W_]+", text.casefold()))
    title_words = set(re.findall(r"[^\W_]+", title.casefold()))
    matches = ids & identifiers(title + "\n" + text)
    # Identifiers dominate a bounded set of generic words, regardless of recency.
    value = len(matches) * 100
    for word in wanted:
        exact = word in body_words or word in title_words
        prefix = not exact and len(word) >= 4 and not word.isdigit() and any(
            candidate.startswith(word) for candidate in body_words | title_words)
        value += 3 * int(exact) + int(prefix) + 2 * int(word in title_words)
    if wanted and all(word in body_words | title_words for word in wanted):
        value += 8
    return value


def excerpt(text, query, limit=1200):
    """Show a match in the middle of long records, keeping full-text paging available."""
    positions = []
    for value in sorted(identifiers(query), key=len, reverse=True):
        if value.startswith("pr#"):
            positions.extend(match.start() for match in PR.finditer(text) if "pr#" + match.group(1) == value)
        else:
            match = re.search(re.escape(value), text, re.I)
            if match:
                positions.append(match.start())
    if not positions:
        for value in terms(query):
            match = re.search(r"\b" + re.escape(value), text, re.I)
            if match:
                positions.append(match.start())
    center = min(positions) if positions else 0
    start = max(0, center - limit // 4)
    end = min(len(text), start + limit)
    return text[start:end], start, end


def records(query, rows, limit=6, text_limit=1200):
    ranked = [(score(query, row["value"], row["key"]), row) for row in rows]
    ranked.sort(key=lambda item: (-item[0], -item[1]["updated"], item[1]["id"]))
    result = []
    for value, row in ranked:
        if not value:
            continue
        text, start, end = excerpt(row["value"], query, text_limit)
        result.append({**row, "value": text, "truncated": start > 0 or end < len(row["value"]),
                       "excerpt_start": start, "excerpt_end": end,
                       "match_basis": "exact identifier" if identifiers(query) & identifiers(row["key"] + "\n" + row["value"]) else "keywords"})
        if len(result) == limit:
            break
    return result


def chats(store, cid, query, limit=8, scope_sql=None, scope_args=(), include_own=False):
    words = terms(query)
    if not words:
        return []
    # Numeric identifiers are exact FTS tokens, never prefix matches (8521 != 85210).
    match = " OR ".join('"' + word + '"' + ("" if word.isdigit() or len(word) < 4 else "*") for word in words)
    own = "" if include_own else " AND m.conversation<>?"
    args = [match] + ([] if include_own else [cid])
    scope = (" AND (" + scope_sql + ")") if scope_sql else ""
    args.extend(scope_args)
    # Rank a bounded shortlist across old and recent turns, not just the latest chats.
    sql = (
        "SELECT m.conversation AS conversation_id,m.turn,c.title,t.created AS recorded,"
        "m.content FROM memory_index m JOIN conversations c ON c.id=m.conversation "
        "JOIN turns t ON t.id=m.turn LEFT JOIN conversation_locations l ON l.conversation=c.id "
        "WHERE memory_index MATCH ?" + own + scope + " ORDER BY rank LIMIT 80")
    exact = []
    for ident in sorted(identifiers(query)):
        values = terms(ident.replace("pr#", ""))
        exact.append('"' + " ".join(values) + '"')
    primary = store.rows(sql, tuple([" OR ".join(exact), *args[1:]])) if exact else []
    general = store.rows(sql, tuple(args))
    seen = set()
    rows = []
    for row in primary + general:
        if row["turn"] not in seen:
            rows.append(row)
            seen.add(row["turn"])
        if len(rows) == 80:
            break
    ranked = [(score(query, row["content"], row["title"]), row) for row in rows]
    ranked.sort(key=lambda item: (-item[0], -item[1]["recorded"], item[1]["turn"]))
    result = []
    for value, row in ranked:
        if not value:
            continue
        text, start, end = excerpt(row["content"], query)
        result.append({key: item for key, item in row.items() if key != "content"} |
                      {"excerpt": text, "excerpt_start": start, "excerpt_end": end,
                       "truncated": start > 0 or end < len(row["content"])})
        if len(result) == limit:
            break
    return result
