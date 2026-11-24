"""Isolated browser-test server: synthetic models, no service credentials."""
import argparse
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
directory = tempfile.TemporaryDirectory()
os.environ.update(APP_DATA_DIR=directory.name, APP_PASSWORD="browser-regression-password",
                  AIMATE_ENV="development", AIMATE_DEV_LOGIN="0")
os.environ.pop("AIMATE_PUBLIC_URL", None)

from app.main import create_app, app as import_app
from app.store import Store


class Block:
    def model_dump(self, **kwargs):
        return {"type": "text", "text": "Analysis model answered."}


class Stream:
    def __init__(self, model):
        self.model = model

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    @property
    def text_stream(self):
        async def chunks():
            yield "Analysis model answered."
        return chunks()

    async def get_final_message(self):
        return SimpleNamespace(content=[Block()], model=self.model,
                               usage=SimpleNamespace(input_tokens=60, output_tokens=8))


class AI:
    def __init__(self, config):
        self.messages = self

    async def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"route":"analysis"}')],
                               usage=SimpleNamespace(input_tokens=20, output_tokens=6))

    def stream(self, **kwargs):
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
    try:
        uvicorn.run(create_app(store, client_factory=AI), host="127.0.0.1", port=args.port,
                    log_level="warning")
    finally:
        store.db.close()
        import_app.state.store.db.close()
        directory.cleanup()
