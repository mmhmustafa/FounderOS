"""Acceptance tests for PR-022 change intelligence."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.change import (
    ChangeDetector,
    render_change_report_json,
    render_change_report_markdown,
)
from founderos_atlas.journeys import MorningBriefJourney, build_morning_brief
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.topology import TopologySnapshotExporter
from founderos_atlas.visualization import TopologyRenderer
from founderos_runtime.cli import main

from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


def device_entry(
    hostname: str,
    ip: str,
    *,
    platform: str = "IOSv",
    os_version: str = "15.9(3)M12",
    serial: str | None = None,
    interfaces: int = 2,
    device_id: str | None = None,
) -> dict:
    return {
        "device_id": device_id or f"cisco-ios:{hostname.casefold()}",
        "hostname": hostname,
        "management_ip": ip,
        "vendor": "cisco",
        "platform": platform,
        "os_name": "IOS",
        "os_version": os_version,
        "serial_number": serial if serial is not None else f"SER-{hostname.upper()}",
        "interfaces": [{"name": f"GigabitEthernet0/{index}"} for index in range(interfaces)],
        "metadata": {},
    }


def edge_entry(
    local_id: str,
    remote_hostname: str,
    local_interface: str = "GigabitEthernet0/1",
    remote_interface: str = "GigabitEthernet0/2",
) -> dict:
    return {
        "local_device_id": local_id,
        "local_interface": local_interface,
        "remote_hostname": remote_hostname,
        "remote_interface": remote_interface,
        "remote_management_ip": None,
        "protocol": "cdp",
        "metadata": {},
    }


def snapshot_dict(
    devices: list[dict],
    edges: list[dict] | None = None,
    *,
    snapshot_id: str = "atlas-topology:test",
    metadata: dict | None = None,
) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "devices": devices,
        "edges": edges or [],
        "warnings": [],
        "metadata": metadata or {},
    }


def two_device_snapshot() -> dict:
    return snapshot_dict(
        [device_entry("R1", "10.0.0.1"), device_entry("SW1", "10.0.0.2")],
        [
            edge_entry("cisco-ios:r1", "SW1"),
            edge_entry("cisco-ios:sw1", "R1", "GigabitEthernet0/2", "GigabitEthernet0/1"),
        ],
    )


class ChangeDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = ChangeDetector()

    def test_identical_snapshots_produce_no_changes(self) -> None:
        report = self.detector.compare(two_device_snapshot(), two_device_snapshot())
        self.assertEqual(0, report.change_count)
        self.assertEqual((), report.changes)
        self.assertEqual({"high": 0, "medium": 0, "low": 0, "info": 0}, report.severity_counts)

    def test_new_device_detected_without_neighbor_noise(self) -> None:
        previous = snapshot_dict([device_entry("R1", "10.0.0.1")])
        current = two_device_snapshot()
        report = self.detector.compare(previous, current)
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual(("device", "low", "SW1"), (change.category, change.severity, change.subject))
        self.assertIn("discovered for the first time", change.description)
        self.assertEqual(("SW1",), report.new_devices)

    def test_removed_device_detected(self) -> None:
        previous = two_device_snapshot()
        current = snapshot_dict([device_entry("R1", "10.0.0.1")])
        report = self.detector.compare(previous, current)
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual(("device", "high", "SW1"), (change.category, change.severity, change.subject))
        self.assertIn("no longer discovered", change.description)
        self.assertIn("10.0.0.2", change.recommendation)
        self.assertEqual(("SW1",), report.removed_devices)

    def test_hostname_change_is_a_rename_not_remove_plus_add(self) -> None:
        previous = snapshot_dict(
            [device_entry("R1", "10.0.0.1", serial="SER-STABLE"), device_entry("SW1", "10.0.0.2")],
            [edge_entry("cisco-ios:r1", "SW1")],
        )
        current = snapshot_dict(
            [
                device_entry("CORE1", "10.0.0.1", serial="SER-STABLE", device_id="cisco-ios:core1"),
                device_entry("SW1", "10.0.0.2"),
            ],
            [edge_entry("cisco-ios:core1", "SW1")],
        )
        report = self.detector.compare(previous, current)
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("hostname", change.category)
        self.assertEqual("medium", change.severity)
        self.assertEqual("R1 was renamed to CORE1", change.description)
        self.assertEqual(("R1", "CORE1"), (change.previous_value, change.current_value))
        self.assertEqual((), report.new_devices)
        self.assertEqual((), report.removed_devices)
        self.assertEqual(("CORE1",), report.changed_devices)

    def test_management_ip_platform_and_os_changes(self) -> None:
        # Interface-level change is operational intelligence, not topology —
        # the topology detector reports device attributes only.
        previous = snapshot_dict([device_entry("R1", "10.0.0.1")])
        current = snapshot_dict(
            [
                device_entry(
                    "R1",
                    "10.0.0.99",
                    platform="ISR4451",
                    os_version="17.9.4a",
                    interfaces=4,
                )
            ]
        )
        report = self.detector.compare(previous, current)
        by_category = {change.category: change for change in report.changes}
        self.assertEqual(
            {"management-ip", "platform", "os-version"}, set(by_category)
        )
        self.assertEqual("medium", by_category["management-ip"].severity)
        self.assertEqual("high", by_category["platform"].severity)
        self.assertEqual("medium", by_category["os-version"].severity)
        self.assertNotIn("interface", by_category)
        self.assertEqual(("R1",), report.changed_devices)

    def test_lost_neighbor_matches_spec_example(self) -> None:
        previous = two_device_snapshot()
        current = snapshot_dict(
            [device_entry("R1", "10.0.0.1"), device_entry("SW1", "10.0.0.2")]
        )
        report = self.detector.compare(previous, current)
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("neighbor", change.category)
        self.assertEqual("medium", change.severity)
        self.assertEqual("R1 lost neighbor SW1", change.description)
        self.assertIn("Verify physical connectivity or CDP", change.recommendation)

    def test_gained_neighbor_is_low_severity(self) -> None:
        previous = snapshot_dict(
            [device_entry("R1", "10.0.0.1"), device_entry("SW1", "10.0.0.2")]
        )
        report = self.detector.compare(previous, two_device_snapshot())
        self.assertEqual(1, report.change_count)
        self.assertEqual("R1 gained neighbor SW1", report.changes[0].description)
        self.assertEqual("low", report.changes[0].severity)

    def test_directed_edge_pair_reports_one_neighbor_change(self) -> None:
        # Both CDP directions disappear; exactly one logical change is reported.
        previous = two_device_snapshot()
        current = snapshot_dict(
            [device_entry("R1", "10.0.0.1"), device_entry("SW1", "10.0.0.2")]
        )
        report = self.detector.compare(previous, current)
        self.assertEqual(1, len([c for c in report.changes if c.category == "neighbor"]))

    def test_rename_produces_no_false_neighbor_churn(self) -> None:
        previous = snapshot_dict(
            [device_entry("R1", "10.0.0.1", serial="SER-STABLE"), device_entry("SW1", "10.0.0.2")],
            [edge_entry("cisco-ios:r1", "SW1")],
        )
        current = snapshot_dict(
            [
                device_entry("CORE1", "10.0.0.1", serial="SER-STABLE", device_id="cisco-ios:core1"),
                device_entry("SW1", "10.0.0.2"),
            ],
            [edge_entry("cisco-ios:core1", "SW1")],
        )
        report = self.detector.compare(previous, current)
        self.assertEqual([], [c for c in report.changes if c.category == "neighbor"])

    def test_discovery_failures_are_reported(self) -> None:
        current = snapshot_dict(
            [device_entry("R1", "10.0.0.1")],
            metadata={"failed_hosts": ["10.0.0.7"]},
        )
        report = self.detector.compare(snapshot_dict([device_entry("R1", "10.0.0.1")]), current)
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual(("discovery", "medium"), (change.category, change.severity))
        self.assertEqual("Discovery failed for 10.0.0.7", change.description)

    def test_report_is_deterministic(self) -> None:
        previous = snapshot_dict([device_entry("R1", "10.0.0.1")])
        current = two_device_snapshot()
        first = self.detector.compare(previous, current)
        second = self.detector.compare(previous, current)
        self.assertEqual(first, second)
        self.assertEqual(render_change_report_json(first), render_change_report_json(second))


class ChangeReportRenderingTests(unittest.TestCase):
    def build_report(self):
        return ChangeDetector().compare(
            snapshot_dict([device_entry("R1", "10.0.0.1")], snapshot_id="atlas-topology:prev"),
            snapshot_dict(
                [device_entry("R1", "10.0.0.1"), device_entry("SW1", "10.0.0.2")],
                snapshot_id="atlas-topology:curr",
            ),
        )

    def test_json_generation(self) -> None:
        report = self.build_report()
        data = json.loads(render_change_report_json(report))
        self.assertEqual("atlas-topology:prev", data["previous_snapshot_id"])
        self.assertEqual("atlas-topology:curr", data["current_snapshot_id"])
        self.assertEqual(1, data["change_count"])
        self.assertEqual(["SW1"], data["new_devices"])
        self.assertEqual("device", data["changes"][0]["category"])
        self.assertTrue(data["changes"][0]["recommendation"])

    def test_markdown_generation(self) -> None:
        markdown = render_change_report_markdown(self.build_report())
        self.assertIn("# Atlas Change Report", markdown)
        self.assertIn("## Severity Summary", markdown)
        self.assertIn("| Low | 1 |", markdown)
        self.assertIn("SW1 was discovered for the first time", markdown)
        self.assertIn("Recommendation:", markdown)

    def test_markdown_for_no_changes(self) -> None:
        report = ChangeDetector().compare(two_device_snapshot(), two_device_snapshot())
        markdown = render_change_report_markdown(report)
        self.assertIn("No changes detected between the two snapshots.", markdown)


class MorningBriefIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        before = ScriptedNetwork({"10.0.0.1": device_outputs("R1", "10.0.0.1")})
        after = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
                "10.0.0.2": device_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
            }
        )
        _, _, cls.previous = run_multihop_discovery(before.transport_factory, "10.0.0.1")
        _, _, cls.current = run_multihop_discovery(after.transport_factory, "10.0.0.1")

    def test_brief_embeds_change_report_when_previous_exists(self) -> None:
        brief = build_morning_brief(self.current, self.previous)
        change_report = brief.metadata["change_report"]
        self.assertGreaterEqual(change_report["change_count"], 1)
        self.assertIn("SW1", change_report["new_devices"])
        self.assertTrue(
            any("SW1" in item for item in brief.recommendations),
            brief.recommendations,
        )

    def test_brief_markdown_includes_change_intelligence(self) -> None:
        markdown = build_morning_brief(self.current, self.previous).to_markdown()
        self.assertIn("## Change Intelligence", markdown)
        self.assertIn("Changes detected:", markdown)
        self.assertIn("High: 0", markdown)
        self.assertIn("SW1 was discovered for the first time", markdown)

    def test_brief_without_previous_has_no_change_section(self) -> None:
        brief = build_morning_brief(self.current, None)
        self.assertNotIn("change_report", brief.metadata)
        self.assertNotIn("## Change Intelligence", brief.to_markdown())

    def test_journey_still_evaluates_with_change_report(self) -> None:
        outcome = MorningBriefJourney().run(self.current, self.previous)
        self.assertEqual(1.0, outcome.evaluation.score)
        self.assertIn("## Change Intelligence", outcome.markdown)


class ViewerHighlightingTests(unittest.TestCase):
    def test_highlighting_marks_new_changed_and_removed(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
                "10.0.0.2": device_outputs("SW1", "10.0.0.2"),
            }
        )
        _, _, current = run_multihop_discovery(network.transport_factory, "10.0.0.1")
        report = ChangeDetector().compare(
            snapshot_dict(
                [
                    device_entry("R1", "10.0.0.1", os_version="15.8(1)M"),
                    device_entry("OLD-FW", "10.0.0.250"),
                ]
            ),
            current,
        )
        elements = TopologyRenderer(current, change_report=report).elements()
        by_label = {node["data"]["label"]: node["data"] for node in elements["nodes"]}
        self.assertEqual("new", by_label["SW1"]["change"])
        self.assertEqual("changed", by_label["R1"]["change"])
        self.assertEqual("removed", by_label["OLD-FW"]["change"])
        self.assertEqual("removed", by_label["OLD-FW"]["kind"])
        html = TopologyRenderer(current, change_report=report).render()
        self.assertIn('node[change = "new"]', html)
        self.assertIn("OLD-FW", html)

    def test_no_highlighting_without_comparison(self) -> None:
        network = ScriptedNetwork({"10.0.0.1": device_outputs("R1", "10.0.0.1")})
        _, _, snapshot = run_multihop_discovery(network.transport_factory, "10.0.0.1")
        elements = TopologyRenderer(snapshot).elements()
        for node in elements["nodes"]:
            self.assertNotIn("change", node["data"])


class AtlasCompareCliTests(unittest.TestCase):
    def write_snapshots(self, workdir: Path) -> tuple[Path, Path]:
        before = ScriptedNetwork({"10.0.0.1": device_outputs("R1", "10.0.0.1")})
        after = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
                "10.0.0.2": device_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
            }
        )
        _, _, previous = run_multihop_discovery(before.transport_factory, "10.0.0.1")
        _, _, current = run_multihop_discovery(after.transport_factory, "10.0.0.1")
        previous_path = workdir / "previous_snapshot.json"
        current_path = workdir / "current_snapshot.json"
        previous_path.write_text(TopologySnapshotExporter(previous).to_json(), encoding="utf-8")
        current_path.write_text(TopologySnapshotExporter(current).to_json(), encoding="utf-8")
        return previous_path, current_path

    def invoke(self, *arguments: str, workdir: Path):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                list(arguments),
                atlas_compare_json_output=workdir / "change_report.json",
                atlas_compare_markdown_output=workdir / "change_report.md",
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_compare_generates_reports_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            previous_path, current_path = self.write_snapshots(workdir)
            code, output, error = self.invoke(
                "atlas", "compare", str(previous_path), str(current_path), workdir=workdir
            )
            self.assertEqual(0, code, error)
            self.assertEqual("", error)
            self.assertIn("Atlas Change Report", output)
            self.assertIn("Changes detected: 1", output)
            self.assertIn("[low] SW1 was discovered for the first time", output)
            self.assertIn("Comparison completed successfully.", output)
            report = json.loads((workdir / "change_report.json").read_text(encoding="utf-8"))
            self.assertEqual(["SW1"], report["new_devices"])
            markdown = (workdir / "change_report.md").read_text(encoding="utf-8")
            self.assertIn("# Atlas Change Report", markdown)

    def test_compare_identical_snapshots_reports_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            previous_path, _ = self.write_snapshots(workdir)
            code, output, error = self.invoke(
                "atlas", "compare", str(previous_path), str(previous_path), workdir=workdir
            )
            self.assertEqual(0, code, error)
            self.assertIn("Changes detected: 0", output)
            self.assertIn("No changes detected between the two snapshots.", output)

    def test_missing_file_is_a_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error = self.invoke(
                "atlas", "compare", str(workdir / "missing.json"), str(workdir / "missing.json"),
                workdir=workdir,
            )
            self.assertEqual(1, code)
            self.assertEqual("", output)
            self.assertIn("Could not read snapshot file", error)

    def test_usage_error_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, output, error = self.invoke("atlas", "compare", workdir=Path(tmp))
            self.assertEqual(2, code)
            self.assertIn("Usage: founderos atlas compare", error)

    def test_help_lists_atlas_compare(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("founderos atlas compare", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
