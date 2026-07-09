"""Regression tests for PR-030.1 Atlas Alpha Stabilization (three goals)."""

from __future__ import annotations

from pathlib import Path
import tomllib
import unittest

from founderos_atlas.config_intelligence import (
    compare_configurations,
    is_dynamic_metadata,
)
from founderos_atlas.state import (
    EVENT_FAILURE,
    EVENT_RECOVERY,
    OperationalStateDetector,
)

from tests.test_change_intelligence import device_entry, snapshot_dict


# ----------------------------------------------------------------------------
# GOAL 1 — credentials extra packaging
# ----------------------------------------------------------------------------


class CredentialsExtraPackagingTests(unittest.TestCase):
    def _pyproject(self) -> dict:
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as handle:
            return tomllib.load(handle)

    def test_credentials_extra_is_declared(self) -> None:
        extras = self._pyproject()["project"]["optional-dependencies"]
        self.assertIn("credentials", extras)

    def test_credentials_extra_requires_keyring(self) -> None:
        extras = self._pyproject()["project"]["optional-dependencies"]
        requirements = " ".join(extras["credentials"]).lower()
        self.assertIn("keyring", requirements)

    def test_no_plaintext_credential_dependency(self) -> None:
        # The credentials extra must not pull an insecure plaintext store.
        extras = self._pyproject()["project"]["optional-dependencies"]
        joined = " ".join(extras["credentials"]).lower()
        for forbidden in ("plaintext", "cleartext"):
            self.assertNotIn(forbidden, joined)


# ----------------------------------------------------------------------------
# GOAL 2 — current health vs historical recovery events
# ----------------------------------------------------------------------------


def _iface(name: str, status: str, protocol: str, ip: str | None = None) -> dict:
    return {
        "name": name,
        "ip_address": ip,
        "status": status,
        "protocol_status": protocol,
        "description": None,
        "metadata": {},
    }


def _snapshot(hostname: str, interfaces: list[dict], snapshot_id: str) -> dict:
    device = device_entry(hostname, "10.0.0.2", interfaces=0)
    device["interfaces"] = interfaces
    return snapshot_dict([device], snapshot_id=snapshot_id)


class CurrentHealthVersusHistoryTests(unittest.TestCase):
    def compare(self, before, after):
        return OperationalStateDetector().compare(
            _snapshot("SW1", before, "atlas-topology:prev"),
            _snapshot("SW1", after, "atlas-topology:curr"),
        )

    def test_failure_event_makes_current_health_not_healthy(self) -> None:
        report = self.compare(
            [_iface("Gi0/1", "up", "up")],
            [_iface("Gi0/1", "administratively_down", "down")],
        )
        self.assertNotEqual("Healthy", report.current_health)
        self.assertGreaterEqual(report.active_issue_count, 1)
        self.assertEqual(1, report.interfaces_down)

    def test_recovery_returns_health_to_healthy(self) -> None:
        report = self.compare(
            [_iface("Gi0/1", "administratively_down", "down")],
            [_iface("Gi0/1", "up", "up")],
        )
        # Two recovery events (status + protocol), but the current state is up.
        self.assertEqual("Healthy", report.current_health)
        self.assertEqual(0, report.active_issue_count)
        self.assertEqual(0, report.interfaces_down)

    def test_recovery_is_preserved_in_history(self) -> None:
        report = self.compare(
            [_iface("Gi0/1", "administratively_down", "down")],
            [_iface("Gi0/1", "up", "up")],
        )
        self.assertGreaterEqual(report.change_count, 1)
        self.assertGreaterEqual(len(report.recoveries), 1)
        events = {change.event for change in report.changes}
        self.assertEqual({EVENT_RECOVERY}, events)

    def test_historical_changes_alone_do_not_cause_attention_required(self) -> None:
        # Recovery + an informational IP change: history is non-empty, but no
        # active issue remains, so status must be Healthy.
        report = self.compare(
            [_iface("Gi0/1", "down", "down", ip="10.10.10.1")],
            [_iface("Gi0/1", "up", "up", ip="10.10.20.1")],
        )
        self.assertTrue(report.changes)  # history preserved
        self.assertEqual("Healthy", report.current_health)
        self.assertEqual("Healthy", report.status)

    def test_failure_event_type_is_tagged(self) -> None:
        report = self.compare(
            [_iface("Gi0/1", "up", "up")],
            [_iface("Gi0/1", "up", "down")],  # protocol down while up
        )
        self.assertEqual(EVENT_FAILURE, report.changes[0].event)
        self.assertTrue(report.changes[0].is_active_issue)


# ----------------------------------------------------------------------------
# GOAL 3 — dynamic Cisco config metadata filtering
# ----------------------------------------------------------------------------


BEFORE_CONFIG = """\
Building configuration...

Current configuration : 3122 bytes
!
! Last configuration change at 00:13:43 UTC Thu Jul 9 2026
!
hostname SW1
!
interface GigabitEthernet0/1
 description uplink
 shutdown
!
end
"""

AFTER_CONFIG_ONLY_METADATA = """\
Building configuration...

Current configuration : 3132 bytes
!
! Last configuration change at 00:40:51 UTC Thu Jul 9 2026
!
hostname SW1
!
interface GigabitEthernet0/1
 description uplink
 shutdown
!
end
"""

AFTER_CONFIG_NO_SHUTDOWN = """\
Building configuration...

Current configuration : 3140 bytes
!
! Last configuration change at 00:41:10 UTC Thu Jul 9 2026
!
hostname SW1
!
interface GigabitEthernet0/1
 description uplink
!
end
"""


class DynamicMetadataFilterTests(unittest.TestCase):
    def test_byte_count_line_is_dynamic_metadata(self) -> None:
        self.assertTrue(is_dynamic_metadata("Current configuration : 3122 bytes"))

    def test_last_change_timestamp_is_dynamic_metadata(self) -> None:
        self.assertTrue(
            is_dynamic_metadata(
                "! Last configuration change at 00:13:43 UTC Thu Jul 9 2026"
            )
        )

    def test_real_config_lines_are_not_dynamic_metadata(self) -> None:
        for line in (
            "hostname SW1",
            "interface GigabitEthernet0/1",
            " shutdown",
            " description Current configuration backup link",
        ):
            self.assertFalse(is_dynamic_metadata(line), line)

    def test_only_metadata_change_reports_zero_changes(self) -> None:
        report = compare_configurations(
            BEFORE_CONFIG, AFTER_CONFIG_ONLY_METADATA, hostname="SW1"
        )
        self.assertEqual(0, report.change_count)

    def test_shutdown_removal_is_the_single_meaningful_change(self) -> None:
        report = compare_configurations(
            BEFORE_CONFIG, AFTER_CONFIG_NO_SHUTDOWN, hostname="SW1"
        )
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("interfaces", change.category)
        self.assertEqual("interface GigabitEthernet0/1", change.raw_diff_reference)
        self.assertIn(" shutdown", change.removed_lines)
        # No byte-count or timestamp lines leaked into the report.
        serialized = " ".join(change.removed_lines + change.added_lines)
        self.assertNotIn("bytes", serialized)
        self.assertNotIn("Last configuration change", serialized)

    def test_no_shutdown_still_detected_without_metadata_noise(self) -> None:
        # Symmetric: adding shutdown is detected too.
        report = compare_configurations(
            AFTER_CONFIG_NO_SHUTDOWN, BEFORE_CONFIG, hostname="SW1"
        )
        self.assertEqual(1, report.change_count)
        self.assertIn(" shutdown", report.changes[0].added_lines)


if __name__ == "__main__":
    unittest.main()
