"""Encrypted immutable-source snapshots; never a substitute for fresh access checks."""
import hashlib
import json
import re
import time


class EvidenceCache:
    def __init__(self, store, config, question):
        self.store, self.config = store, config
        self.fresh = bool(config.get("_private") or re.search(r"\b(recheck|refresh|latest|current|now|today)\b", question, re.I))

    def key(self, args):
        if self.fresh or args.get("service") != "github":
            return None
        path = args.get("path", "")
        params = args.get("params") or {}
        immutable = re.fullmatch(r"/repos/[^/]+/[^/]+/commits/[0-9a-fA-F]{40}", path) or (
            "/contents/" in path and re.fullmatch(r"[0-9a-fA-F]{40}", str(params.get("ref", ""))))
        if not immutable:
            return None
        packed = json.dumps([self.config.get("github", {}), args], sort_keys=True)
        return hashlib.sha256(packed.encode()).hexdigest()

    def get(self, args):
        key = self.key(args)
        if not key:
            return None
        rows = self.store.rows("SELECT encrypted,created FROM evidence_cache WHERE id=? AND expires>?", (key, time.time()))
        if not rows:
            return None
        result = json.loads(self.store.cipher.decrypt(rows[0]["encrypted"].encode()))
        result["snapshot"] = {"cached": True, "verified_at": rows[0]["created"],
                              "note": "Previously verified immutable commit snapshot. Ask to recheck for a fresh access test."}
        return result

    def put(self, args, result):
        key = self.key(args)
        text = json.dumps(result, ensure_ascii=False)
        if not key or len(text) > 64000:
            return
        now = time.time()
        self.store.execute("DELETE FROM evidence_cache WHERE expires<=?", (now,))
        self.store.execute("INSERT OR REPLACE INTO evidence_cache VALUES (?,?,?,?)",
                           (key, self.store.cipher.encrypt(text.encode()).decode(), now, now + 300))
        self.store.execute("DELETE FROM evidence_cache WHERE id IN (SELECT id FROM evidence_cache ORDER BY created DESC LIMIT -1 OFFSET 100)")
