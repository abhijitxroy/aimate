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

    def test_simple_needs_only_token(self):
        config = validate_config({"ai": {"provider": "bedrock", "bedrock_mode": "simple", "api_key": "key"}}, {})
        ai = config["ai"]
        self.assertEqual(ai["region"], "us-east-2")
        self.assertEqual(ai["bedrock_auth"], "bearer")
        self.assertEqual(ai["bedrock_endpoint"], "runtime")
        self.assertEqual(ai["model"], "us.anthropic.claude-haiku-5-5")
        with patch("anthropic.AsyncAnthropicBedrock") as factory:
            ai_client(config)
            self.assertEqual(factory.call_args.kwargs["aws_region"], "us-east-2")
            self.assertEqual(factory.call_args.kwargs["api_key"], "key")

    def test_simple_overrides_hidden_advanced_fields_and_keeps_key(self):
        old = self.config(api_key="saved")
        config = validate_config(self.config(bedrock_mode="simple", bedrock_auth="iam", bedrock_endpoint="mantle"), old)
        self.assertEqual(config["ai"]["api_key"], "saved")
        self.assertEqual(config["ai"]["bedrock_auth"], "bearer")
        self.assertEqual(config["ai"]["bedrock_endpoint"], "runtime")

    def test_advanced_and_chatgpt_keep_their_models(self):
        advanced = validate_config(self.config(bedrock_mode="advanced"), {})
        self.assertEqual(advanced["ai"]["model"], "account-model")
        self.assertEqual(advanced["ai"]["region"], "us-east-1")
        chatgpt = validate_config({"ai": {"provider": "chatgpt", "model": "plan-model", "bedrock_mode": "simple"}}, {})
        self.assertEqual(chatgpt["ai"]["model"], "plan-model")

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
        with patch("anthropic.AsyncAnthropicBedrockMantle") as factory:
            ai_client(self.config(bedrock_endpoint="mantle", api_key="bedrock-secret"))
            self.assertEqual(factory.call_args.kwargs["aws_region"], "us-east-1")
            self.assertEqual(factory.call_args.kwargs["api_key"], "bedrock-secret")

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
                       {"bedrock_auth": "anything"}, {"bedrock_endpoint": "anything"}, {"bedrock_mode": "anything"},
                       {"bedrock_endpoint": "mantle", "bedrock_auth": "iam"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_config(self.config(**fields), {})

    def test_provider_switch_does_not_reuse_another_providers_key(self):
        new = validate_config(self.config(), {"ai": {"provider": "anthropic", "api_key": "old-secret"}})
        self.assertEqual(new["ai"]["api_key"], "")

    def test_aws_authentication_error_is_specific_without_echoing_body(self):
        error = SimpleNamespace(status_code=403, body={"Message": "Authentication failed: Please make sure your API Key is valid. secret-token"})
        message = ai_error(error)
        self.assertIn("could not authenticate", message)
        self.assertNotIn("secret-token", message)
        self.assertNotIn("model access", message)

    def test_errors_do_not_echo_upstream_body(self):
        error = SimpleNamespace(status_code=403, body="secret-token")
        self.assertIn("IAM", ai_error(error))
        self.assertNotIn("secret-token", ai_error(error))

    def test_bad_request_distinguishes_context_model_and_unknown_without_body_leaks(self):
        cases = [
            ({"Message": "prompt is too long secret-token"}, "context limit"),
            ({"error": {"message": "Invalid thinking signature secret-token"}}, "saved reasoning"),
            ({"message": "Invalid tool_result secret-token"}, "tool context"),
            ({"Message": "Invalid model identifier secret-token"}, "model or inference profile"),
            ({"Message": "Unknown service validation secret-token"}, "key may still be valid"),
        ]
        for body, expected in cases:
            message = ai_error(SimpleNamespace(status_code=400, body=body))
            self.assertIn(expected, message)
            self.assertNotIn("secret-token", message)


if __name__ == "__main__":
    unittest.main()
