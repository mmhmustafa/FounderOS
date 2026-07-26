"""Canonical telemetry adapters and bounded persistence."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from founderos_atlas.telemetry import (
    FACT_BGP_STATE,
    FACT_INTERFACE_UTILIZATION,
    AdapterUnavailableError,
    MappingTelemetryAdapter,
    TelemetryAdapterRegistry,
    TelemetryCollectionService,
    TelemetryStore,
    derive_signals,
    fact,
    reconcile_action_center,
)
from founderos_atlas.audit import AuditLog
from founderos_atlas.notifications import (
    STATUS_RESOLVED,
    STATUS_UNREAD,
    NotificationStore,
)


UTC = timezone.utc


class TelemetryFoundationTests(unittest.TestCase):
    def test_mapping_adapter_preserves_provenance(self) -> None:
        adapter = MappingTelemetryAdapter(
            "snmp-v3",
            lambda: [{
                "kind": FACT_INTERFACE_UTILIZATION,
                "entity_id": "r1:Gi0/1",
                "metric": "utilization",
                "value": 42.5,
                "unit": "percent",
                "observed_at": "2026-07-26T10:00:00+00:00",
                "metadata": {"if_index": 7},
            }],
            source="snmp",
        )
        values = adapter.collect(scope_id="delhi")
        self.assertEqual(1, len(values))
        self.assertEqual("snmp", values[0].source)
        self.assertEqual("snmp-v3", values[0].adapter)
        self.assertEqual("delhi", values[0].scope_id)

    def test_provider_error_is_explicit_without_leaking_detail(self) -> None:
        def failed():
            raise RuntimeError("token=do-not-leak")

        adapter = MappingTelemetryAdapter("cloud", failed, source="api")
        with self.assertRaisesRegex(
            AdapterUnavailableError, "provider is unavailable"
        ) as raised:
            adapter.collect(scope_id="enterprise")
        self.assertNotIn("do-not-leak", str(raised.exception))

    def test_deduplication_retention_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TelemetryStore(tmp, retention_days=2)
            old = fact(
                kind=FACT_BGP_STATE,
                entity_id="r1->r2",
                metric="session",
                value="established",
                unit="state",
                observed_at="2026-07-20T10:00:00+00:00",
                source="cli",
                adapter="ios",
                scope_id="delhi",
            )
            current = fact(
                kind=FACT_INTERFACE_UTILIZATION,
                entity_id="r1:Gi0/1",
                metric="utilization",
                value=55,
                unit="percent",
                observed_at="2026-07-26T10:00:00+00:00",
                source="snmp",
                adapter="snmp-v3",
                scope_id="delhi",
            )
            self.assertEqual(2, store.ingest((old, current)))
            self.assertEqual(0, store.ingest((current,)))
            self.assertEqual(2, len(TelemetryStore(tmp).query()))
            removed = store.prune(
                now=datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
            )
            self.assertEqual(1, removed)
            self.assertEqual([current.fact_id], [
                item.fact_id for item in store.query()
            ])

    def test_out_of_order_ingest_sorts_queries_and_downsamples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TelemetryStore(tmp)
            base = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            values = [
                fact(
                    kind=FACT_INTERFACE_UTILIZATION,
                    entity_id="r1:Gi0/1",
                    metric="utilization",
                    value=value,
                    unit="percent",
                    observed_at=(base + timedelta(minutes=minute)).isoformat(),
                    source="snmp",
                    adapter="snmp-v3",
                    scope_id="delhi",
                )
                for minute, value in ((40, 60), (5, 20), (20, 40))
            ]
            store.ingest(values)
            observed = [item.value for item in store.query()]
            self.assertEqual([60, 40, 20], observed)
            buckets = store.downsample(
                kind=FACT_INTERFACE_UTILIZATION, bucket_minutes=60
            )
            self.assertEqual(1, len(buckets))
            self.assertEqual(40, buckets[0]["average"])
            self.assertEqual(3, buckets[0]["samples"])

    def test_store_is_bounded_under_large_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TelemetryStore(tmp, max_facts=100)
            base = datetime(2026, 7, 26, tzinfo=UTC)
            values = [
                fact(
                    kind=FACT_INTERFACE_UTILIZATION,
                    entity_id=f"r{index}:eth0",
                    metric="utilization",
                    value=index,
                    unit="percent",
                    observed_at=(base + timedelta(seconds=index)).isoformat(),
                    source="fixture",
                    adapter="load-test",
                    scope_id="enterprise",
                )
                for index in range(1000)
            ]
            self.assertEqual(1000, store.ingest(values))
            self.assertEqual(100, len(store.query(limit=1000)))

    def test_operational_signals_use_state_and_explicit_thresholds(self) -> None:
        now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
        values = [
            fact(
                kind=FACT_BGP_STATE,
                entity_id="edge-1",
                metric="neighbor:192.0.2.1",
                value="idle",
                unit="state",
                observed_at=now.isoformat(),
                source="provider:one",
                adapter="fixture",
                scope_id="lab",
            ),
            fact(
                kind=FACT_INTERFACE_UTILIZATION,
                entity_id="edge-1:Gi0/0",
                metric="utilization",
                value=95,
                unit="percent",
                observed_at=now.isoformat(),
                source="provider:one",
                adapter="fixture",
                scope_id="lab",
                metadata={"critical_threshold": 90},
            ),
            fact(
                kind=FACT_INTERFACE_UTILIZATION,
                entity_id="edge-2:Gi0/0",
                metric="utilization",
                value=75,
                unit="percent",
                observed_at=now.isoformat(),
                source="provider:one",
                adapter="fixture",
                scope_id="lab",
            ),
        ]
        signals = derive_signals(values, now=now)
        self.assertEqual(2, len(signals))
        self.assertTrue(all(item.severity == "critical" for item in signals))

    def test_downsample_supports_multi_hour_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TelemetryStore(tmp)
            store.ingest([fact(
                kind=FACT_INTERFACE_UTILIZATION,
                entity_id="wan",
                metric="utilization",
                value=10,
                unit="percent",
                observed_at="2026-07-26T10:12:00+00:00",
                source="fixture",
                adapter="fixture",
                scope_id="lab",
            )])
            self.assertEqual(
                1,
                len(store.downsample(
                    kind=FACT_INTERFACE_UTILIZATION,
                    bucket_minutes=120,
                )),
            )

    def test_secret_shaped_metadata_is_redacted_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TelemetryStore(tmp)
            value = fact(
                kind=FACT_BGP_STATE,
                entity_id="edge-1",
                metric="state",
                value="established",
                unit="state",
                observed_at="2026-07-26T10:00:00+00:00",
                source="fixture",
                adapter="fixture",
                scope_id="lab",
                metadata={
                    "neighbor": "192.0.2.1",
                    "api_token": "CANARY-NOT-FOR-DISK",
                    "apiKey": "CAMEL-CASE-KEY-CANARY",
                    "private-key": "PRIVATE-KEY-CANARY",
                },
            )
            store.ingest((value,))
            raw = store.path.read_text(encoding="utf-8")
            self.assertNotIn("CANARY-NOT-FOR-DISK", raw)
            self.assertNotIn("CAMEL-CASE-KEY-CANARY", raw)
            self.assertNotIn("PRIVATE-KEY-CANARY", raw)
            self.assertIn("[redacted]", raw)

    def test_registry_requires_explicit_unique_adapters_and_tracks_status(
        self,
    ) -> None:
        adapter = MappingTelemetryAdapter(
            "snmp-v3", lambda: (), source="snmp"
        )
        registry = TelemetryAdapterRegistry((adapter,))
        self.assertEqual(("snmp-v3",), registry.names())
        self.assertEqual(
            "configured", registry.statuses()["snmp-v3"]["state"]
        )
        with self.assertRaisesRegex(ValueError, "registered"):
            registry.register(adapter)
        with self.assertRaisesRegex(
            AdapterUnavailableError, "not configured"
        ):
            registry.get("missing")

    def test_collection_is_bounded_audited_and_preserves_provenance(
        self,
    ) -> None:
        now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
        adapter = MappingTelemetryAdapter(
            "snmp-v3",
            lambda: [{
                "kind": FACT_INTERFACE_UTILIZATION,
                "entity_id": "edge-1:Gi0/0",
                "metric": "utilization",
                "value": 96,
                "unit": "percent",
                "observed_at": now.isoformat(),
                "provider_ref": "poll:opaque-42",
                "metadata": {
                    "warning_threshold": 80,
                    "critical_threshold": 90,
                    "api_token": "must-not-persist",
                },
            }],
            source="snmp",
        )
        with tempfile.TemporaryDirectory() as tmp:
            registry = TelemetryAdapterRegistry((adapter,))
            store = TelemetryStore(tmp, retention_days=2, max_facts=20)
            store.ingest((fact(
                kind=FACT_BGP_STATE,
                entity_id="old-edge",
                metric="session",
                value="idle",
                unit="state",
                observed_at="2026-07-20T10:00:00+00:00",
                source="fixture",
                adapter="fixture",
                scope_id="delhi",
            ),))
            service = TelemetryCollectionService(
                tmp, registry, store=store, clock=lambda: now,
            )
            result = service.collect(
                "snmp-v3", scope_id="delhi", actor="alice",
                actor_roles=("network-operator",),
            )
            self.assertEqual("success", result.outcome)
            self.assertEqual(1, result.pruned)
            stored = store.query()
            self.assertEqual(1, len(stored))
            self.assertEqual(result.collection_id, stored[0].collection_id)
            self.assertEqual("poll:opaque-42", stored[0].provider_ref)
            self.assertEqual("[redacted]", stored[0].metadata["api_token"])
            self.assertEqual(
                "available", registry.statuses()["snmp-v3"]["state"]
            )
            event = AuditLog(tmp).events(category="telemetry-collection")[0]
            self.assertEqual("alice", event.actor)
            self.assertEqual(result.collection_id, event.correlation_id)
            action = NotificationStore(tmp).for_principal(
                "alice", ("network-operator",)
            )[0]
            self.assertEqual(STATUS_UNREAD, action.status)
            self.assertIn(stored[0].fact_id, action.source_refs)
            persisted = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    store.path, AuditLog(tmp).path,
                    NotificationStore(tmp).path,
                )
            )
            self.assertNotIn("must-not-persist", persisted)

    def test_failed_collection_exposes_only_safe_error_code(self) -> None:
        def failed():
            raise RuntimeError("Bearer provider-secret")

        adapter = MappingTelemetryAdapter("cloud", failed, source="api")
        with tempfile.TemporaryDirectory() as tmp:
            registry = TelemetryAdapterRegistry((adapter,))
            service = TelemetryCollectionService(
                tmp, registry,
                clock=lambda: datetime(2026, 7, 26, tzinfo=UTC),
            )
            with self.assertRaisesRegex(
                AdapterUnavailableError, "provider is unavailable"
            ):
                service.collect("cloud", scope_id="enterprise")
            status = registry.statuses()["cloud"]
            self.assertEqual("unavailable", status["state"])
            self.assertEqual("provider-unavailable", status["error_code"])
            event = AuditLog(tmp).events(category="telemetry-collection")[0]
            self.assertEqual("failed", event.outcome)
            self.assertNotIn(
                "provider-secret",
                AuditLog(tmp).path.read_text(encoding="utf-8"),
            )

    def test_action_reconciliation_is_isolated_to_collected_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notifications = NotificationStore(tmp)
            for scope in ("delhi", "mumbai"):
                notifications.notify(
                    kind="telemetry-signal",
                    title=f"{scope} signal",
                    audience="role:network-operator",
                    scope_id=scope,
                    dedupe_key=f"telemetry:{scope}:edge:fact",
                )
            self.assertEqual(
                1,
                reconcile_action_center(
                    notifications, (), evidence_complete=True,
                    scope_id="delhi",
                ),
            )
            items = notifications.for_principal(
                "alice", ("network-operator",), include_done=True
            )
            states = {item.scope_id: item.status for item in items}
            self.assertEqual(STATUS_RESOLVED, states["delhi"])
            self.assertEqual(STATUS_UNREAD, states["mumbai"])

    def test_partial_collection_never_infers_recovery(self) -> None:
        now = datetime(2026, 7, 26, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            notifications = NotificationStore(tmp)
            notifications.notify(
                kind="telemetry-signal",
                title="Edge is down",
                audience="role:network-operator",
                scope_id="delhi",
                dedupe_key="telemetry:delhi:edge:fact",
            )
            partial = MappingTelemetryAdapter(
                "partial", lambda: (), source="snmp"
            )
            complete = MappingTelemetryAdapter(
                "complete", lambda: (), source="rest",
                evidence_complete=True,
            )
            registry = TelemetryAdapterRegistry((partial, complete))
            service = TelemetryCollectionService(
                tmp, registry, notifications=notifications,
                clock=lambda: now,
            )
            first = service.collect("partial", scope_id="delhi")
            self.assertFalse(first.evidence_complete)
            self.assertEqual(
                STATUS_UNREAD,
                notifications.for_principal(
                    "alice", ("network-operator",), include_done=True
                )[0].status,
            )
            second = service.collect("complete", scope_id="delhi")
            self.assertTrue(second.evidence_complete)
            self.assertEqual(
                STATUS_RESOLVED,
                notifications.for_principal(
                    "alice", ("network-operator",), include_done=True
                )[0].status,
            )


if __name__ == "__main__":
    unittest.main()
