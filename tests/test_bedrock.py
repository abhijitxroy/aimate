"""Bedrock authentication routing and secret isolation; no billable requests."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent import ai_client, ai_error
from app.connectors import scrub
from app.store import Store
from app.validation import validate_config


class BedrockTests(unittest.TestCase):
    def config(self, **kwargs):
        return {"ai": {"provider": "bedrock", "region": "us-east-1",
                       "model": "account-model", **kwargs}}

    def test_bearer_runtime(self):
        with patch("anthropic.AsyncAnthropicBedrock") as factory:
            ai_client(self.config(api_key="bedrock-secret"))
            self.assertEqual(factory.call_args.kwargs["api_key"], "bedrock-secret")
            self.assertNotIn("aws_secret_key", factory.call_args.kwargs)

    def test_iam_uses_credentials_not_saved_bearer(self):
        with patch.dict(os.environ, {}, clear=True), patch("anthropic.AsyncAnthropicBedrock") as factory:
            ai_client(self.config(bedrock_auth="iam", api_key="unused-key",
                                 aws_access_key="access", aws_secret_key="secret", aws_session_token="session"))
            self.assertNotIn("api_key", factory.call_args.kwargs)
            self.assertEqual(factory.call_args.kwargs["aws_session_token"], "session")
            self.assertEqual(factory.call_args.kwargs["aws_secret_key"], "secret")

    def test_iam_server_chain(self):
        with patch.dict(os.environ, {}, clear=True), patch("anthropic.AsyncAnthropicBedrock") as factory:
            ai_client(self.config(bedrock_auth="iam"))
            self.assertNotIn("aws_access_key", factory.call_args.kwargs)

    def test_iam_environment_bearer_conflict_is_explicit(self):
        with patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "secret"}):
            with self.assertRaisesRegex(ValueError, "unset"):
                ai_client(self.config(bedrock_auth="iam"))

    def test_mantle_routes_to_native_messages(self):
        with patch("anthropic.AsyncAnthropic") as factory:
            ai_client(self.config(bedrock_endpoint="mantle", api_key="bedrock-secret"))
            self.assertEqual(factory.call_args.kwargs["base_url"],
                             "https://bedrock-mantle.us-east-1.api.aws/anthropic")

    def test_secrets_preserved_removed_and_never_exposed(self):
        old = self.config(aws_access_key="access", aws_secret_key="secret", aws_session_token="session")
        new = validate_config(self.config(bedrock_auth="iam"), old)
        self.assertEqual(new["ai"]["aws_session_token"], "session")
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.save_config(new)
                public = store.public_config()["ai"]
                for key in ("aws_access_key", "aws_secret_key", "aws_session_token"):
                    self.assertNotIn(key, public)
                    self.assertTrue(public[key + "_configured"])
                self.assertEqual(scrub("access secret session", new), "[redacted] [redacted] [redacted]")
            finally:
                store.db.close()
        removed = validate_config(self.config(clear_aws=True), old)
        self.assertFalse(removed["ai"]["aws_secret_key"])

    def test_bad_configuration_rejected(self):
        for fields in ({"region": "evil/path"}, {"aws_access_key": "only-one"},
                       {"bedrock_auth": "anything"}, {"bedrock_endpoint": "anything"},
                       {"bedrock_endpoint": "mantle", "bedrock_auth": "iam"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_config(self.config(**fields), {})

    def test_provider_switch_does_not_reuse_another_providers_key(self):
        new = validate_config(self.config(), {"ai": {"provider": "anthropic", "api_key": "old-secret"}})
        self.assertEqual(new["ai"]["api_key"], "")

    def test_errors_do_not_echo_upstream_body(self):
        error = SimpleNamespace(status_code=403, body="secret-token")
        self.assertIn("IAM", ai_error(error))
        self.assertNotIn("secret-token", ai_error(error))


if __name__ == "__main__":
    unittest.main()
