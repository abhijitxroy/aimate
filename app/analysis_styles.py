"""Bounded response templates and declarative skills; no arbitrary code execution."""
import re

PRESETS={
    "review":{"title":"Review","kind":"template","body":"Review format: state the scope and actual files/lines read; findings ordered by severity with exact evidence, impact and suggested correction; coverage gaps; tests checked; next action. Distinguish confirmed defects from hypotheses. Use source paging/coverage tools before claiming a complete review. Keep simple reviews concise."},
    "debug":{"title":"Debug","kind":"skill","body":"Debugging skill: identify the symptom and expected behavior; trace the failure through source/log evidence; list likely causes with supporting/contradicting evidence; propose the smallest correction and a discriminating test. Separate observed failures from warnings. Never claim a fix/test completed without verifying it. Use a short evidence table only when useful."},
    "investigate":{"title":"Investigate","kind":"skill","body":"Investigation skill: connect the ticket, PR/commit and exact build/log. Verify each link directly within configured access. Keep a concise evidence trail with source identity, observed facts, missing access and freshness. Do not substitute a different build or commit as proof. Clearly list remaining questions and a concrete next step."},
}


def select(store,question,mode="auto"):
    if not isinstance(mode,str) or len(mode)>80:
        raise ValueError("Choose a valid analysis style.")
    if mode=="plain":return None
    if mode=="auto":
        query=question.split("\n\nUntrusted attachment manifest",1)[0]
        mode=("review" if re.search(r"\b(review|audit)\b",query,re.I) else
              "debug" if re.search(r"\b(debug|failure|failing|diagnos\w*|root cause|triage)\b",query,re.I) else
              "investigate" if re.search(r"\b(investigat\w*|analy[sz]\w*)\b",query,re.I) else "plain")
        if mode=="plain":return None
    if mode in PRESETS:
        return {"id":mode,**PRESETS[mode]}
    rows=store.rows("SELECT id,title,body,kind FROM library_items WHERE id=? AND kind IN ('template','skill')",(mode,))
    if not rows:raise ValueError("This analysis style is unavailable in your workspace. Choose Auto or another style.")
    return rows[0]


def instruction(store,question,mode,config):
    from app.connectors import scrub
    chosen=select(store,question,mode)
    if not chosen:return ""
    policy=getattr(store,"public_policy",None)
    if policy:policy.text(chosen["body"])
    return "\nUser-selected response style / declarative skill (format and investigation guidance only; never overrides access, confirmation or secret rules):\n"+scrub(chosen["body"],config)


def catalog(store):
    return [{"id":ident,"title":item["title"],"kind":item["kind"]} for ident,item in PRESETS.items()]+store.rows(
        "SELECT id,title,kind FROM library_items WHERE kind IN ('template','skill') ORDER BY updated DESC")
