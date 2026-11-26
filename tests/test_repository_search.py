"""Pinned discovery/search, honest coverage, source budgets and permission checks."""
import base64
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.agent import tools_for
from app.connectors import Services
from app.repository_search import RepositorySearch, read

COMMIT = "a" * 40
SUBTREE = "b" * 40


class RepositorySearchTests(unittest.IsolatedAsyncioTestCase):
    def make(self, files, *, incomplete=False, failures=()):
        self.calls = []
        self.files = files
        self.incomplete = incomplete
        self.revoked = False
        def remote(request):
            self.calls.append(request)
            self.assertEqual(request.method, "GET")
            if request.url.path == "/repos/team/repo":
                return httpx.Response(200, json={"default_branch": "feature/work"})
            if request.url.path.endswith("/commits"):
                self.assertEqual(request.url.params["sha"], "feature/work")
                return httpx.Response(200, json=[{"sha": COMMIT}])
            if "/git/trees/" in request.url.path:
                if "recursive" not in request.url.params:
                    return httpx.Response(200, json={"tree": [{"type": "tree", "path": "src", "sha": SUBTREE}]})
                entries = [{"path": path[4:] if request.url.path.endswith(SUBTREE) else path,
                            "type": "blob", "mode": "100644", "size": len(text.encode())}
                           for path, text in files.items() if not request.url.path.endswith(SUBTREE) or path.startswith("src/")]
                return httpx.Response(200, json={"truncated": incomplete, "tree": entries})
            path = request.url.path.split("/contents/")[-1]
            self.assertEqual(request.url.params["ref"], COMMIT)
            if path in failures:
                return httpx.Response(404, json={"message": "synthetic-private-body"})
            return httpx.Response(200, json={"type": "file", "encoding": "base64",
                "content": base64.b64encode(files[path].encode()).decode()})
        config = {"github": {"url": "https://api.github.com", "repos": ["team/repo"], "token": "synthetic"}}
        services = Services(config, httpx.MockTransport(remote))
        def access():
            if self.revoked:raise ValueError("Access revoked")
        services.access_check = access
        return services, RepositorySearch(services)

    async def test_find_substring_glob_pin_and_cursor(self):
        _, reader = self.make({"src/retry.py": "retry", "src/retry_test.py": "", "README.md": ""})
        result = await reader.read("find_repository_files", {"repo": "team/repo", "path_pattern": "retry", "limit": 1})
        data = result["data"]
        self.assertEqual(data["commit"], COMMIT)
        self.assertEqual(data["matches"][0]["path"], "src/retry.py")
        self.assertEqual(data["next"], {"ref": COMMIT, "offset": 1})
        second = await reader.read("find_repository_files", {"repo": "team/repo", "path_pattern": "retry", **data["next"]})
        self.assertEqual(second["data"]["matches"][0]["path"], "src/retry_test.py")
        self.assertTrue(second["data"]["remaining_scope_complete"])
        self.assertFalse(second["data"]["full_scope_complete"])
        self.assertEqual(sum("/commits" in r.url.path for r in self.calls), 1)
        self.assertEqual(sum("/git/trees/" in r.url.path for r in self.calls), 1)
        narrowed = await reader.read("find_repository_files", {"repo": "team/repo", "ref": COMMIT,
            "directory": "src", "path_pattern": "*.py"})
        self.assertEqual(len(narrowed["data"]["matches"]), 2)
        self.assertTrue(narrowed["data"]["full_scope_complete"])

    async def test_content_pages_do_not_skip_matches_or_repeat_reads(self):
        _, reader = self.make({"src/a.py": "\n".join(f"retry line {i}" for i in range(45)), "src/b.py": "retry last"})
        args = {"repo": "team/repo", "query": "retry", "path_pattern": "*.py", "limit": 7}
        found = []
        for _ in range(10):
            result = await reader.read("search_repository_text", args)
            data = result["data"]
            self.assertLess(len(json.dumps(result)), 18000)
            found.extend((row["path"], row["line"]) for row in data["matches"])
            if not data["next"]:break
            args.update(data["next"])
        self.assertEqual(found, [("src/a.py", i) for i in range(1, 46)] + [("src/b.py", 1)])
        self.assertEqual(sum("/contents/" in r.url.path for r in self.calls), 2)
        self.assertTrue(data["remaining_scope_complete"])
        self.assertFalse(data["full_scope_complete"])

    async def test_literal_search_unicode_line_citations_and_excerpt_limits(self):
        _, reader = self.make({"src/a.py": "café\nretry\nRETRY\n"+("x"*1000)+"(retry|fail)"})
        result = await reader.read("search_repository_text", {"repo": "team/repo", "query": "(retry|fail)", "path_pattern": "*.py"})
        matches = result["data"]["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["line"], 4)
        self.assertIn("(retry|fail)", matches[0]["text"])
        self.assertTrue(matches[0]["excerpt_truncated"])
        self.assertIn("?ref="+COMMIT, matches[0]["url"])
        self.assertTrue(result["data"]["full_scope_complete"])
        upper = await reader.read("search_repository_text", {"repo": "team/repo", "ref": COMMIT,
            "query": "RETRY", "case_sensitive": True, "path_pattern": "*.py"})
        self.assertEqual([x["line"] for x in upper["data"]["matches"]], [3])

    async def test_incomplete_tree_is_not_complete_or_a_whole_repo_count(self):
        _, reader = self.make({"src/a.py": "retry"}, incomplete=True)
        result = await reader.read("search_repository_text", {"repo": "team/repo", "query": "retry", "path_pattern": "*"})
        self.assertFalse(result["data"]["tree_complete"])
        self.assertFalse(result["data"]["full_scope_complete"])
        self.assertIn("partial", result["data"]["gaps"][0]["reason"])

    async def test_errors_binary_and_oversized_files_are_explicit_gaps(self):
        _, reader = self.make({"a.py": "retry", "b.py": "\0binary", "c.py": "z"*1_400_001}, failures={"a.py"})
        result = await reader.read("search_repository_text", {"repo": "team/repo", "query": "retry", "path_pattern": "*"})
        self.assertEqual(len(result["data"]["gaps"]), 3)
        self.assertFalse(result["data"]["remaining_scope_complete"])
        self.assertNotIn("synthetic-private-body", json.dumps(result))
        self.assertFalse(any("/contents/c.py" in r.url.path for r in self.calls))

    async def test_automatic_search_excludes_credential_files(self):
        _, reader = self.make({".env": "retry", "gcp-creds.json": "retry", "secrets/key.txt": "retry", "src/a.py": "retry"})
        result = await reader.read("search_repository_text", {"repo": "team/repo", "query": "retry", "path_pattern": "*"})
        self.assertEqual(result["data"]["excluded_paths"], 3)
        self.assertEqual([x["path"] for x in result["data"]["matches"]], ["src/a.py"])
        self.assertEqual(sum("/contents/" in r.url.path for r in self.calls), 1)

    async def test_scope_validation_and_revocation_also_guard_cached_content(self):
        services, reader = self.make({"src/a.py": "retry"})
        for args in ({"repo": "other/repo"}, {"directory": "../src"}, {"offset": True},
                     {"ref": "../../main"}, {"limit": 0}, {"case_sensitive": "false"}, {"query": "x\n"},
                     {"unexpected": "value"}):
            params = {"repo": "team/repo", "query": "retry", "path_pattern": "*", **args}
            with self.assertRaises(ValueError):await reader.read("search_repository_text", params)
        self.assertEqual(self.calls, [])
        args = {"repo": "team/repo", "query": "retry", "path_pattern": "*"}
        await reader.read("search_repository_text", args)
        self.revoked = True
        with self.assertRaisesRegex(ValueError, "revoked"):
            await reader.read("search_repository_text", {**args, "ref": COMMIT})
        self.revoked = False
        services.config["github"]["repos"] = []
        with self.assertRaisesRegex(ValueError, "scope"):await reader.read("search_repository_text", args)

    async def test_public_policy_is_applied_to_decoded_and_cached_source(self):
        services, reader = self.make({"src/a.py": "internal-evidence"})
        class Policy:
            def text(self, value):
                if "internal-evidence" in value:raise ValueError("Blocked private content")
        args = {"repo": "team/repo", "query": "internal", "path_pattern": "*"}
        await reader.read("search_repository_text", args)
        services.public_policy = Policy()
        result = await reader.read("search_repository_text", {**args, "ref": COMMIT})
        self.assertEqual(result["data"]["matches"], [])
        self.assertIn("Blocked", result["data"]["gaps"][0]["reason"])

    async def test_disabled_tool_keeps_existing_read_and_private_tools(self):
        services, _ = self.make({"src/a.py": "retry"})
        with patch.dict(os.environ, {"AIMATE_REPOSITORY_SEARCH_ENABLED": "0"}):
            for config in ({}, {"_private": True}, {"_role": "viewer", "allow_writes": False}):
                names = {x["name"] for x in tools_for(config)}
                self.assertIn("api_read", names)
                self.assertIn("read_github_file", names)
                self.assertNotIn("search_repository_text", names)
            with self.assertRaisesRegex(ValueError, "disabled"):
                await read(services, "find_repository_files", {"repo": "team/repo", "path_pattern": "*"})
