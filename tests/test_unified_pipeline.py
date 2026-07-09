"""Integration tests for the PR-028 unified discovery pipeline."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.history import HistoryRepository
from founderos_runtime.cli import main

from tests.test_atlas_transport import PASSWORD
from tests.test_config_collection import (
    INVENTORY,
    LICENSE,
    MODULE,
    RUNNING_CONFIG,
    STARTUP_CONFIG,
    UNSUPPORTED,
)
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


def full_outputs(hostname: str, ip: str, neighbors=(), *, running_config=None, interfaces_brief=None):
    outputs = {
        **device_outputs(hostname, ip, neighbors),
        "show running-config": (running_config or RUNNING_CONFIG).replace("R1", hostname),
        "show startup-config": STARTUP_CONFIG,
        "show inventory": INVENTORY,
        "show license summary": LICENSE,
        "show module": MODULE,
    }
    if interfaces_brief is not None:
        outputs["show ip interface brief"] = interfaces_brief
    return outputs


def two_device_network(**overrides) -> ScriptedNetwork:
    topology = {
        "10.0.0.1": full_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
        "10.0.0.2": full_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
    }
    topology.update(overrides)
    return ScriptedNetwork(topology)


class UnifiedPipelineTests(unittest.TestCase):
    def run_discover(
        self,
        workdir: Path,
        network: ScriptedNetwork,
        *,
        collect: str = "y",
        start: datetime | None = None,
    ):
        start = start or datetime(2026, 7, 9, 8, 15, 0, tzinfo=timezone.utc)
        ticks = iter([start, start + timedelta(seconds=36)])
        replies = iter(["10.0.0.1", "atlas", "", "", collect])
        opened: list[str] = []
        stdout, stderr = StringIO(), StringIO()
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
                atlas_compare_json_output=workdir / "change_report.json",
                atlas_compare_markdown_output=workdir / "change_report.md",
                atlas_config_diff_json_output=workdir / "config_change_report.json",
                atlas_config_diff_markdown_output=workdir / "config_change_report.md",
                atlas_clock=lambda: next(ticks),
                atlas_browser_opener=opened.append,
            )
        return code, stdout.getvalue(), stderr.getvalue(), opened

    def test_first_discovery_without_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error, opened = self.run_discover(workdir, two_device_network())
            self.assertEqual(0, code, error)
            self.assertIn("Atlas Discovery Pipeline", output)
            for line in (
                "[1/9] Connecting to seed device ... ok",
                "[2/9] Discovering topology ... ok (2 device(s), 0 failed)",
                "[3/9] Collecting configurations ... ok (2 device(s))",
                "[4/9] Loading previous baseline ... skipped (first discovery)",
                "[5/9] Comparing topology ... skipped (no baseline)",
                "[6/9] Comparing configurations ... skipped (no baseline configurations)",
                "[7/9] Building reports ... ok",
                "[8/9] Archiving discovery ... ok",
                "[9/9] Updating dashboard ... ok",
                "Discovery Complete",
            ):
                self.assertIn(line, output)
            self.assertIn("Baseline: none (first discovery)", output)
            self.assertFalse((workdir / "change_report.json").exists())
            self.assertFalse((workdir / "config_change_report.json").exists())
            self.assertEqual(1, len(opened))

    def test_second_discovery_uses_baseline_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self.run_discover(workdir, two_device_network())
            later = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
            code, output, error, _ = self.run_discover(
                workdir, two_device_network(), start=later
            )
            self.assertEqual(0, code, error)
            self.assertIn("[4/9] Loading previous baseline ... ok (2026-07-09_08-15-00)", output)
            self.assertIn("[5/9] Comparing topology ... ok (0 change(s))", output)
            self.assertIn(
                "[6/9] Comparing configurations ... ok (0 change(s) across 2 device(s))",
                output,
            )
            self.assertTrue((workdir / "change_report.json").exists())
            report = json.loads(
                (workdir / "config_change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(2, report["device_count"])
            self.assertEqual(0, report["devices_changed"])

    def test_configuration_change_is_detected_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self.run_discover(workdir, two_device_network())
            changed_config = RUNNING_CONFIG.replace(
                "ip address 10.0.0.1 255.255.255.0",
                "ip address 10.0.99.1 255.255.255.0",
            )
            network = two_device_network(
                **{
                    "10.0.0.1": full_outputs(
                        "R1", "10.0.0.1", (("SW1", "10.0.0.2"),),
                        running_config=changed_config,
                    )
                }
            )
            later = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
            code, output, error, _ = self.run_discover(workdir, network, start=later)
            self.assertEqual(0, code, error)
            report = json.loads(
                (workdir / "config_change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, report["devices_changed"])
            self.assertGreaterEqual(report["change_count"], 1)
            categories = {
                change["category"]
                for device in report["reports"]
                for change in device["changes"]
            }
            self.assertIn("interfaces", categories)
            self.assertIn("Configuration changes:", output)
            # The brief carries the count in Today's Summary.
            brief = (workdir / "morning_brief.md").read_text(encoding="utf-8")
            self.assertIn("configuration change(s) detected", brief)

    def test_topology_change_is_detected_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self.run_discover(
                workdir,
                ScriptedNetwork({"10.0.0.1": full_outputs("R1", "10.0.0.1")}),
            )
            later = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
            code, output, error, _ = self.run_discover(
                workdir, two_device_network(), start=later
            )
            self.assertEqual(0, code, error)
            report = json.loads(
                (workdir / "change_report.json").read_text(encoding="utf-8")
            )
            self.assertIn("SW1", report["new_devices"])
            brief = (workdir / "morning_brief.md").read_text(encoding="utf-8")
            self.assertIn("## Change Intelligence", brief)
            self.assertIn("SW1 was discovered for the first time", brief)

    def test_interface_shutdown_is_flagged_medium(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self.run_discover(workdir, two_device_network())
            shut_brief = (
                "Interface                  IP-Address      OK? Method Status                Protocol\n"
                "GigabitEthernet0/0         10.0.0.2        YES manual up                    up\n"
                "GigabitEthernet0/1         unassigned      YES unset  administratively down down\n"
            )
            network = two_device_network(
                **{
                    "10.0.0.2": full_outputs(
                        "SW1", "10.0.0.2", (("R1", "10.0.0.1"),),
                        interfaces_brief=shut_brief,
                    )
                }
            )
            later = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
            code, output, error, _ = self.run_discover(workdir, network, start=later)
            self.assertEqual(0, code, error)
            report = json.loads(
                (workdir / "change_report.json").read_text(encoding="utf-8")
            )
            shutdowns = [
                change
                for change in report["changes"]
                if change["category"] == "interface"
                and "changed from up to administratively down" in change["description"]
            ]
            self.assertEqual(1, len(shutdowns))
            self.assertEqual("medium", shutdowns[0]["severity"])
            self.assertIn(
                "Verify whether the interface shutdown on SW1 was planned.",
                shutdowns[0]["recommendation"],
            )
            brief = (workdir / "morning_brief.md").read_text(encoding="utf-8")
            self.assertIn("Verify whether the interface shutdown on SW1 was planned.", brief)

    def test_discovery_failure_does_not_break_the_pipeline(self) -> None:
        network = ScriptedNetwork(
            {
                "10.0.0.1": full_outputs(
                    "R1", "10.0.0.1", (("SW1", "10.0.0.2"), ("SW2", "10.0.0.3"))
                ),
                "10.0.0.2": full_outputs("SW1", "10.0.0.2"),
            },
            unreachable=frozenset({"10.0.0.3"}),
        )
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error, _ = self.run_discover(workdir, network)
            self.assertEqual(0, code, error)
            self.assertIn("[2/9] Discovering topology ... ok (2 device(s), 1 failed)", output)
            self.assertIn("Discovery Complete", output)
            record = HistoryRepository(workdir / ".atlas" / "history").load().records[0]
            self.assertEqual(("10.0.0.3",), record.failures)

    def test_partial_configuration_collection(self) -> None:
        network = two_device_network(
            **{
                "10.0.0.2": {
                    **full_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
                    "show startup-config": UNSUPPORTED,
                    "show module": UNSUPPORTED,
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error, _ = self.run_discover(workdir, network)
            self.assertEqual(0, code, error)
            self.assertIn("[partial] SW1 ->", output)
            record = HistoryRepository(workdir / ".atlas" / "history").load().records[0]
            self.assertEqual("partial", record.configuration_status)
            self.assertEqual(2, record.configured_device_count)

    def test_history_record_contains_the_complete_artifact_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self.run_discover(workdir, two_device_network())
            later = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
            self.run_discover(workdir, two_device_network(), start=later)
            repository = HistoryRepository(workdir / ".atlas" / "history")
            record = repository.load().records[0]
            record_dir = repository.record_directory(record.record_id)
            for name in (
                "discovery_metadata.json",
                "topology_snapshot.json",
                "morning_brief.md",
                "atlas_topology.html",
                "dashboard.html",
                "change_report.json",
                "config_change_report.json",
            ):
                self.assertTrue((record_dir / name).is_file(), name)
            self.assertTrue((record_dir / "configs" / "R1" / "running_config.txt").is_file())
            metadata = json.loads(
                (record_dir / "discovery_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(36.0, metadata["duration_seconds"])
            self.assertIn("atlas_version", metadata["metadata"])

    def test_dashboard_reflects_the_run_without_manual_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, _, error, _ = self.run_discover(workdir, two_device_network())
            self.assertEqual(0, code, error)
            html = (workdir / "dashboard.html").read_text(encoding="utf-8")
            for section in (
                "Recent Discoveries",
                "Recent Changes",
                "Configuration Changes",
                "Recent Incident Investigation",
                "Quick Actions",
            ):
                self.assertIn(section, html)
            self.assertIn("09-Jul-2026 08:15", html)  # the archived run is listed

    def test_morning_brief_is_manager_friendly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self.run_discover(workdir, two_device_network())
            later = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
            code, _, error, _ = self.run_discover(
                workdir, two_device_network(), start=later
            )
            self.assertEqual(0, code, error)
            brief = (workdir / "morning_brief.md").read_text(encoding="utf-8")
            self.assertIn("# Good Morning", brief)
            self.assertIn("## Today's Summary", brief)
            self.assertIn("- 2 device(s) discovered", brief)
            self.assertIn("- 1 relationship(s) verified", brief)
            self.assertIn("- Configuration collected from 2 device(s)", brief)
            self.assertIn("- No topology changes detected", brief)
            self.assertIn("Started: 2026-07-09T23:41:18+00:00", brief)
            self.assertIn("Completed: 2026-07-09T23:41:54+00:00", brief)
            self.assertIn("Duration: 36.0 seconds", brief)

    def test_viewer_node_details_are_enriched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, _, error, _ = self.run_discover(workdir, two_device_network())
            self.assertEqual(0, code, error)
            html = (workdir / "atlas_topology.html").read_text(encoding="utf-8")
            for marker in (
                '"neighbors":1',
                '"discovery_depth":"0"',
                '"discovery_depth":"1"',
                '"config_collected":"Yes"',
                '"last_discovered":"2026-07-09T08:15:36+00:00"',
                "Discovery depth",
                "Configuration collected",
                "Last configuration change",
            ):
                self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
