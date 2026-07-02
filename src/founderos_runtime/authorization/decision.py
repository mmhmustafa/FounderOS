"""Immutable plan Authorization Decision contracts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
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
class PolicyResult:
    policy: str
    outcome: str
    reason: str


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    required_approvals: tuple[str, ...]
    policy_results: tuple[PolicyResult, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be a boolean")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be a non-empty string")
        if len(self.required_approvals) != len(set(self.required_approvals)):
            raise ValueError("required_approvals must be unique")
        object.__setattr__(self, "required_approvals", tuple(sorted(self.required_approvals)))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "required_approvals": list(self.required_approvals),
            "policy_results": [
                {"policy": x.policy, "outcome": x.outcome, "reason": x.reason}
                for x in self.policy_results
            ],
            "metadata": thaw(self.metadata),
        }

