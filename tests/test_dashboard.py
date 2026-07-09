"""Acceptance tests for PR-024 Atlas executive dashboard."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.change import ChangeDetector, render_change_report_json
from founderos_atlas.dashboard import (
    DashboardRenderer,
    build_dashboard_summary,
)
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.topology import TopologyGraph, TopologySnapshot, TopologySnapshotExporter
from founderos_runtime.cli import main

from tests.test_change_intelligence import device_entry, snapshot_dict
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


def build_workspace(workdir: Path) -> None:
    """Create a full artifact set: snapshot, viewer, brief, changes, configs."""

    network = ScriptedNetwork(
        {
            "10.0.0.1": device_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
            "10.0.0.2": device_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
        }
    )
    _, _, snapshot = run_multihop_discovery(network.transport_factory, "10.0.0.1")
    (workdir / "topology_snapshot.json").write_text(
        TopologySnapshotExporter(snapshot).to_json(), encoding="utf-8"
    )
    (workdir / "atlas_topology.html").write_text("<html>viewer</html>", encoding="utf-8")
    (workdir / "morning_brief.md").write_text("# Good Morning\n", encoding="utf-8")
    report = ChangeDetector().compare(
        snapshot_dict([device_entry("R1", "10.0.0.1")]), snapshot
    )
    (workdir / "change_report.json").write_text(
        render_change_report_json(report), encoding="utf-8"
    )
    (workdir / "change_report.md").write_text("# Atlas Change Report\n", encoding="utf-8")
    for hostname in ("R1", "SW1"):
        config_dir = workdir / "configs" / hostname
        config_dir.mkdir(parents=True)
        (config_dir / "running_config.txt").write_text("!\nend\n", encoding="utf-8")


def summary_kwargs(workdir: Path) -> dict:
    return {
        "snapshot_path": workdir / "topology_snapshot.json",
        "topology_path": workdir / "atlas_topology.html",
        "brief_path": workdir / "morning_brief.md",
        "change_report_json": workdir / "change_report.json",
        "change_report_md": workdir / "change_report.md",
        "configs_dir": workdir / "configs",
        "history_root": workdir / ".atlas" / "history",
        "timeline_path": workdir / "timeline.md",
        "config_change_report": workdir / "config_change_report.json",
        "config_change_report_md": workdir / "config_change_report.md",
        "incident_report": workdir / "incident_report.json",
        "incident_report_md": workdir / "incident_report.md",
        "link_base": workdir,
    }


class DashboardSummaryTests(unittest.TestCase):
    def test_full_workspace_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            build_workspace(workdir)
            summary = build_dashboard_summary(**summary_kwargs(workdir))
        self.assertEqual(2, summary.device_count)
        self.assertEqual(1, summary.relationship_count)
        self.assertEqual("100%", summary.discovery_success)
        self.assertEqual(2, summary.configurations_collected)
        self.assertEqual(1, summary.change_count)
        self.assertEqual("Warning", summary.status)
        self.assertIn("1 change(s) detected", summary.status_detail)
        self.assertIn("[low] SW1 was discovered for the first time", summary.recent_changes)
        availability = {action.label: action.available for action in summary.actions}
        for label in (
            "Open Topology",
            "Open Morning Brief",
            "Open Change Report",
            "Open Configurations",
            "Open Snapshot",
        ):
            self.assertTrue(availability[label], label)
        # No history in this workspace yet.
        self.assertFalse(availability["Open History"])
        self.assertFalse(availability["Open Timeline"])
        hrefs = {action.label: action.href for action in summary.actions}
        self.assertEqual("atlas_topology.html", hrefs["Open Topology"])
        self.assertEqual("configs", hrefs["Open Configurations"])

    def test_missing_artifacts_degrade_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_dashboard_summary(**summary_kwargs(Path(tmp)))
        self.assertEqual("Unknown", summary.status)
        self.assertIn("No discovery has run yet", summary.status_detail)
        self.assertIsNone(summary.device_count)
        self.assertIsNone(summary.change_count)
        self.assertEqual("—", summary.discovery_success)
        self.assertEqual(0, summary.configurations_collected)
        self.assertEqual("never", summary.last_discovery)
        self.assertTrue(all(action.href is None for action in summary.actions))
        self.assertEqual(
            ("No discovery has run yet. Run: founderos atlas discover",),
            summary.recent_activity,
        )

    def test_empty_network_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            snapshot = TopologySnapshot.from_graph(TopologyGraph())
            (workdir / "topology_snapshot.json").write_text(
                TopologySnapshotExporter(snapshot).to_json(), encoding="utf-8"
            )
            summary = build_dashboard_summary(**summary_kwargs(workdir))
        self.assertEqual(0, summary.device_count)
        self.assertEqual(0, summary.relationship_count)
        self.assertEqual("Healthy", summary.status)
        self.assertEqual("—", summary.discovery_success)

    def test_no_changes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            build_workspace(workdir)
            snapshot = json.loads(
                (workdir / "topology_snapshot.json").read_text(encoding="utf-8")
            )
            report = ChangeDetector().compare(snapshot, snapshot)
            (workdir / "change_report.json").write_text(
                render_change_report_json(report), encoding="utf-8"
            )
            summary = build_dashboard_summary(**summary_kwargs(workdir))
        self.assertEqual(0, summary.change_count)
        self.assertEqual((), summary.recent_changes)
        self.assertEqual("Healthy", summary.status)
        self.assertIn("Change report: no changes detected.", summary.recent_activity)

    def test_critical_status_on_high_severity_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            build_workspace(workdir)
            snapshot = json.loads(
                (workdir / "topology_snapshot.json").read_text(encoding="utf-8")
            )
            report = ChangeDetector().compare(
                snapshot_dict(
                    [device_entry("R1", "10.0.0.1"), device_entry("FW-OLD", "10.0.0.9")]
                ),
                snapshot,
            )
            (workdir / "change_report.json").write_text(
                render_change_report_json(report), encoding="utf-8"
            )
            summary = build_dashboard_summary(**summary_kwargs(workdir))
        self.assertEqual("Critical", summary.status)
        self.assertIn("high-severity", summary.status_detail)


class DashboardRendererTests(unittest.TestCase):
    def render(self, workdir: Path) -> str:
        return DashboardRenderer(
            build_dashboard_summary(**summary_kwargs(workdir))
        ).render()

    def test_dashboard_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            build_workspace(workdir)
            html = self.render(workdir)
        self.assertIn("<title>Atlas Dashboard</title>", html)
        self.assertIn("Enterprise Network Intelligence", html)
        self.assertIn("Last discovery: unrecorded", html)
        self.assertIn('class="status warning"', html)
        self.assertIn("Devices", html)
        self.assertIn("Relationships", html)
        self.assertIn("Discovery Success", html)
        self.assertIn("Configurations Collected", html)
        self.assertIn("Recent Changes", html)
        self.assertIn("Recent Activity", html)
        self.assertIn("Quick Actions", html)
        self.assertIn('href="atlas_topology.html"', html)
        self.assertIn('href="morning_brief.md"', html)
        self.assertIn('href="change_report.md"', html)
        self.assertIn('href="configs"', html)
        self.assertIn('href="topology_snapshot.json"', html)
        self.assertNotIn("__", html.split("</head>")[1])  # no unreplaced tokens
        self.assertNotIn("<script", html)  # frameworkless and script-free

    def test_missing_artifacts_render_disabled_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html = self.render(Path(tmp))
        self.assertIn('class="status unknown"', html)
        self.assertIn("(not yet generated)", html)
        self.assertNotIn("<a class=\"action\"", html)
        self.assertIn("No discovery has run yet", html)

    def test_rendering_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            build_workspace(workdir)
            first = self.render(workdir)
            second = self.render(workdir)
        self.assertEqual(first, second)


class DashboardCliTests(unittest.TestCase):
    def invoke(self, workdir: Path):
        opened: list[str] = []
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                ["atlas", "dashboard"],
                atlas_dashboard_output=workdir / "dashboard.html",
                atlas_topology_output=workdir / "atlas_topology.html",
                atlas_snapshot_output=workdir / "topology_snapshot.json",
                atlas_morning_brief_output=workdir / "morning_brief.md",
                atlas_compare_json_output=workdir / "change_report.json",
                atlas_compare_markdown_output=workdir / "change_report.md",
                atlas_config_output_dir=workdir / "configs",
                atlas_history_root=workdir / ".atlas" / "history",
                atlas_timeline_output=workdir / "timeline.md",
                atlas_config_diff_json_output=workdir / "config_change_report.json",
                atlas_config_diff_markdown_output=workdir / "config_change_report.md",
                atlas_incident_json_output=workdir / "incident_report.json",
                atlas_incident_markdown_output=workdir / "incident_report.md",
                atlas_browser_opener=opened.append,
            )
        return code, stdout.getvalue(), stderr.getvalue(), opened

    def test_dashboard_command_generates_and_opens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            build_workspace(workdir)
            code, output, error, opened = self.invoke(workdir)
            self.assertEqual(0, code, error)
            self.assertIn("Atlas Dashboard", output)
            self.assertIn("Network status: Warning", output)
            self.assertIn("Devices: 2", output)
            self.assertIn("Dashboard saved:", output)
            self.assertEqual(1, len(opened))
            self.assertTrue(opened[0].endswith("dashboard.html"))
            html = (workdir / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Enterprise Network Intelligence", html)

    def test_dashboard_command_with_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error, opened = self.invoke(workdir)
            self.assertEqual(0, code, error)
            self.assertIn("Network status: Unknown", output)
            self.assertTrue((workdir / "dashboard.html").is_file())
            self.assertEqual(1, len(opened))

    def test_discover_regenerates_dashboard_automatically(self) -> None:
        from tests.test_atlas_transport import PASSWORD

        network = ScriptedNetwork(
            {"10.0.0.1": device_outputs("R1", "10.0.0.1")}
        )
        replies = iter(["10.0.0.1", "atlas", "", "", ""])
        opened: list[str] = []
        stdout, stderr = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    ["atlas", "discover"],
                    atlas_transport_factory=lambda credentials: network.transport_factory(
                        credentials.host
                    ),
                    atlas_input_reader=lambda prompt: next(replies, ""),
                    atlas_password_reader=lambda prompt: PASSWORD,
                    atlas_topology_output=workdir / "atlas_topology.html",
                    atlas_snapshot_output=workdir / "topology_snapshot.json",
                    atlas_morning_brief_output=workdir / "morning_brief.md",
                    atlas_config_output_dir=workdir / "configs",
                    atlas_dashboard_output=workdir / "dashboard.html",
                    atlas_history_root=workdir / ".atlas" / "history",
                    atlas_browser_opener=opened.append,
                )
            self.assertEqual(0, code, stderr.getvalue())
            self.assertIn("Dashboard saved:", stdout.getvalue())
            html = (workdir / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Enterprise Network Intelligence", html)
            self.assertIn(">1</span>", html)  # one device tile
            self.assertIn('href="atlas_topology.html"', html)
            # Only the topology viewer opens a browser tab.
            self.assertEqual(1, len(opened))
            self.assertTrue(opened[0].endswith("atlas_topology.html"))

    def test_help_lists_atlas_dashboard(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("founderos atlas dashboard", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
