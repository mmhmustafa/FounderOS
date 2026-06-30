"""Event construction helpers."""

from __future__ import annotations

from typing import Any

from .ids import new_id, utc_now
from .repositories import RuntimeRepositories


def build_event(
    repositories: RuntimeRepositories,
    *,
    project_id: str,
    event_type: str,
    actor: dict[str, Any],
    subject_ref: dict[str, Any],
    correlation_id: str,
    payload: dict[str, Any],
    causation_event_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    event: dict[str, Any] = {
        "id": new_id("event"),
        "project_ref": {"kind": "project", "id": project_id},
        "sequence": repositories.events.next_sequence(project_id),
        "event_type": event_type,
        "actor": actor,
        "subject_ref": subject_ref,
        "correlation_id": correlation_id,
        "payload": payload,
        "occurred_at": now,
        "recorded_at": now,
    }
    if causation_event_ref:
        event["causation_event_ref"] = causation_event_ref
    return event
