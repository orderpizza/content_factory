from __future__ import annotations

import os
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from common.gemini import (
    DEFAULT_TEXT_TIMEOUT_SECONDS,
    MAX_TEXT_TIMEOUT_SECONDS,
    TEXT_CLAIM_LEASE_SECONDS,
    GeminiConfigurationError,
    VertexGeminiClient,
    configured_api_version,
    configured_location,
    retryable_provider_error,
    text_timeout_seconds,
)
from common.runtime_fingerprint import runtime_fingerprint
from google.genai.errors import APIError
from workflow.editorial_planning import GeminiEditorialPlanningWorker
from workflow.gemini_adaptation import GeminiAdaptationWorker
from workflow.gemini_determination import GeminiDeterminationWorker
from workflow.gemini_generation import GeminiPipelineRunner
from workflow.gemini_intake import GeminiIntakeWorker


class TransportReliabilityTests(unittest.TestCase):
    def test_timeout_default_override_and_rejection(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(text_timeout_seconds(), DEFAULT_TEXT_TIMEOUT_SECONDS)
            self.assertEqual(DEFAULT_TEXT_TIMEOUT_SECONDS, 180)
        for value in ("0", "-1", "301", "abc", "1.5"):
            with self.subTest(value=value), self.assertRaisesRegex(
                GeminiConfigurationError, "GEMINI_TEXT_TIMEOUT_SECONDS"
            ):
                text_timeout_seconds(value)
        self.assertEqual(text_timeout_seconds("245"), 245)

    def test_model_location_and_api_version_defaults_and_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_location("gemini-3.7-flash"), "global")
            self.assertEqual(configured_location("gemini-2.5-flash"), "us-central1")
            self.assertEqual(configured_api_version("gemini-3.7-flash"), "v1")
            self.assertEqual(configured_api_version("gemini-3-flash-preview"), "v1beta")
        with patch.dict(os.environ, {"GOOGLE_CLOUD_LOCATION": "europe-west4", "GEMINI_API_VERSION": "v1beta"}, clear=True):
            self.assertEqual(configured_location("gemini-3.7-flash"), "europe-west4")
            self.assertEqual(configured_api_version("gemini-3.7-flash"), "v1beta")
        with patch.dict(os.environ, {"GEMINI_API_VERSION": "v1"}, clear=True):
            with self.assertRaisesRegex(GeminiConfigurationError, "preview model"):
                configured_api_version("gemini-3-flash-preview")
        with patch.dict(os.environ, {"GEMINI_API_VERSION": "v9"}, clear=True):
            with self.assertRaisesRegex(GeminiConfigurationError, "must be v1 or v1beta"):
                configured_api_version("gemini-3.7-flash")
        with patch.dict(os.environ, {"GOOGLE_CLOUD_LOCATION": "global"}, clear=True):
            self.assertEqual(configured_location("operator-model"), "global")

    def test_client_passes_timeout_api_and_single_sdk_attempt_without_network(self):
        client_calls = []

        class HttpOptions:
            def __init__(self, **kwargs):
                self.values = kwargs

        class HttpRetryOptions:
            def __init__(self, **kwargs):
                self.values = kwargs

        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.values = kwargs

        sdk = ModuleType("google.genai")
        sdk.types = SimpleNamespace(HttpOptions=HttpOptions, HttpRetryOptions=HttpRetryOptions,
                                    GenerateContentConfig=GenerateContentConfig)
        sdk.Client = lambda **kwargs: client_calls.append(kwargs)
        google = ModuleType("google")
        google.genai = sdk
        with patch.dict(os.environ, {"GEMINI_TEXT_TIMEOUT_SECONDS": "210", "GEMINI_API_VERSION": "v1"}, clear=True), \
                patch.dict("sys.modules", {"google": google, "google.genai": sdk}):
            client = VertexGeminiClient(project="p", model="gemini-3.7-flash")
            client.generate_json = lambda *args, **kwargs: {}  # client construction is covered by the SDK boundary test
            # Exercise the actual adapter through an instance method backed by the fake module.
            client = VertexGeminiClient(project="p", model="gemini-3.7-flash")
            class Response:
                text = "{}"
                usage_metadata = None
                candidates = []
            class Models:
                def generate_content(self, **kwargs):
                    return Response()
            class FakeSDKClient:
                def __init__(self, **kwargs):
                    client_calls.append(kwargs)
                    self.models = Models()
                def close(self):
                    pass
            sdk.Client = FakeSDKClient
            client.generate_json("p", {"type": "object"})
        options = client_calls[-1]["http_options"].values
        self.assertEqual(client_calls[-1]["location"], "global")
        self.assertEqual(options["timeout"], 210_000)
        self.assertEqual(options["api_version"], "v1")
        self.assertEqual(options["retry_options"].values["attempts"], 1)

    def test_provider_status_codes_retry_but_local_timeout_does_not(self):
        for status in (429, 500, 502, 503, 504):
            self.assertTrue(retryable_provider_error(APIError(status, {})))
        self.assertFalse(retryable_provider_error(TimeoutError("504 DEADLINE_EXCEEDED")))
        self.assertFalse(retryable_provider_error(SimpleNamespace(code=504)))
        self.assertFalse(retryable_provider_error(APIError(400, {})))

    def test_text_claim_lease_exceeds_maximum_deadline_and_all_text_workers_use_it(self):
        self.assertGreaterEqual(TEXT_CLAIM_LEASE_SECONDS, MAX_TEXT_TIMEOUT_SECONDS + 120)
        class Store:
            model_budget_policy = None
            def __init__(self): self.calls = []
            def claim(self, *args, **kwargs): self.calls.append(kwargs); return None
        store = Store()
        fake = SimpleNamespace(model="fixture", max_output_tokens=None, thinking_level="LOW")
        workers = [
            GeminiIntakeWorker(store, fake), GeminiDeterminationWorker(store, fake),
            GeminiEditorialPlanningWorker(store, fake), GeminiPipelineRunner(store, fake),
            GeminiAdaptationWorker(store, fake),
        ]
        for worker in workers: worker.run_once()
        self.assertEqual([c["lease_seconds"] for c in store.calls], [600] * 5)

    def test_runtime_fingerprint_has_nonsecret_transport_and_contract_versions(self):
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-3.7-flash", "GOOGLE_CLOUD_LOCATION": "global",
                                     "GEMINI_API_VERSION": "v1", "GEMINI_TEXT_TIMEOUT_SECONDS": "180",
                                     "GOOGLE_CLOUD_PROJECT": "do-not-record"}, clear=True):
            value = runtime_fingerprint()
        self.assertEqual(value["database_schema_version"], 17)
        self.assertEqual(value["text_model"], "gemini-3.7-flash")
        self.assertEqual(value["vertex_location"], "global")
        self.assertEqual(value["api_version"], "v1")
        self.assertEqual(value["text_timeout_seconds"], 180)
        self.assertEqual(value["prompt_versions"]["generation"], "workflow_gemini_generation_prompt_v7")
        self.assertNotIn("do-not-record", repr(value))


if __name__ == "__main__":
    unittest.main()
