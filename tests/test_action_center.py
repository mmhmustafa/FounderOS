"""Operational Action Center persistence and lifecycle contracts."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from founderos_atlas.notifications import (
    STATUS_ACKNOWLEDGED,
    STATUS_IN_PROGRESS,
    STATUS_RESOLVED,
    STATUS_SNOOZED,
    STATUS_UNREAD,
    NotificationStore,
)


class ActionCenterStoreTests(unittest.TestCase):
    def test_repeated_condition_is_grouped_and_counts_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NotificationStore(tmp)
            created = store.notify(
                kind="policy-regression",
                title="NTP policy regressed",
                audience="role:policy-manager",
                href="/policy?policy=ntp",
                dedupe_key="policy:ntp:site:delhi",
                priority="high",
                scope_id="delhi",
                source_refs=("policy-result:ntp:r1",),
            )
            self.assertIsNotNone(created)
            duplicate = store.notify(
                kind="policy-regression",
                title="NTP policy still failing",
                audience="role:policy-manager",
                href="/policy?policy=ntp",
                dedupe_key="policy:ntp:site:delhi",
                priority="high",
                scope_id="delhi",
                source_refs=("policy-result:ntp:r1", "policy-result:ntp:r2"),
            )
            self.assertIsNone(duplicate)
            items = store.for_principal("alice", ("policy-manager",))
            self.assertEqual(1, len(items))
            self.assertEqual(2, items[0].occurrences)
            self.assertEqual(2, len(items[0].source_refs))

    def test_resolution_and_recurrence_preserve_one_durable_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NotificationStore(tmp)
            created = store.notify(
                kind="discovery-failed",
                title="Delhi discovery failed",
                audience="alice",
                dedupe_key="discovery:delhi",
            )
            store.set_status(
                created.notification_id,
                STATUS_RESOLVED,
                expected_revision=created.revision,
                reason="A later run succeeded.",
            )
            reopened = store.notify(
                kind="discovery-failed",
                title="Delhi discovery failed again",
                audience="alice",
                dedupe_key="discovery:delhi",
            )
            self.assertIsNotNone(reopened)
            self.assertEqual(created.notification_id, reopened.notification_id)
            self.assertEqual(STATUS_UNREAD, reopened.status)
            self.assertEqual(1, reopened.recurrence_count)
            self.assertIsNone(reopened.resolved_at)

    def test_stale_or_incomplete_evidence_never_auto_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NotificationStore(tmp)
            store.notify(
                kind="edit-conflict",
                title="Identity conflict",
                audience="role:network-operator",
                dedupe_key="identity:r1",
            )
            self.assertEqual(
                0,
                store.reconcile(
                    kind="edit-conflict",
                    audience="role:network-operator",
                    active_dedupe_keys=(),
                    evidence_complete=False,
                ),
            )
            self.assertEqual(
                0,
                store.reconcile(
                    kind="edit-conflict",
                    audience="role:network-operator",
                    active_dedupe_keys=(),
                    evidence_complete=True,
                    evidence_stale=True,
                ),
            )
            self.assertEqual(
                1,
                store.reconcile(
                    kind="edit-conflict",
                    audience="role:network-operator",
                    active_dedupe_keys=(),
                    evidence_complete=True,
                    evidence_stale=False,
                ),
            )
            items = store.for_principal(
                "alice", ("network-operator",), include_done=True
            )
            self.assertEqual(STATUS_RESOLVED, items[0].status)

    def test_optimistic_revision_and_transition_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NotificationStore(tmp)
            item = store.notify(
                kind="assignment",
                title="Investigate core",
                audience="alice",
            )
            store.set_status(
                item.notification_id,
                STATUS_ACKNOWLEDGED,
                expected_revision=item.revision,
                owner="alice",
            )
            acknowledged = store.for_principal("alice", ())[0]
            self.assertEqual(STATUS_ACKNOWLEDGED, acknowledged.status)
            self.assertEqual("alice", acknowledged.owner)
            with self.assertRaisesRegex(RuntimeError, "changed"):
                store.set_status(
                    item.notification_id,
                    STATUS_IN_PROGRESS,
                    expected_revision=item.revision,
                )

    def test_filters_are_principal_scoped_and_priority_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NotificationStore(tmp)
            store.notify(
                kind="stale-evidence",
                title="Low",
                audience="alice",
                priority="low",
                owner="alice",
            )
            store.notify(
                kind="incident",
                title="Critical",
                audience="alice",
                priority="critical",
                owner="alice",
            )
            store.notify(
                kind="incident",
                title="Other user",
                audience="bob",
                priority="critical",
            )
            items = store.for_principal("alice", (), mine=True)
            self.assertEqual(["Critical", "Low"], [item.title for item in items])

    def test_snoozed_item_is_hidden_until_wake_time_and_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NotificationStore(tmp)
            item = store.notify(
                kind="assignment",
                title="Review later",
                audience="alice",
            )
            wake = (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(timespec="seconds")
            store.set_status(
                item.notification_id,
                STATUS_SNOOZED,
                expected_revision=item.revision,
                due_at=wake,
            )
            self.assertEqual([], store.for_principal("alice", ()))
            snoozed = store.for_principal(
                "alice", (), status=STATUS_SNOOZED
            )
            self.assertEqual(1, len(snoozed))
            self.assertEqual(wake, snoozed[0].due_at)


if __name__ == "__main__":
    unittest.main()
