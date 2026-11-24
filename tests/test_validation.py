"""Dependency-free checks for the actual scope/input validators."""
import unittest

from app.validation import clean_path, number, ref, scoped_jql, valid_base, validate_config


class ValidationTests(unittest.TestCase):
    def test_masked_credentials_cannot_replace_saved_secrets(self):
        for credential in ("api_key", "aws_access_key", "aws_secret_key", "aws_session_token"):
            for masked in ("<redacted>", "[REDACTED]", "********", "••••••"):
                config = self.config()
                config["ai"][credential] = masked
                with self.subTest(credential=credential, masked=masked), self.assertRaisesRegex(ValueError, "Masked"):
                    validate_config(config, {})
        for section in ("github", "jira", "jenkins"):
            config = self.config()
            config[section]["token"] = "<redacted>"
            with self.assertRaisesRegex(ValueError, "Masked"):
                validate_config(config, {})

    def config(self):
        return {"allow_writes": False,
                "ai": {"provider": "anthropic", "model": "example-model"},
                "github": {"url": "https://github.example/api/v3", "repos": ["team/repo"], "token": "sample-token"},
                "jira": {}, "jenkins": {}}

    def test_https_base_preserves_enterprise_prefix(self):
        self.assertEqual(valid_base("https://github.example/api/v3/"), "https://github.example/api/v3")

    def test_unsafe_bases_rejected(self):
        for value in ["http://github.example", "https://user:pass@host", "https://host?secret=x",
                      "https://host#fragment", "https://host\\other"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                valid_base(value)

    def test_relative_paths_reject_escape(self):
        for value in ["//evil.example", "https://evil.example", "/x/../secret", "/x/%2e%2e/secret",
                      "/x/%252e%252e/secret", "/x%2fy", "/x%5cy", "/x?token=x", "/x#other"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                clean_path(value)

    def test_safe_paths_work(self):
        self.assertEqual(clean_path("/repos/team/repo/contents/src/main.py"), "/repos/team/repo/contents/src/main.py")

    def test_jql_or_cannot_escape_scope(self):
        self.assertEqual(scoped_jql("status = Open OR assignee = currentUser() ORDER BY updated DESC", ["DEMO"]),
                         "project IN (DEMO) AND (status = Open OR assignee = currentUser()) ORDER BY updated DESC")

    def test_jql_parenthesis_injection_rejected(self):
        for value in ["status=Open) OR project=OTHER OR (status=Open", "(status=Open", 'summary ~ "unterminated']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                scoped_jql(value, ["DEMO"])

    def test_order_by_in_quoted_string_is_preserved(self):
        self.assertEqual(scoped_jql('summary ~ "order by example"', ["DEMO"]),
                         'project IN (DEMO) AND (summary ~ "order by example")')

    def test_token_preservation_and_removal(self):
        old = self.config()
        new = self.config()
        new["github"]["token"] = ""
        self.assertEqual(validate_config(new, old)["github"]["token"], "sample-token")
        new["github"]["clear_token"] = True
        self.assertEqual(validate_config(new, old)["github"]["token"], "")

    def test_token_requires_scope(self):
        cfg = self.config()
        cfg["github"]["repos"] = []
        with self.assertRaises(ValueError):
            validate_config(cfg, {})

    def test_non_string_scope_and_traversal_rejected(self):
        for value in [[{"repo": "team/repo"}], ["team/.."], ["../repo"]]:
            cfg = self.config()
            cfg["github"]["repos"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config(cfg, {})

    def test_repo_deduplication(self):
        cfg = self.config()
        cfg["github"]["repos"] = ["team/repo", "team/repo"]
        self.assertEqual(validate_config(cfg, {})["github"]["repos"], ["team/repo"])

    def test_github_organization_url_normalizes_mixed_repositories(self):
        cfg = self.config()
        cfg["github"].update(url="https://github.com/intel-innersource/",
                             repos=["abhijitxroy/aimate", "frameworks.devops.oneapi.ci"])
        result = validate_config(cfg, {})["github"]
        self.assertEqual(result["url"], "https://api.github.com")
        self.assertEqual(result["repos"], ["abhijitxroy/aimate", "intel-innersource/frameworks.devops.oneapi.ci"])

    def test_github_repository_and_pr_links_normalize(self):
        cfg = self.config()
        cfg["github"].update(url="https://api.github.com",
                             repos=["https://github.com/team/repo.git", "https://github.com/team/repo/pull/1257"])
        self.assertEqual(validate_config(cfg, {})["github"]["repos"], ["team/repo"])

    def test_repository_links_reject_credentials_and_other_hosts(self):
        for value in ["https://github.com/team/repo?token=private", "https://other.example/team/repo"]:
            cfg = self.config()
            cfg["github"]["repos"] = [value]
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_config(cfg, {})

    def test_numeric_and_branch_guards(self):
        self.assertEqual(number("42"), 42)
        self.assertEqual(ref("fix/DEMO-123"), "fix/DEMO-123")
        for value in [True, 0, -1, "a"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)
        for value in ["../main", "fix//x", "fix.lock", "-branch", "main?x"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ref(value)


if __name__ == "__main__":
    unittest.main()
