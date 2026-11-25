"""Set a saved chat's initial identity once; preserve explicit user choices."""
import os
import re

TOPICS = (
    (r"\b(security|password|vault|privacy|auth|login|pat)\b","🔐"),
    (r"\b(debug|bug|failure|failed|error|fix|troubleshoot)\b","🐛"),
    (r"\b(jenkins|build|pipeline|deployment|logs?)\b","⚙️"),
    (r"\b(pull requests?|pr|github|git|repos?|commits?|branches|merge)\b","📦"),
    (r"\b(jira|issues?|tickets?|tasks?|todo)\b","📋"),
    (r"\b(ai|aimate|claude|bedrock|chatgpt|models?|assistant|your name)\b","🤖"),
    (r"\b(usage|billing|cost|budget|spend|tokens?)\b","💰"),
    (r"\b(architecture|design|flow|diagram|plan|roadmap)\b","🧩"),
    (r"\b(test|tests|testing|validation|coverage)\b","🧪"),
    (r"\b(code|coding|python|javascript|api|implement|function)\b","💻"),
    (r"\b(data|database|sql|metrics|report|analysis)\b","📊"),
    (r"\b(readme|docs?|documentation|notes|diary|knowledge|explain)\b","📖"),
    (r"\b(ui|theme|style|colou?r|layout|page|website)\b","🎨"),
    (r"\b(performance|speed|latency)\b","⚡"),
    (r"\b(health|doctor|medical|hospital)\b","🏥"),
    (r"\b(school|class|study|education)\b","🎓"),
    (r"\b(office|meeting|work)\b","💼"),
    (r"\b(food|cook|recipe|meal)\b","🍽️"),
    (r"\b(travel|flight|plane|trip)\b","✈️"),
)


def topic_icon(text):
    return next((icon for pattern,icon in TOPICS if re.search(pattern,text,re.I)),"💬")


def initialize(store,cid,messages):
    if store.db.execute("SELECT COUNT(*) FROM turns WHERE conversation=?",(cid,)).fetchone()[0] != 1:
        return
    question=next((m.get("content") for m in messages if m.get("role")=="user" and isinstance(m.get("content"),str)),"")
    if not question.strip():
        return
    store.db.execute("UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",(question.strip()[:100],cid))
    if os.environ.get("AIMATE_INITIAL_IDENTITY_ENABLED") != "0":
        store.db.execute("INSERT OR IGNORE INTO conversation_icons VALUES (?,?)",(cid,topic_icon(question)))
