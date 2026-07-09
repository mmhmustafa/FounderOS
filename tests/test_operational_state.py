"""Acceptance tests for PR-029 operational state intelligence."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.state import (
    OperationalStateDetector,
    render_state_report_json,
    render_state_report_markdown,
)
from founderos_runtime.cli import main

from tests.test_change_intelligence import device_entry, snapshot_dict


def iface(name: str, ip: str | None, status: str, protocol: str) -> dict:
    return {
        "name": name,
        "ip_address": ip,
        "status": status,
        "protocol_status": protocol,
        "description": None,
        "metadata": {},
    }


def device_with_interfaces(hostname: str, ip: str, interfaces: list[dict]) -> dict:
    entry = device_entry(hostname, ip, interfaces=0)
    entry["interfaces"] = interfaces
    return entry


def snapshot_with(hostname: str, interfaces: list[dict], snapshot_id: str) -> dict:
    return snapshot_dict(
        [device_with_interfaces(hostname, "10.10.10.1", interfaces)],
        snapshot_id=snapshot_id,
    )


class OperationalStateDetectorTests(unittest.TestCase):
    def compare(self, before_ifaces, after_ifaces, hostname="SW1"):
        previous = snapshot_with(hostname, before_ifaces, "atlas-topology:prev")
        current = snapshot_with(hostname, after_ifaces, "atlas-topology:curr")
        return OperationalStateDetector().compare(previous, current)

    def test_identical_state_has_no_changes(self) -> None:
        ifaces = [iface("Gi0/1", "10.10.10.1", "up", "up")]
        report = self.compare(ifaces, ifaces)
        self.assertEqual(0, report.change_count)
        self.assertEqual("Healthy", report.status)

    def test_status_up_to_down_is_high(self) -> None:
        report = self.compare(
            [iface("Gi0/1", "10.10.10.1", "up", "up")],
            [iface("Gi0/1", "10.10.10.1", "down", "up")],
        )
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("status", change.field)
        self.assertEqual("high", change.severity)
        self.assertEqual(("up", "down"), (change.previous_value, change.current_value))
        self.assertIn("SW1 interface Gi0/1 status changed from up to down", change.description)
        self.assertIn("cable, remote device, interface errors and spanning-tree", change.recommendation)
        self.assertEqual(1, report.interfaces_down)

    def test_status_up_to_admin_down_is_medium(self) -> None:
        report = self.compare(
            [iface("Gi0/1", "10.10.10.1", "up", "up")],
            [iface("Gi0/1", "10.10.10.1", "administratively_down", "up")],
        )
        change = report.changes[0]
        self.assertEqual("medium", change.severity)
        self.assertIn("administratively down", change.description)
        self.assertIn("administrative shutdown", change.recommendation)

    def test_protocol_change_is_reported_separately_and_high(self) -> None:
        report = self.compare(
            [iface("Gi0/1", "10.10.10.1", "up", "up")],
            [iface("Gi0/1", "10.10.10.1", "up", "down")],
        )
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("protocol", change.field)
        self.assertEqual("high", change.severity)
        self.assertIn("line protocol changed from up to down", change.description)
        self.assertIn("line protocol, keepalives", change.recommendation)

    def test_admin_shutdown_reports_status_and_protocol_separately(self) -> None:
        # An admin shutdown drops both status and protocol; each is its own
        # change, but the interface counts as down once.
        report = self.compare(
            [iface("Gi0/1", "10.10.10.1", "up", "up")],
            [iface("Gi0/1", "10.10.10.1", "administratively_down", "down")],
        )
        fields = {change.field: change.severity for change in report.changes}
        self.assertEqual({"status": "medium", "protocol": "high"}, fields)
        self.assertEqual(1, report.interfaces_down)

    def test_ip_change_is_medium(self) -> None:
        report = self.compare(
            [iface("Gi0/2", "10.10.10.1", "up", "up")],
            [iface("Gi0/2", "10.10.20.1", "up", "up")],
        )
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("ip_address", change.field)
        self.assertEqual("medium", change.severity)
        self.assertEqual(
            ("10.10.10.1", "10.10.20.1"),
            (change.previous_value, change.current_value),
        )

    def test_new_interface_is_low(self) -> None:
        report = self.compare(
            [iface("Gi0/1", "10.10.10.1", "up", "up")],
            [
                iface("Gi0/1", "10.10.10.1", "up", "up"),
                iface("Gi0/2", "10.10.20.1", "up", "up"),
            ],
        )
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("interface", change.field)
        self.assertEqual("added", change.change_type)
        self.assertEqual("low", change.severity)
        self.assertIn("newly detected", change.description)

    def test_removed_interface_is_medium(self) -> None:
        report = self.compare(
            [
                iface("Gi0/1", "10.10.10.1", "up", "up"),
                iface("Gi0/2", "10.10.20.1", "up", "up"),
            ],
            [iface("Gi0/1", "10.10.10.1", "up", "up")],
        )
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("interface", change.field)
        self.assertEqual("removed", change.change_type)
        self.assertEqual("medium", change.severity)
        self.assertIn("no longer present", change.description)

    def test_recovery_to_up_is_low(self) -> None:
        report = self.compare(
            [iface("Gi0/1", "10.10.10.1", "down", "down")],
            [iface("Gi0/1", "10.10.10.1", "up", "up")],
        )
        self.assertEqual({"low"}, {change.severity for change in report.changes})
        self.assertEqual(0, report.interfaces_down)

    def test_devices_matched_across_snapshots_by_hostname(self) -> None:
        previous = snapshot_dict(
            [
                device_with_interfaces("R1", "10.0.0.1", [iface("Gi0/2", "10.10.10.1", "up", "up")]),
                device_with_interfaces("SW1", "10.0.0.2", [iface("Gi0/1", None, "up", "up")]),
            ]
        )
        current = snapshot_dict(
            [
                device_with_interfaces("R1", "10.0.0.1", [iface("Gi0/2", "10.10.20.1", "up", "up")]),
                device_with_interfaces("SW1", "10.0.0.2", [iface("Gi0/1", None, "down", "down")]),
            ]
        )
        report = OperationalStateDetector().compare(previous, current)
        self.assertEqual({"R1", "SW1"}, set(report.devices_changed))
        self.assertEqual(1, report.interfaces_down)  # SW1 Gi0/1

    def test_report_is_deterministic(self) -> None:
        before = [iface("Gi0/1", "10.10.10.1", "up", "up")]
        after = [iface("Gi0/1", "10.10.10.1", "down", "up")]
        first = self.compare(before, after)
        second = self.compare(before, after)
        self.assertEqual(first, second)
        self.assertEqual(
            render_state_report_json(first), render_state_report_json(second)
        )


class StateReportRenderingTests(unittest.TestCase):
    def build_report(self):
        previous = snapshot_dict(
            [
                device_with_interfaces("SW1", "10.0.0.2", [iface("Gi0/1", None, "up", "up")]),
                device_with_interfaces("R1", "10.0.0.1", [iface("Gi0/2", "10.10.10.1", "up", "up")]),
            ],
            snapshot_id="atlas-topology:prev",
        )
        current = snapshot_dict(
            [
                device_with_interfaces("SW1", "10.0.0.2", [iface("Gi0/1", None, "down", "up")]),
                device_with_interfaces("R1", "10.0.0.1", [iface("Gi0/2", "10.10.20.1", "up", "up")]),
            ],
            snapshot_id="atlas-topology:curr",
        )
        return OperationalStateDetector().compare(
            previous, current, previous_ref="prev", current_ref="curr"
        )

    def test_json_generation(self) -> None:
        data = json.loads(render_state_report_json(self.build_report()))
        self.assertEqual(2, data["change_count"])
        self.assertEqual(1, data["interfaces_down"])
        self.assertEqual(1, data["active_issue_count"])  # SW1 down; IP change is informational
        self.assertEqual(0, data["recovery_count"])
        self.assertEqual("Critical", data["current_health"])  # a hard down is high severity
        self.assertEqual("Critical", data["status"])
        self.assertEqual(["R1", "SW1"], data["devices_changed"])
        for change in data["changes"]:
            for field in ("hostname", "interface", "field", "severity", "event", "description", "recommendation"):
                self.assertIn(field, change)

    def test_markdown_generation_matches_spec_shape(self) -> None:
        markdown = render_state_report_markdown(self.build_report())
        self.assertIn("# Atlas Operational Change Report", markdown)
        self.assertIn("Current health: Critical", markdown)
        self.assertIn("Active issues: 1", markdown)
        self.assertIn("Interfaces currently down: 1", markdown)
        self.assertIn("## Active Issues", markdown)
        self.assertIn("## Events (history)", markdown)
        self.assertIn("[FAILURE] SW1 Gi0/1", markdown)
        self.assertIn("status: up → down", markdown)
        self.assertIn("[INFORMATIONAL] R1 Gi0/2", markdown)


class StateDiffCliTests(unittest.TestCase):
    def write_snapshot(self, path: Path, hostname: str, status: str, ip: str) -> None:
        snapshot = snapshot_with(
            hostname, [iface("Gi0/1", ip, status, status)], "atlas-topology:x"
        )
        # snapshot_with builds a synthetic content-address; state-diff does not
        # re-validate it, so a plain dict file is enough.
        path.write_text(json.dumps(snapshot), encoding="utf-8")

    def invoke(self, *arguments, workdir: Path):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                list(arguments),
                atlas_state_diff_json_output=workdir / "state_change_report.json",
                atlas_state_diff_markdown_output=workdir / "state_change_report.md",
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_path_mode_generates_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            previous = workdir / "previous.json"
            current = workdir / "current.json"
            self.write_snapshot(previous, "SW1", "up", "10.10.10.1")
            self.write_snapshot(current, "SW1", "down", "10.10.10.1")
            code, output, error = self.invoke(
                "atlas", "state-diff", str(previous), str(current), workdir=workdir
            )
            self.assertEqual(0, code, error)
            self.assertIn("Atlas Operational Change Report", output)
            self.assertIn("Interfaces currently down: 1", output)
            self.assertIn("Current health: Critical", output)
            self.assertIn("[failure] SW1 Gi0/1", output)
            report = json.loads(
                (workdir / "state_change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, report["interfaces_down"])
            self.assertEqual("Critical", report["current_health"])
            self.assertIn(
                "# Atlas Operational Change Report",
                (workdir / "state_change_report.md").read_text(encoding="utf-8"),
            )

    def test_missing_file_is_a_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error = self.invoke(
                "atlas", "state-diff", str(workdir / "nope.json"),
                str(workdir / "nope.json"), workdir=workdir,
            )
            self.assertEqual(1, code)
            self.assertIn("Could not read snapshot file", error)

    def test_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, _, error = self.invoke("atlas", "state-diff", workdir=Path(tmp))
            self.assertEqual(2, code)
            self.assertIn("Usage: founderos atlas state-diff", error)

    def test_help_lists_state_diff(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("founderos atlas state-diff", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
