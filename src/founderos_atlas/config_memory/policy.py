"""Configuration collection policy (PR-044, Part 1).

Collection is policy driven, not a bare on/off flag:

    always          collect on every authenticated discovery
    scheduled       collect when the configured interval has elapsed
    manual          collect only when the operator explicitly asks
    discovery-only  collect during a discovery run, but never on a schedule
    disabled        never collect

The decision is a pure function of (policy, context) — deterministic, no
clock reads inside the engine: the caller supplies ``now`` and the last
collection time, so the same inputs always produce the same decision.

Backward compatible: the existing boolean ``collect_configuration`` maps to
``always`` (True) or ``disabled`` (False).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


POLICY_ALWAYS = "always"
POLICY_SCHEDULED = "scheduled"
POLICY_MANUAL = "manual"
POLICY_DISCOVERY_ONLY = "discovery-only"
POLICY_DISABLED = "disabled"

COLLECTION_POLICIES = (
    POLICY_ALWAYS,
    POLICY_SCHEDULED,
    POLICY_MANUAL,
    POLICY_DISCOVERY_ONLY,
    POLICY_DISABLED,
)

DEFAULT_SCHEDULE_HOURS = 24

# Why a run did or did not collect — surfaced to the operator, never guessed.
REASON_POLICY_DISABLED = "collection policy is disabled"
REASON_ALWAYS = "collection policy is always"
REASON_DISCOVERY_RUN = "collection runs with discovery"
REASON_MANUAL_REQUESTED = "an operator explicitly requested collection"
REASON_MANUAL_NOT_REQUESTED = (
    "collection policy is manual and this run did not request it"
)
REASON_SCHEDULE_DUE = "the collection schedule is due"
REASON_SCHEDULE_NOT_DUE = "the collection schedule is not due yet"
REASON_SCHEDULE_FIRST = "no configuration has been collected yet"


@dataclass(frozen=True)
class CollectionDecision:
    """Whether to collect, and the stated reason."""

    collect: bool
    policy: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"collect": self.collect, "policy": self.policy, "reason": self.reason}


def normalize_policy(value: Any) -> str:
    """Resolve a policy value, including the legacy boolean form."""

    if value is None:
        return POLICY_DISABLED
    if isinstance(value, bool):
        # Backward compatibility with profile.collect_configuration.
        return POLICY_ALWAYS if value else POLICY_DISABLED
    text = str(value).strip().casefold()
    if text in COLLECTION_POLICIES:
        return text
    if text in ("true", "yes", "on"):
        return POLICY_ALWAYS
    if text in ("false", "no", "off", ""):
        return POLICY_DISABLED
    raise ValueError(f"unknown collection policy: {value!r}")


def _hours_since(last: str | None, now: str) -> float | None:
    if not last:
        return None
    try:
        previous = datetime.fromisoformat(last)
        current = datetime.fromisoformat(now)
    except (TypeError, ValueError):
        return None
    return (current - previous).total_seconds() / 3600.0


def decide_collection(
    policy: Any,
    *,
    now: str,
    last_collected_at: str | None = None,
    schedule_hours: int = DEFAULT_SCHEDULE_HOURS,
    is_discovery_run: bool = True,
    manually_requested: bool = False,
) -> CollectionDecision:
    """Decide whether this run collects configuration, and say why.

    Deterministic: identical inputs always yield the identical decision.
    """

    resolved = normalize_policy(policy)

    if resolved == POLICY_DISABLED:
        return CollectionDecision(False, resolved, REASON_POLICY_DISABLED)

    if resolved == POLICY_ALWAYS:
        return CollectionDecision(True, resolved, REASON_ALWAYS)

    if resolved == POLICY_DISCOVERY_ONLY:
        return CollectionDecision(
            bool(is_discovery_run),
            resolved,
            REASON_DISCOVERY_RUN if is_discovery_run
            else "this run is not a discovery run",
        )

    if resolved == POLICY_MANUAL:
        return CollectionDecision(
            bool(manually_requested),
            resolved,
            REASON_MANUAL_REQUESTED if manually_requested
            else REASON_MANUAL_NOT_REQUESTED,
        )

    # POLICY_SCHEDULED
    if manually_requested:
        return CollectionDecision(True, resolved, REASON_MANUAL_REQUESTED)
    elapsed = _hours_since(last_collected_at, now)
    if elapsed is None:
        return CollectionDecision(True, resolved, REASON_SCHEDULE_FIRST)
    if elapsed >= schedule_hours:
        return CollectionDecision(
            True,
            resolved,
            f"{REASON_SCHEDULE_DUE} ({elapsed:.1f}h since the last collection, "
            f"interval {schedule_hours}h)",
        )
    return CollectionDecision(
        False,
        resolved,
        f"{REASON_SCHEDULE_NOT_DUE} ({elapsed:.1f}h of {schedule_hours}h elapsed)",
    )
