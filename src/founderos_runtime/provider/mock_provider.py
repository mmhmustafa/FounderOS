"""Deterministic local Provider with optional fixture and failure behavior."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .contracts import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    canonical_json,
    thaw,
    validate_operation,
)
from .exceptions import (
    ProviderFixtureError,
    ProviderFixtureNotFoundError,
    ProviderRequestError,
)


@dataclass(frozen=True)
class _Fixture:
    operation: str
    input: dict[str, Any]
    output: Any
    error: ProviderError | None
    metadata: dict[str, Any]


def _fixture_key(operation: str, input_value: Mapping[str, Any]) -> str:
    payload = {"operation": operation, "input": thaw(input_value)}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class MockProvider:
    """Pure deterministic generation with no network, credentials, or runtime mutation."""

    provider_name = "founderos.mock"
    provider_version = "1.0.0"

    def __init__(
        self,
        *,
        fixtures: Iterable[_Fixture] = (),
        strict_fixtures: bool = False,
        simulated_errors: Mapping[str, ProviderError] | None = None,
    ) -> None:
        fixture_index: dict[str, _Fixture] = {}
        for fixture in fixtures:
            key = _fixture_key(fixture.operation, fixture.input)
            if key in fixture_index:
                raise ProviderFixtureError(
                    f"duplicate fixture for operation {fixture.operation!r} and identical input"
                )
            fixture_index[key] = fixture
        errors = dict(simulated_errors or {})
        for operation, error in errors.items():
            try:
                validate_operation(operation)
            except ProviderRequestError as failure:
                raise ProviderFixtureError("simulated error operation is invalid") from failure
            if not isinstance(error, ProviderError):
                raise ProviderFixtureError("simulated error values must be ProviderError objects")
        self._fixtures = fixture_index
        self._strict_fixtures = strict_fixtures
        self._simulated_errors = errors

    @classmethod
    def from_fixtures(cls, path: str | Path) -> "MockProvider":
        fixture_path = Path(path)
        if not fixture_path.is_file():
            raise ProviderFixtureError(f"fixture file was not found: {fixture_path}")
        try:
            with fixture_path.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ProviderFixtureError(f"fixture file is not valid UTF-8 JSON: {fixture_path}") from error
        fixtures = _parse_fixture_document(document)
        return cls(fixtures=fixtures, strict_fixtures=True)

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not isinstance(request, ProviderRequest):
            raise ProviderRequestError("generate requires a ProviderRequest")
        metadata = self._response_metadata(request)

        simulated = self._simulated_errors.get(request.operation)
        if simulated is not None:
            return self._error_response(request, simulated, metadata)

        fixture = self._fixtures.get(_fixture_key(request.operation, request.input))
        if fixture is None and self._strict_fixtures:
            raise ProviderFixtureNotFoundError(
                f"no fixture for operation {request.operation!r} with request fingerprint "
                f"{request.fingerprint}"
            )
        if fixture is not None:
            metadata["fixture"] = fixture.metadata
            if fixture.error is not None:
                return self._error_response(request, fixture.error, metadata)
            output = fixture.output
        else:
            output = {"operation": request.operation, "input": thaw(request.input)}

        validation_error = self._validate_output(request, output)
        if validation_error is not None:
            return self._error_response(request, validation_error, metadata)
        return ProviderResponse(
            request_id=request.request_id,
            status=ProviderStatus.SUCCESS,
            output=output,
            error=None,
            metadata=metadata,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
        )

    @staticmethod
    def _response_metadata(request: ProviderRequest) -> dict[str, Any]:
        return {
            "request_fingerprint": request.fingerprint,
            "correlation_id": request.correlation_id,
            "idempotency_key": request.idempotency_key,
            "request_metadata": thaw(request.metadata),
        }

    def _error_response(
        self,
        request: ProviderRequest,
        error: ProviderError,
        metadata: Mapping[str, Any],
    ) -> ProviderResponse:
        return ProviderResponse(
            request_id=request.request_id,
            status=ProviderStatus.ERROR,
            output=None,
            error=error,
            metadata=metadata,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
        )

    @staticmethod
    def _validate_output(request: ProviderRequest, output: Any) -> ProviderError | None:
        if request.expected_output_schema is None:
            return None
        validator = Draft202012Validator(thaw(request.expected_output_schema))
        errors = sorted(
            validator.iter_errors(output),
            key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
        )
        if not errors:
            return None
        error = errors[0]
        field = ".".join(str(part) for part in error.absolute_path) or "<root>"
        return ProviderError(
            code="invalid_output",
            message="mock output does not match expected_output_schema",
            retryable=False,
            details={"field": field, "reason": error.message},
        )


def _parse_fixture_document(document: Any) -> tuple[_Fixture, ...]:
    if not isinstance(document, dict) or set(document) != {"format_version", "responses"}:
        raise ProviderFixtureError("fixture document must contain only format_version and responses")
    if document["format_version"] != "1.0.0":
        raise ProviderFixtureError("unsupported fixture format_version; expected 1.0.0")
    if not isinstance(document["responses"], list):
        raise ProviderFixtureError("fixture responses must be an array")

    fixtures: list[_Fixture] = []
    for index, item in enumerate(document["responses"]):
        if not isinstance(item, dict):
            raise ProviderFixtureError(f"fixture responses[{index}] must be an object")
        allowed = {"operation", "input", "output", "error", "metadata"}
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise ProviderFixtureError(f"fixture responses[{index}] has unknown field {unknown[0]!r}")
        if "operation" not in item or "input" not in item:
            raise ProviderFixtureError(f"fixture responses[{index}] requires operation and input")
        if ("output" in item) == ("error" in item):
            raise ProviderFixtureError(
                f"fixture responses[{index}] requires exactly one of output or error"
            )
        if not isinstance(item["input"], dict):
            raise ProviderFixtureError(f"fixture responses[{index}] operation/input are invalid")
        try:
            request = ProviderRequest(
                request_id=f"fixture-{index}",
                operation=item["operation"],
                input=item["input"],
            )
        except ProviderRequestError as failure:
            raise ProviderFixtureError(f"fixture responses[{index}] operation/input are invalid") from failure
        error = None
        if "error" in item:
            error_value = item["error"]
            if not isinstance(error_value, dict):
                raise ProviderFixtureError(f"fixture responses[{index}].error must be an object")
            try:
                error = ProviderError(**error_value)
            except (TypeError, ProviderRequestError) as failure:
                raise ProviderFixtureError(f"fixture responses[{index}].error is invalid") from failure
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ProviderFixtureError(f"fixture responses[{index}].metadata must be an object")
        fixtures.append(
            _Fixture(
                operation=request.operation,
                input=thaw(request.input),
                output=item.get("output"),
                error=error,
                metadata=metadata,
            )
        )
    return tuple(fixtures)
