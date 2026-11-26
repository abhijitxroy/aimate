"""Pinned encrypted knowledge, full paging, source revocation and HTTP ownership."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.agent import tools_for
from app.knowledge_index import Index
from app.local_evidence import KEY
from test_app import Store, create_app, fixture_config


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "repo"
        self.root.mkdir()
        self.store = Store(Path(self.directory.name) / "data")
        self.config = {**fixture_config(), KEY: [{"name": "project", "path": str(self.root)}],
                       "_role": "admin", "_local_access": True}
        self.store.save_config(self.config)
        self.git("init")
        self.git("config", "user.email", "fixture@example.test")
        self.git("config", "user.name", "Fixture")
        self.text = "---\ntitle: GPU Detection\naliases: [device absent, missing accelerator]\nstatus: active\ntags: [gpu, ci]\nupdated: 2026-09-15\n---\n\nGPU evidence\n" + "condition and evidence " * 300
        (self.root / "guide.md").write_text(self.text, encoding="utf-8")
        self.git("add", "guide.md")
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "fixture")
        self.index = Index(self.store, self.config)

    def tearDown(self):
        self.store.db.close()
        self.directory.cleanup()

    def git(self, *args):
        result = subprocess.run(["git", "-c", "core.hooksPath=", "-C", str(self.root), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")})
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return result.stdout.decode().strip()

    def prepare(self):
        return self.index.index({"source": "project", "paths": ["guide.md"]})

    def test_encrypted_pinned_import_alias_search_full_paging_and_gap_detection(self):
        result = self.prepare()
        self.assertEqual(result["commit"], self.git("rev-parse", "HEAD"))
        self.assertNotIn(b"GPU evidence", self.index.path().read_bytes())
        row = self.index.read("search_project_knowledge", {"query": "missing accelerator"})["matches"][0]
        self.assertEqual(row["title"], "GPU Detection")
        last = self.index.read("read_project_knowledge", {"id": row["id"], "start": 4000})["data"]
        self.assertTrue(last["end_reached"])
        self.assertFalse(last["complete"])
        first = self.index.read("read_project_knowledge", {"id": row["id"]})["data"]
        self.assertTrue(first["complete"])
        self.assertEqual(first["text"] + last["text"], self.text)
        self.assertFalse(first["source_changed"])
        self.assertIn("not AiMate validation", first["note"])

    def test_uncommitted_changes_not_imported_and_reindex_never_changes_old_id_to_new_commit(self):
        self.prepare()
        old = self.index.load()[0]["id"]
        (self.root / "guide.md").write_text("Uncommitted new content", encoding="utf-8")
        self.prepare()
        self.assertEqual(self.index.load()[0]["text"], self.text)
        self.git("add", "guide.md")
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "changed fixture")
        self.assertTrue(self.index.read("read_project_knowledge", {"id": old})["data"]["source_changed"])
        self.prepare()
        self.assertNotEqual(self.index.load()[0]["id"], old)
        with self.assertRaises(ValueError):
            self.index.read("read_project_knowledge", {"id": old})

    def test_path_limits_atomic_failure_and_source_revocation(self):
        self.prepare()
        before = self.index.path().read_bytes()
        for paths in (["../guide.md"], [".git/config"], ["guide.md", "missing.md"], [{}], ["guide.md"] * 2):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.index.index({"source": "project", "paths": paths})
            self.assertEqual(before, self.index.path().read_bytes())
        self.store.save_config({**self.config, KEY: []})
        with self.assertRaises(ValueError):
            self.index.load()

    def test_retired_records_excluded_and_credentials_redacted_before_persistence(self):
        secret = self.config["github"]["token"]
        (self.root / "guide.md").write_text("---\ntitle: Retired note\nstatus: retired\n---\nGPU " + secret, encoding="utf-8")
        self.git("add", "guide.md")
        self.git("-c", "commit.gpgsign=false", "commit", "-m", "retired")
        self.prepare()
        self.assertEqual(self.index.read("search_project_knowledge", {"query": "GPU"})["matches"], [])
        self.assertNotIn(secret, json.dumps(self.index.load()))
        self.assertTrue(self.index.load()[0]["redacted"])

    def test_roles_private_disabled_and_other_account_have_no_access_to_owner_index(self):
        self.prepare()
        for changed in ({"_role": "viewer"}, {"_role": "developer"}, {"_local_access": False}, {"_private": True}):
            config = {**self.config, **changed}
            self.assertNotIn("read_project_knowledge", {tool["name"] for tool in tools_for(config)})
            with self.assertRaises(ValueError):
                Index(self.store, config).load()
        with patch.dict(os.environ, {"AIMATE_KNOWLEDGE_INDEX_ENABLED": "0"}):
            self.assertNotIn("search_project_knowledge", {tool["name"] for tool in tools_for(self.config)})
            with self.assertRaises(ValueError):
                self.index.load()
        second = Store(Path(self.directory.name) / "other-data")
        try:
            second.save_config(self.config)
            self.assertEqual(Index(second, self.config).load(), [])
        finally:
            second.db.close()

    def test_http_csrf_owner_guard_and_document_reader(self):
        app = create_app(self.store)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/knowledge-index").status_code, 401)
            csrf = client.post("/api/login", json={"password": self.store.password}).json()["csrf"]
            body = {"source": "project", "paths": ["guide.md"]}
            self.assertEqual(client.post("/api/knowledge-index", json=body).status_code, 403)
            result = client.post("/api/knowledge-index", json=body, headers={"x-csrf-token": csrf})
            self.assertEqual(result.status_code, 200)
            rows = client.get("/api/knowledge-index").json()["entries"]
            self.assertNotIn("text", rows[0])
            document = client.get("/api/knowledge-index/" + rows[0]["id"]).json()
            self.assertIn("GPU evidence", document["data"]["text"])
        with TestClient(app, client=("192.0.2.10", 1000)) as remote:
            remote.post("/api/login", json={"password": self.store.password})
            self.assertEqual(remote.get("/api/knowledge-index").status_code, 403)

    def test_invalid_storage_and_tool_arguments_preserve_original_file(self):
        self.prepare()
        for name, args in (("unknown", {}), ("read_project_knowledge", []),
                           ("search_project_knowledge", {"query": "GPU", "extra": True})):
            with self.assertRaises(ValueError):
                self.index.read(name, args)
        for raw in (b"damaged", self.store.cipher.encrypt(b'[{}]')):
            self.index.path().write_bytes(raw)
            with self.assertRaises(ValueError):
                self.index.load()
            self.assertEqual(self.index.path().read_bytes(), raw)

    def test_reopened_store_retains_encrypted_index_without_reimport(self):
        self.prepare()
        directory = self.store.directory
        self.store.db.close()
        self.store = Store(directory)
        restored = Index(self.store, self.config)
        self.assertEqual(restored.read("search_project_knowledge", {"query": "missing accelerator"})["matches"][0]["title"],
                         "GPU Detection")
