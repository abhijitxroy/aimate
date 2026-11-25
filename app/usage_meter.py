"""Account for model requests, including interrupted calls, without storing prompts."""
import time
import secrets
from app.usage import record, enforce_budget


class Call:
    def __init__(self, store, config, model, origin):
        self.store, self.config, self.model, self.origin = store, config, model, origin
        self.ident = secrets.token_hex(16)
        self.reported = False

    def __enter__(self):
        if self.config.get("ai",{}).get("provider")!="ollama":
            enforce_budget(self.store)
        self.store.execute("INSERT INTO usage_calls VALUES (?,?,?,?,?)",
                           (self.ident, time.time(), self.model, self.origin, "incomplete"))
        return self

    def complete(self, response):
        incoming = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
        if incoming is None:
            return
        incoming = incoming if isinstance(incoming, dict) else (
            incoming.model_dump() if hasattr(incoming, "model_dump") else vars(incoming))
        model = response.get("model") if isinstance(response, dict) else getattr(response, "model", None)
        record(self.store, self.config, model or self.model, incoming, self.origin)
        self.reported = True
        self.store.execute("UPDATE usage_calls SET status='reported' WHERE id=?", (self.ident,))

    def __exit__(self, kind, value, traceback):
        if kind and not self.reported:
            self.store.execute("UPDATE usage_calls SET status='failed / usage unavailable' WHERE id=?", (self.ident,))


class MeteredClient:
    def __init__(self, client, store, config, origin):
        self.client, self.store, self.config, self.origin = client, store, config, origin
        self.messages = self

    async def create(self, **args):
        with Call(self.store, self.config, args["model"], self.origin) as call:
            response = await self.client.messages.create(**args)
            call.complete(response)
            return response

    def stream(self, **args):
        return MeteredStream(self, args)

    async def close(self):
        await self.client.close()


class MeteredStream:
    def __init__(self, owner, args):
        self.owner, self.args = owner, args

    async def __aenter__(self):
        self.call = Call(self.owner.store, self.owner.config, self.args["model"], self.owner.origin)
        self.call.__enter__()
        try:
            self.context = self.owner.client.messages.stream(**self.args)
            self.stream = await self.context.__aenter__()
            return self
        except BaseException as exc:
            self.call.__exit__(type(exc), exc, exc.__traceback__)
            raise

    @property
    def text_stream(self):
        return self.stream.text_stream

    async def get_final_message(self):
        response = await self.stream.get_final_message()
        self.call.complete(response)
        return response

    async def __aexit__(self, kind, value, traceback):
        try:
            return await self.context.__aexit__(kind, value, traceback)
        finally:
            self.call.__exit__(kind, value, traceback)


async def responses(store, config, origin, source, connection, payload, **kwargs):
    with Call(store, config, payload["model"], origin) as call:
        async for event in source(connection, payload, **kwargs):
            if event["type"] == "response.completed":
                call.complete(event["response"])
            yield event
