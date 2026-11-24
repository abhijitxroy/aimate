"""Large-source review coverage, paging, stable evidence and scope boundaries."""
import asyncio
import base64
import json
import unittest
import tempfile
from types import SimpleNamespace

import httpx

from app.connectors import Services
from app.review import ReviewReader, read
from app.agent import run_turn
from app.store import Store

HEAD, BASE = "a" * 40, "b" * 40


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    def make_reader(self, text, changed=1):
        self.calls = []
        self.changed = changed
        self.head = HEAD
        self.merge_base = BASE
        def remote(request):
            self.calls.append(request)
            if request.url.path.endswith("/files"):
                page = int(request.url.params["page"])
                size = int(request.url.params["per_page"])
                rows = [{"filename": f"file-{i}.py", "status": "modified"} for i in range(changed)]
                return httpx.Response(200, json=rows[(page - 1) * size:page * size])
            if "/pulls/" in request.url.path:
                return httpx.Response(200, json={"head": {"sha": self.head}, "base": {"sha": BASE},
                                                "changed_files": self.changed})
            if "/compare/" in request.url.path:
                return httpx.Response(200, json={"merge_base_commit": {"sha": self.merge_base}})
            return httpx.Response(200, json={"type": "file", "encoding": "base64", "sha": "c" * 40,
                                            "content": base64.b64encode(text.encode()).decode()})
        services = Services({"github": {"url": "https://api.github.com", "repos": ["team/repo"],
                                         "token": "synthetic"}}, httpx.MockTransport(remote))
        return ReviewReader(services)

    async def read_all(self, reader, path="file-0.py", commit=HEAD):
        args = {"repo": "team/repo", "path": path, "ref": commit}
        parts = []
        while True:
            result = await reader.file(args)
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 20000)
            data = result["data"]
            parts.append(data["text"])
            if data["complete"]:
                break
            args.update(start_line=data["next_line"], start_column=data["next_column"])
        return "".join(parts)

    async def test_large_multiline_unicode_file_has_no_omitted_ranges(self):
        text = "".join(f"line {i}: café 🚀\n" for i in range(6000))
        reader = self.make_reader(text)
        self.assertEqual(await self.read_all(reader), text)
        self.assertTrue(reader.coverage()["data"]["files"][0]["read_complete"])
        self.assertEqual(len(self.calls), 1, "Pinned source should be fetched only once.")
        self.assertEqual(self.calls[0].url.params["ref"], HEAD)

    async def test_long_single_line_and_json_escaping_are_continued_exactly(self):
        text = ('"\\\t' * 10000) + "\nlast line"
        reader = self.make_reader(text)
        self.assertEqual(await self.read_all(reader), text)

    async def test_tail_read_does_not_claim_complete_and_overlap_is_not_double_counted(self):
        reader = self.make_reader("first\nsecond\nthird\n")
        args = {"repo": "team/repo", "path": "file-0.py", "ref": HEAD, "start_line": 3}
        result = await reader.file(args)
        self.assertTrue(result["data"]["end_of_file"])
        self.assertFalse(result["data"]["complete"])
        self.assertEqual(result["data"]["next_line"], 1)
        self.assertFalse(result["data"]["read_complete"])
        await reader.file(args)
        self.assertEqual(reader.coverage()["data"]["files"][0]["read_characters"], 6)
        await self.read_all(reader)
        self.assertTrue(reader.coverage()["data"]["files"][0]["read_complete"])

    async def test_manifest_requires_all_pages_and_both_versions(self):
        reader = self.make_reader("content\n", changed=6)
        first = await reader.manifest({"repo": "team/repo", "pull": 7})
        self.assertEqual(first["data"]["next_page"], 2)
        self.assertFalse(first["data"]["manifest_complete"])
        await reader.manifest({"repo": "team/repo", "pull": 7, "page": 2})
        self.assertTrue(reader.manifest_complete())
        self.assertEqual(reader.coverage()["data"]["missing_source_count"], 12)
        for i in range(6):
            for commit in (HEAD, BASE):
                await self.read_all(reader, f"file-{i}.py", commit)
        self.assertTrue(reader.coverage()["data"]["complete_pr_read"])

    async def test_source_scope_path_ref_and_offsets_are_validated_before_network(self):
        reader = self.make_reader("content")
        valid = {"repo": "team/repo", "path": "code.py", "ref": HEAD}
        for changes in ({"repo": "other/repo"}, {"path": "../private"}, {"path": "/abs"},
                        {"ref": "main"}, {"start_line": True}, {"start_line": 0},
                        {"end_line": 500}, {"start_column": -1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                await reader.file({**valid, **changes})
        self.assertEqual(self.calls, [])

    async def test_empty_file_and_provider_api_limit_remain_explicit(self):
        reader = self.make_reader("", changed=3001)
        result = await reader.file({"repo": "team/repo", "path": "empty.py", "ref": HEAD})
        self.assertTrue(result["data"]["read_complete"])
        page = await reader.manifest({"repo": "team/repo", "pull": 7})
        self.assertTrue(page["data"]["api_limit_reached"])
        self.assertFalse(page["data"]["manifest_complete"])

    async def test_agent_integrates_manifest_file_pages_and_coverage(self):
        reader = self.make_reader("reviewable code\n")
        class Block:
            def __init__(self, **value):
                self.value = value
            def model_dump(self, **kwargs):
                return self.value
        class AI:
            def __init__(self):
                self.messages, self.stage = self, 0
            def stream(self, **kwargs):
                stage = self.stage
                self.stage += 1
                class Stream:
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        pass
                    @property
                    def text_stream(self):
                        async def text():
                            if stage == 3:
                                yield "Both source versions read."
                        return text()
                    async def get_final_message(self):
                        if stage == 0:
                            blocks = [Block(type="tool_use", id="manifest", name="read_pr_manifest",
                                            input={"repo": "team/repo", "pull": 7})]
                        elif stage == 1:
                            blocks = [Block(type="tool_use", id=commit, name="read_github_file",
                                            input={"repo": "team/repo", "path": "file-0.py", "ref": commit})
                                      for commit in (HEAD, BASE)]
                        elif stage == 2:
                            blocks = [Block(type="tool_use", id="coverage", name="review_coverage", input={})]
                        else:
                            blocks = [Block(type="text", text="Both source versions read.")]
                        return SimpleNamespace(content=blocks, model="fixture",
                                               usage=SimpleNamespace(input_tokens=10, output_tokens=1))
                return Stream()
            async def close(self):
                pass
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            config = dict(reader.services.config)
            config.update(ai={"provider": "anthropic", "model": "fixture", "api_key": "synthetic"},
                          allow_writes=False)
            store.save_config(config)
            cid = store.new_conversation()
            ai = AI()
            try:
                events = [event async for event in run_turn(
                    store, cid, "Review this PR", model_mode="standard",
                    client_factory=lambda cfg: ai, services_factory=lambda cfg: reader.services)]
                self.assertTrue(all(e["ok"] for e in events if e["event"] == "tool_done"))
                self.assertEqual(events[-1]["event"], "done")
                self.assertTrue(reader.services._review_reader.coverage()["data"]["complete_pr_read"])
                saved = json.loads(store.rows("SELECT messages FROM turns")[0]["messages"])
                coverage = [json.loads(block["content"])["data"]
                            for message in saved if isinstance(message["content"], list)
                            for block in message["content"]
                            if block.get("type") == "tool_result" and block.get("tool_use_id") == "coverage"]
                self.assertTrue(coverage[0]["complete_pr_read"])
            finally:
                store.db.close()

    async def test_encrypted_progress_resumes_after_restart_but_requires_fresh_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            reader = self.make_reader("review code\n")
            cid = store.new_conversation()
            cfg = reader.services.config
            store.save_config(cfg)
            try:
                await read(reader.services, "read_pr_manifest", {"repo": "team/repo", "pull": 7}, store, cid)
                for commit in (HEAD, BASE):
                    await read(reader.services, "read_github_file",
                               {"repo": "team/repo", "path": "file-0.py", "ref": commit}, store, cid)
                encrypted = store.rows("SELECT encrypted FROM review_sessions")[0]["encrypted"]
                self.assertNotIn("file-0.py", encrypted)
                self.assertNotIn("review code", store.cipher.decrypt(encrypted.encode()).decode())
                store.db.close()
                store = Store(directory)
                resumed = self.make_reader("review code\n").services
                result = await read(resumed, "review_coverage", {}, store, cid)
                self.assertFalse(result["data"]["complete_pr_read"])
                self.assertEqual(result["data"]["missing_source_count"], 0)
                await read(resumed, "read_pr_manifest", {"repo": "team/repo", "pull": 7}, store, cid)
                self.assertTrue((await read(resumed, "review_coverage", {}, store, cid))["data"]["complete_pr_read"])
                resumed.config["github"]["token"] = "different-credential"
                self.assertEqual((await read(resumed, "review_coverage", {}, store, cid))["data"]["source_count"], 0)
            finally:
                store.db.close()

    async def test_changed_head_resets_prior_coverage(self):
        reader = self.make_reader("review code\n")
        await reader.manifest({"repo": "team/repo", "pull": 7})
        await self.read_all(reader)
        self.head = "d" * 40
        await reader.manifest({"repo": "team/repo", "pull": 7})
        self.assertEqual(reader.coverage()["data"]["source_count"], 0)
        self.assertEqual(reader.coverage()["data"]["missing_source_count"], 2)

    async def test_legacy_contents_read_marks_truncation(self):
        reader = self.make_reader("x" * 50000)
        result = await reader.services.read("github", "/repos/team/repo/contents/code.py")
        self.assertTrue(result["data"]["truncated"])
        self.assertEqual(result["data"]["total_characters"], 50000)
        self.assertIn("read_github_file", result["data"]["note"])

    async def test_manifest_uses_merge_base_not_unrelated_target_branch_changes(self):
        reader = self.make_reader("review code\n")
        self.merge_base = "e" * 40
        result = await reader.manifest({"repo": "team/repo", "pull": 7})
        self.assertEqual(result["data"]["base_sha"], "e" * 40)
        self.assertEqual(result["data"]["target_base_sha"], BASE)
        self.assertEqual(result["data"]["files"][0]["sources"][1]["ref"], "e" * 40)

    async def test_independent_review_reset_clears_prior_reads(self):
        reader = self.make_reader("review code\n")
        await reader.manifest({"repo": "team/repo", "pull": 7})
        await self.read_all(reader)
        await reader.manifest({"repo": "team/repo", "pull": 7, "reset": True})
        self.assertEqual(reader.coverage()["data"]["source_count"], 0)
        with self.assertRaises(ValueError):
            await reader.manifest({"repo": "team/repo", "pull": 7, "page": 2, "reset": True})
