"""Immutable deterministic Execution Plan value objects."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
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


@dataclass(frozen=True, order=True)
class DefinitionReference:
    id: str
    version: str
    role: str | None = None


@dataclass(frozen=True, order=True)
class ArtifactReference:
    id: str
    artifact_type: str
    schema_ref: str


@dataclass(frozen=True)
class ExecutionStep:
    id: str
    type: str
    description: str
    required_agent: DefinitionReference | None
    required_artifacts: tuple[str, ...]
    produced_artifacts: tuple[str, ...]
    requires_evaluation: bool
    requires_approval: bool


@dataclass(frozen=True)
class ExecutionPlan:
    workflow_id: str
    steps: tuple[ExecutionStep, ...]
    required_agents: tuple[DefinitionReference, ...]
    required_artifacts: tuple[ArtifactReference, ...]
    produced_artifacts: tuple[ArtifactReference, ...]
    evaluations: tuple[Mapping[str, Any], ...]
    approvals: tuple[Mapping[str, Any], ...]
    transition_request: Mapping[str, Any] | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evaluations",
            tuple(_freeze(item) for item in self.evaluations),
        )
        object.__setattr__(
            self,
            "approvals",
            tuple(_freeze(item) for item in self.approvals),
        )
        object.__setattr__(
            self,
            "transition_request",
            _freeze(self.transition_request) if self.transition_request is not None else None,
        )
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "steps": [asdict(step) for step in self.steps],
            "required_agents": [asdict(agent) for agent in self.required_agents],
            "required_artifacts": [asdict(artifact) for artifact in self.required_artifacts],
            "produced_artifacts": [asdict(artifact) for artifact in self.produced_artifacts],
            "evaluations": thaw(self.evaluations),
            "approvals": thaw(self.approvals),
            "transition_request": thaw(self.transition_request),
            "metadata": thaw(self.metadata),
        }
