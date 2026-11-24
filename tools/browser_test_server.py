"""Isolated browser-test server: synthetic models, no service credentials."""
import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
directory = tempfile.TemporaryDirectory()
os.environ.update(APP_DATA_DIR=directory.name, APP_PASSWORD="browser-regression-password",
                  AIMATE_ENV="development", AIMATE_DEV_LOGIN="0", AIMATE_DEMO="0",
                  AIMATE_PUBLIC_SHOWCASE="0")
os.environ.pop("AIMATE_PUBLIC_URL", None)
os.environ.pop("APP_PUBLIC_URL", None)

from app.main import create_app, app as import_app
from app.store import Store


class Block:
    def __init__(self, text):
        self.text = text
    def model_dump(self, **kwargs):
        return {"type": "text", "text": self.text}


class Stream:
    def __init__(self, model, text="Analysis model answered.", slow=False):
        self.model, self.text, self.slow = model, text, slow

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    @property
    def text_stream(self):
        async def chunks():
            if self.slow:
                for _ in range(30):
                    await asyncio.sleep(.1)
            yield self.text
        return chunks()

    async def get_final_message(self):
        return SimpleNamespace(content=[Block(self.text)], model=self.model,
                               usage=SimpleNamespace(input_tokens=60, output_tokens=8))


class AI:
    def __init__(self, config):
        self.messages = self

    async def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"route":"analysis"}')],
                               usage=SimpleNamespace(input_tokens=20, output_tokens=6))

    def stream(self, **kwargs):
        question=str(kwargs["messages"][-1]["content"])
        if question.startswith("Parallel "):
            return Stream(kwargs["model"],"Reply: "+question,slow=True)
        if "Which ticket" in str(kwargs["messages"][-1]["content"]):
            return Stream(kwargs["model"], "DEMO-8437 · PR #1257" if "DEMO-8437" in kwargs["system"]
                          else "Missing saved context.")
        return Stream(kwargs["model"])

    async def close(self):
        pass


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    store = Store(directory.name)
    store.save_config({"allow_writes": False,
                       "ai": {"provider": "anthropic", "model": "standard-fixture",
                              "analysis_model": "analysis-fixture", "api_key": "synthetic-fixture"},
                       "github": {}, "jira": {}, "jenkins": {}})
    store.execute("INSERT INTO todos VALUES (?,?,0,?,?)",
                  ("long-task", "Long task\n" + "\n".join(f"Step {i}: preserve multiline details." for i in range(20)), 1, 1))
    legacy = store.new_conversation("Old continuity reference")
    store.save_turn(legacy, [{"role": "user", "content": "Investigate DEMO-8437 and PR #1257."}])
    for index in range(18):
        store.save_turn(legacy, [{"role": "user", "content": f"Follow-up detail {index}"}])
    try:
        uvicorn.run(create_app(store, client_factory=AI), host="127.0.0.1", port=args.port,
                    log_level="warning")
    finally:
        store.db.close()
        import_app.state.store.db.close()
        directory.cleanup()
