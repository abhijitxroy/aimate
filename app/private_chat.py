"""Session-only transcripts: no disk history, search index, previews or action proposals."""
import copy
import json


class PrivateChat:
    def __init__(self, store, ident):
        self.store, self.ident, self.turns = store, ident, []
        self.sequence = 0
        self.documents = {}

    def __getattr__(self, name):
        return getattr(self.store, name)

    def config(self):
        return {**self.store.config(), "_private":True, "allow_writes":False}

    def history(self, cid):
        messages, size = [], 0
        for turn in reversed(self.turns[-10:]):
            chunk = copy.deepcopy(turn["messages"])
            length = len(json.dumps(chunk))
            if messages and size + length > 60000:
                break
            messages.insert(0,chunk)
            size += length
        return [m for chunk in messages for m in chunk]

    def save_turn(self, cid, messages, metadata=None):
        import time
        self.sequence += 1
        self.turns.append({"id":self.sequence,"messages":messages,"usage":metadata,"created":time.time()})
        self.turns = self.turns[-10:]

    def execute(self, sql, args=()):
        if sql.startswith("UPDATE conversations SET title"):
            return None
        return self.store.execute(sql,args)

    def rows(self, sql, args=()):
        if "actions" in sql or "conversation_references" in sql:
            return []
        return self.store.rows(sql,args)
