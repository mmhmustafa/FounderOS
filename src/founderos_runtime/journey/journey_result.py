"""Immutable deterministic result values for one in-memory Founder Journey."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from founderos_runtime.evaluation import EvaluationResult


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


def thaw(value: Any) -> Any:
    """Return a defensive JSON-compatible copy of frozen Journey data."""

    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return deepcopy(value)


class JourneyStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class JourneyResult:
    workflow_id: str
    status: JourneyStatus
    completed_steps: tuple[str, ...]
    skipped_steps: tuple[str, ...]
    evaluation_results: tuple[EvaluationResult, ...]
    generated_artifacts: Mapping[str, Any]
    execution_log: tuple[Mapping[str, Any], ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.workflow_id, str) or not self.workflow_id:
            raise ValueError("workflow_id must be a non-empty string")
        if not isinstance(self.status, JourneyStatus):
            raise ValueError("status must be a JourneyStatus")
        object.__setattr__(self, "generated_artifacts", _freeze(self.generated_artifacts))
        object.__setattr__(self, "execution_log", tuple(_freeze(x) for x in self.execution_log))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "completed_steps": list(self.completed_steps),
            "skipped_steps": list(self.skipped_steps),
            "evaluation_results": [
                {
                    "request_id": result.request_id,
                    "passed": result.passed,
                    "score": result.score,
                    "findings": [
                        {
                            "rule_id": finding.rule_id,
                            "severity": finding.severity.value,
                            "message": finding.message,
                            "passed": finding.passed,
                        }
                        for finding in result.findings
                    ],
                    "metadata": thaw(result.metadata),
                }
                for result in self.evaluation_results
            ],
            "generated_artifacts": thaw(self.generated_artifacts),
            "execution_log": thaw(self.execution_log),
            "metadata": thaw(self.metadata),
        }

