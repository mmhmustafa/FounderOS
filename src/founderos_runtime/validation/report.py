"""Immutable Plan Validation findings and report contracts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return deepcopy(value)


class FindingSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, order=True)
class ValidationFinding:
    code: str
    severity: FindingSeverity
    message: str
    subject: str


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    findings: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    errors: tuple[ValidationFinding, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        expected_warnings = tuple(x for x in self.findings if x.severity is FindingSeverity.WARNING)
        expected_errors = tuple(x for x in self.findings if x.severity is FindingSeverity.ERROR)
        if self.warnings != expected_warnings or self.errors != expected_errors:
            raise ValueError("warnings and errors must be projections of findings")
        if self.valid != (not self.errors):
            raise ValueError("valid must be true exactly when errors is empty")
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        encode = lambda item: {
            "code": item.code,
            "severity": item.severity.value,
            "message": item.message,
            "subject": item.subject,
        }
        return {
            "valid": self.valid,
            "findings": [encode(item) for item in self.findings],
            "warnings": [encode(item) for item in self.warnings],
            "errors": [encode(item) for item in self.errors],
            "metadata": thaw(self.metadata),
        }


def report(findings: list[ValidationFinding], metadata: Mapping[str, Any]) -> ValidationReport:
    ordered = tuple(sorted(findings, key=lambda x: (x.severity.value, x.code, x.subject, x.message)))
    warnings = tuple(x for x in ordered if x.severity is FindingSeverity.WARNING)
    errors = tuple(x for x in ordered if x.severity is FindingSeverity.ERROR)
    return ValidationReport(not errors, ordered, warnings, errors, metadata)

