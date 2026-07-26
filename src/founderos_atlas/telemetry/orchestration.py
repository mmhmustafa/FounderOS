"""Credential-safe orchestration for registered telemetry providers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from founderos_atlas.audit import AuditEvent, AuditLog
from founderos_atlas.notifications import NotificationStore

from .adapters import AdapterUnavailableError, TelemetryAdapterRegistry
from .intelligence import derive_signals, reconcile_action_center
from .models import TelemetryFact
from .store import TelemetryStore


@dataclass(frozen=True)
class CollectionResult:
    collection_id: str
    adapter: str
    scope_id: str
    outcome: str
    received: int
    added: int
    pruned: int
    signals: int
    resolved_actions: int
    evidence_complete: bool
    error_code: str | None = None


class TelemetryCollectionService:
    """Collect from one adapter; persist only normalized, safe evidence."""

    def __init__(
        self,
        workspace_root: str | Path,
        registry: TelemetryAdapterRegistry,
        *,
        store: TelemetryStore | None = None,
        notifications: NotificationStore | None = None,
        audit: AuditLog | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(workspace_root)
        self.registry = registry
        self.store = store or TelemetryStore(self.root)
        self.notifications = notifications or NotificationStore(self.root)
        self.audit = audit or AuditLog(self.root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def collect(
        self,
        adapter_name: str,
        *,
        scope_id: str,
        actor: str = "system",
        actor_roles=(),
    ) -> CollectionResult:
        name = str(adapter_name or "").strip()
        scope = str(scope_id or "").strip()
        if not scope or len(scope) > 160 or any(ord(c) < 32 for c in scope):
            raise ValueError("telemetry scope is invalid")
        adapter = self.registry.get(name)
        collection_id = f"collection:{uuid4().hex}"
        self.registry.mark_attempt(name)
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("telemetry collection clock must include timezone")
        try:
            received = tuple(adapter.collect(scope_id=scope))
            facts = self._validated_facts(
                received, adapter_name=name, scope_id=scope,
                collection_id=collection_id, now=now,
                retention_days=self.store.retention_days,
            )
            pruned = self.store.prune(now=now)
            added = self.store.ingest(facts)
            self.registry.mark_success(name, len(facts))
            # Reconcile against THIS provider snapshot, not retained history.
            # Historical facts stay available for trends, but a condition
            # absent from an explicitly complete fresh snapshot may recover.
            signals = derive_signals(facts, now=now)
            evidence_complete = bool(
                getattr(adapter, "evidence_complete", False)
            ) and len(facts) == len(received)
            resolved = reconcile_action_center(
                self.notifications, signals,
                evidence_complete=evidence_complete,
                scope_id=scope,
            )
            result = CollectionResult(
                collection_id, name, scope, "success", len(received), added,
                pruned, len(signals), resolved, evidence_complete,
            )
            self._audit(result, actor=actor, actor_roles=actor_roles)
            return result
        except Exception as error:
            code = (
                "provider-unavailable"
                if isinstance(error, AdapterUnavailableError)
                else "collection-invalid"
            )
            self.registry.mark_failure(name, error_code=code)
            result = CollectionResult(
                collection_id, name, scope, "failed", 0, 0, 0, 0, 0,
                False, code,
            )
            self._audit(result, actor=actor, actor_roles=actor_roles)
            if isinstance(error, AdapterUnavailableError):
                raise
            raise AdapterUnavailableError(
                f"{name} telemetry collection failed validation"
            ) from error

    @staticmethod
    def _validated_facts(
        values,
        *,
        adapter_name: str,
        scope_id: str,
        collection_id: str,
        now: datetime,
        retention_days: int,
    ) -> tuple[TelemetryFact, ...]:
        facts: list[TelemetryFact] = []
        for value in values:
            if not isinstance(value, TelemetryFact):
                raise TypeError("telemetry provider returned a non-fact value")
            if value.adapter != adapter_name or value.scope_id != scope_id:
                raise ValueError(
                    "telemetry provider returned mismatched provenance"
                )
            observed = datetime.fromisoformat(value.observed_at).astimezone(
                timezone.utc
            )
            if observed < now.astimezone(timezone.utc) - timedelta(
                days=retention_days
            ):
                continue
            if observed > now.astimezone(timezone.utc) + timedelta(minutes=5):
                continue
            facts.append(replace(value, collection_id=collection_id))
        return tuple(facts)

    def _audit(self, result: CollectionResult, *, actor: str, actor_roles) -> None:
        # Only counts and opaque references: provider errors and response
        # bodies never enter durable audit data.
        self.audit.append(AuditEvent.create(
            category="telemetry-collection",
            operation="collect",
            subject=result.adapter,
            actor=str(actor or "system"),
            actor_roles=actor_roles,
            scope_id=result.scope_id,
            outcome=result.outcome,
            source="telemetry",
            correlation_id=result.collection_id,
            after={
                "received": result.received,
                "added": result.added,
                "pruned": result.pruned,
                "signals": result.signals,
                "resolved_actions": result.resolved_actions,
                "evidence_complete": result.evidence_complete,
                "error_code": result.error_code,
            },
        ))
