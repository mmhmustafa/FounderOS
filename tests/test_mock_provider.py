"""Deterministic Mock Provider contracts, fixtures, failures, and isolation tests."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from founderos_runtime.provider import (
    MockProvider,
    ProviderError,
    ProviderFixtureNotFoundError,
    ProviderRequest,
    ProviderRequestError,
    ProviderStatus,
    thaw,
)

from tests.helpers import RuntimeFixture


class MockProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = ProviderRequest(
            request_id="req-001",
            operation="discovery.summarize",
            input={"candidate": "Deterministic SaaS"},
            metadata={"source": "test"},
            correlation_id="command-001",
            idempotency_key="summary-001",
        )

    def fixture_file(self, responses: list[dict[str, object]]) -> tuple[TemporaryDirectory, Path]:
        directory = TemporaryDirectory()
        path = Path(directory.name) / "provider-fixtures.json"
        path.write_text(
            json.dumps({"format_version": "1.0.0", "responses": responses}),
            encoding="utf-8",
        )
        return directory, path

    def test_mock_provider_returns_deterministic_output(self) -> None:
        response = MockProvider().generate(self.request)
        self.assertEqual(response.status, ProviderStatus.SUCCESS)
        self.assertEqual(
            thaw(response.output),
            {
                "operation": "discovery.summarize",
                "input": {"candidate": "Deterministic SaaS"},
            },
        )

    def test_same_request_returns_equal_response(self) -> None:
        provider = MockProvider()
        first = provider.generate(self.request)
        second = provider.generate(self.request)
        self.assertEqual(first, second)
        self.assertEqual(first.metadata["request_fingerprint"], second.metadata["request_fingerprint"])

    def test_fixture_based_response_works(self) -> None:
        directory, path = self.fixture_file(
            [
                {
                    "operation": "discovery.summarize",
                    "input": {"candidate": "Deterministic SaaS"},
                    "output": {"summary": "Fixture result"},
                    "metadata": {"fixture_id": "summary-1"},
                }
            ]
        )
        self.addCleanup(directory.cleanup)
        response = MockProvider.from_fixtures(path).generate(self.request)
        self.assertEqual(thaw(response.output), {"summary": "Fixture result"})
        self.assertEqual(response.metadata["fixture"]["fixture_id"], "summary-1")

    def test_missing_fixture_returns_clear_error(self) -> None:
        directory, path = self.fixture_file([])
        self.addCleanup(directory.cleanup)
        provider = MockProvider.from_fixtures(path)
        with self.assertRaises(ProviderFixtureNotFoundError) as raised:
            provider.generate(self.request)
        self.assertIn("discovery.summarize", str(raised.exception))
        self.assertIn(self.request.fingerprint, str(raised.exception))

    def test_simulated_provider_failure_returns_error_response(self) -> None:
        failure = ProviderError(
            code="rate_limited",
            message="Simulated provider rate limit",
            retryable=True,
        )
        response = MockProvider(simulated_errors={"discovery.summarize": failure}).generate(
            self.request
        )
        self.assertEqual(response.status, ProviderStatus.ERROR)
        self.assertIsNone(response.output)
        self.assertEqual(response.error, failure)

    def test_response_includes_request_and_provider_metadata(self) -> None:
        response = MockProvider().generate(self.request)
        self.assertEqual(response.request_id, "req-001")
        self.assertEqual(response.provider_name, "founderos.mock")
        self.assertEqual(response.provider_version, "1.0.0")
        self.assertEqual(response.metadata["correlation_id"], "command-001")
        self.assertEqual(response.metadata["idempotency_key"], "summary-001")
        self.assertEqual(response.metadata["request_metadata"]["source"], "test")

    def test_provider_performs_no_network_access(self) -> None:
        with (
            patch("socket.create_connection", side_effect=AssertionError("network used")),
            patch("urllib.request.urlopen", side_effect=AssertionError("network used")),
        ):
            response = MockProvider().generate(self.request)
        self.assertEqual(response.status, ProviderStatus.SUCCESS)

    def test_provider_does_not_mutate_runtime_state(self) -> None:
        runtime = RuntimeFixture()
        before = runtime.repositories.export_records()
        MockProvider().generate(self.request)
        after = runtime.repositories.export_records()
        self.assertEqual(before, after)

    def test_invalid_request_is_rejected(self) -> None:
        with self.assertRaises(ProviderRequestError):
            ProviderRequest(request_id="", operation="discovery.summarize", input={})
        with self.assertRaises(ProviderRequestError):
            ProviderRequest(request_id="req", operation="Invalid Operation", input={})
        with self.assertRaises(ProviderRequestError):
            ProviderRequest(request_id="req", operation="valid.operation", input={1: "invalid"})
        with self.assertRaises(ProviderRequestError):
            MockProvider().generate({"request_id": "not-a-contract"})  # type: ignore[arg-type]

    def test_expected_output_schema_failure_is_structured(self) -> None:
        request = ProviderRequest(
            request_id="req-schema",
            operation="discovery.summarize",
            input={"candidate": "Example"},
            expected_output_schema={
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
            },
        )
        response = MockProvider().generate(request)
        self.assertEqual(response.status, ProviderStatus.ERROR)
        self.assertEqual(response.error.code, "invalid_output")
        self.assertFalse(response.error.retryable)

    def test_request_and_response_values_are_immutable(self) -> None:
        response = MockProvider().generate(self.request)
        with self.assertRaises(TypeError):
            self.request.input["candidate"] = "Changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            response.metadata["correlation_id"] = "changed"  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
