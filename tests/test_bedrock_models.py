"""Catalog discovery is read-only, region-specific and distinct from invocation."""
import asyncio
import unittest

import httpx

from app.bedrock_models import discover_models, presets


class BedrockModelTests(unittest.TestCase):
    def test_presets_preserve_organization_versions_and_endpoint_ids(self):
        runtime = {m["id"] for m in presets()}
        self.assertIn("us.anthropic.claude-fable-5-2", runtime)
        self.assertIn("us.anthropic.claude-sonnet-5-5", runtime)
        self.assertTrue(all(m["id"].startswith("anthropic.") for m in presets("mantle")))

    def test_runtime_lists_models_and_all_profile_pages_without_inference(self):
        requests = []

        def remote(request):
            requests.append(request)
            self.assertEqual(request.headers["authorization"], "Bearer catalog-secret")
            self.assertEqual(request.url.host, "bedrock.us-east-2.amazonaws.com")
            if request.url.path == "/foundation-models":
                return httpx.Response(200, json={"modelSummaries": [
                    {"modelId": "anthropic.claude-sonnet-5-5", "modelName": "Sonnet 5.5", "modelLifecycle": {"status": "ACTIVE"}},
                    {"modelId": "anthropic.claude-old", "modelLifecycle": {"status": "LEGACY"}}]})
            self.assertEqual(request.url.path, "/inference-profiles")
            if request.url.params.get("nextToken"):
                return httpx.Response(200, json={"inferenceProfileSummaries": [
                    {"inferenceProfileId": "us.anthropic.claude-opus-5-5", "status": "ACTIVE",
                     "models": [{"modelArn": "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-opus-5-5"}]}]})
            return httpx.Response(200, json={"inferenceProfileSummaries": [], "nextToken": "page2"})

        result = asyncio.run(discover_models({"region": "us-east-2", "api_key": "catalog-secret"},
                                            transport=httpx.MockTransport(remote)))
        self.assertEqual(len(result["models"]), 2)
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(request.method == "GET" for request in requests))
        self.assertIn("does not verify invocation", result["message"])
        self.assertNotIn("catalog-secret", str(result))

    def test_denied_catalog_does_not_claim_access_or_echo_body(self):
        result = asyncio.run(discover_models({"api_key": "key"}, transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"message": "PRIVATE ERROR BODY"}))))
        self.assertEqual(result["models"], [])
        self.assertIn("permission", result["message"])
        self.assertNotIn("PRIVATE ERROR BODY", str(result))

    def test_mantle_uses_its_own_model_list_endpoint(self):
        def remote(request):
            self.assertEqual(request.url.host, "bedrock-mantle.us-east-2.api.aws")
            self.assertEqual(request.url.path, "/v1/models")
            return httpx.Response(200, json={"data": [{"id": "anthropic.claude-haiku-5-5"}, {"id": "other.model"}]})

        result = asyncio.run(discover_models({"api_key": "key", "bedrock_endpoint": "mantle"},
                                            transport=httpx.MockTransport(remote)))
        self.assertEqual([m["id"] for m in result["models"]], ["anthropic.claude-haiku-5-5"])

    def test_invalid_region_and_missing_key_do_not_make_requests(self):
        for ai in ({"region": "evil.example/path", "api_key": "key"}, {}):
            with self.subTest(ai=ai), self.assertRaises(ValueError):
                asyncio.run(discover_models(ai))
