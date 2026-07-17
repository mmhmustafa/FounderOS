"""Adapters folding every audit trail into one unified, filterable view.

The site-override and peer-identity audits keep their own files and
their own undo semantics — those repositories replay their trails
verbatim, so this module READS them and never rewrites them. Everything
newer (exceptions, assignments, acknowledgements, annotations) already
lives in the unified log.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .log import AuditLog
from .models import AuditEvent


def _site_override_events(workspace_root: Path) -> list[AuditEvent]:
    try:
        from founderos_atlas.sites import SiteOverrideRepository

        events = SiteOverrideRepository(workspace_root).history()
    except Exception:  # noqa: BLE001 - an absent trail is a state
        return []
    unified: list[AuditEvent] = []
    for event in events:
        # before/after hold ONLY the mutated field, so the diff view never
        # implies a value was removed when it merely wasn't restated.
        unified.append(AuditEvent(
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            actor=event.actor,
            scope_id="all",
            category="site-override",
            operation=event.action,
            subject=event.subject_key,
            before={"site_id": event.before_site_id},
            after={"site_id": event.after_site_id},
            reason=event.reason,
            source="web",
            correlation_id=event.undoes_event_id,
        ))
    return unified


def _identity_resolution_events(workspace_root: Path) -> list[AuditEvent]:
    try:
        from founderos_atlas.identity import PeerResolutionRepository

        events = PeerResolutionRepository(workspace_root).history()
    except Exception:  # noqa: BLE001
        return []
    unified: list[AuditEvent] = []
    for event in events:
        unified.append(AuditEvent(
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            actor=event.actor,
            scope_id="all",
            category="identity-resolution",
            operation=event.action,
            subject=event.subject_key,
            before={"resolved_hostname": event.before_hostname},
            after={"resolved_hostname": event.after_hostname},
            reason=event.reason,
            source="web",
            correlation_id=event.undoes_event_id,
        ))
    return unified


def unified_audit_events(
    workspace_root: str | Path,
    *,
    category: str | None = None,
    actor: str | None = None,
    subject_contains: str | None = None,
) -> tuple[AuditEvent, ...]:
    """Every audit event Atlas holds, newest first, optionally filtered."""

    root = Path(workspace_root)
    events: list[AuditEvent] = list(AuditLog(root).events())
    events.extend(_site_override_events(root))
    events.extend(_identity_resolution_events(root))
    if category:
        events = [e for e in events if e.category == category]
    if actor:
        events = [e for e in events if e.actor == actor]
    if subject_contains:
        needle = subject_contains.casefold()
        events = [
            e for e in events
            if needle in e.subject.casefold()
            or needle in str(e.before).casefold()
            or needle in str(e.after).casefold()
        ]
    events.sort(key=lambda e: e.occurred_at, reverse=True)
    return tuple(events)


def export_rows(events) -> list[dict[str, Any]]:
    """Flat export rows (CSV/JSON) for the filtered audit view."""

    return [
        {
            "occurred_at": e.occurred_at,
            "actor": e.actor,
            "scope": e.scope_id,
            "category": e.category,
            "operation": e.operation,
            "subject": e.subject,
            "before": str(dict(e.before)),
            "after": str(dict(e.after)),
            "reason": e.reason or "",
            "source": e.source,
            "correlation_id": e.correlation_id or "",
            "event_id": e.event_id,
        }
        for e in events
    ]
