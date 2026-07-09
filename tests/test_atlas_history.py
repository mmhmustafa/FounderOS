"""Acceptance tests for PR-025 Atlas historical timeline and network memory."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.dashboard import build_dashboard_summary
from founderos_atlas.history import (
    DiscoveryRecord,
    HistoryRepository,
    folder_name_for,
    generate_timeline,
)
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.topology import TopologySnapshotExporter
from founderos_runtime.cli import main

from tests.test_atlas_transport import PASSWORD
from tests.test_dashboard import summary_kwargs
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


def record_fields(**overrides) -> dict:
    fields = {
        "started_at": "2026-07-09T23:41:18+00:00",
        "completed_at": "2026-07-09T23:41:23+00:00",
        "duration_seconds": 4.8,
        "device_count": 2,
        "relationship_count": 1,
        "warning_count": 0,
        "failures": (),
        "configuration_status": "collected",
        "configured_device_count": 2,
        "quality_score": 1.0,
        "network_status": "Healthy",
        "snapshot_id": "atlas-topology:test",
    }
    fields.update(overrides)
    return fields


def snapshot_json_for(hostnames: tuple[str, ...]) -> str:
    topology = {}
    for index, hostname in enumerate(hostnames, start=1):
        neighbors = tuple(
            (other, f"10.0.0.{position}")
            for position, other in enumerate(hostnames, start=1)
            if other != hostname
        )
        topology[f"10.0.0.{index}"] = device_outputs(
            hostname, f"10.0.0.{index}", neighbors
        )
    network = ScriptedNetwork(topology)
    _, _, snapshot = run_multihop_discovery(network.transport_factory, "10.0.0.1")
    return TopologySnapshotExporter(snapshot).to_json()


class HistoryRepositoryTests(unittest.TestCase):
    def test_history_creation_preserves_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            snapshot_file = workdir / "topology_snapshot.json"
            snapshot_file.write_text(snapshot_json_for(("R1",)), encoding="utf-8")
            brief_file = workdir / "morning_brief.md"
            brief_file.write_text("# Good Morning\n", encoding="utf-8")
            config_dir = workdir / "configs" / "R1"
            config_dir.mkdir(parents=True)
            (config_dir / "running_config.txt").write_text("!\nend\n", encoding="utf-8")

            repository = HistoryRepository(workdir / ".atlas" / "history")
            record = repository.save_discovery(
                **record_fields(),
                artifacts={
                    "topology_snapshot.json": snapshot_file,
                    "morning_brief.md": brief_file,
                },
                config_directories={"R1": config_dir},
            )
            record_dir = repository.record_directory(record.record_id)
            self.assertEqual("2026-07-09_23-41-18", record.record_id)
            self.assertTrue((record_dir / "discovery_metadata.json").is_file())
            self.assertTrue((record_dir / "topology_snapshot.json").is_file())
            self.assertTrue((record_dir / "morning_brief.md").is_file())
            self.assertTrue((record_dir / "configs" / "R1" / "running_config.txt").is_file())
            metadata = json.loads(
                (record_dir / "discovery_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(4.8, metadata["duration_seconds"])
            self.assertEqual(
                ["configs/R1", "morning_brief.md", "topology_snapshot.json"],
                metadata["metadata"]["artifacts"],
            )

    def test_timestamp_uniqueness_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = HistoryRepository(Path(tmp) / "history")
            first = repository.save_discovery(**record_fields())
            second = repository.save_discovery(**record_fields())
            third = repository.save_discovery(**record_fields())
            self.assertEqual("2026-07-09_23-41-18", first.record_id)
            self.assertEqual("2026-07-09_23-41-18-2", second.record_id)
            self.assertEqual("2026-07-09_23-41-18-3", third.record_id)
            self.assertEqual(3, len(repository.load().records))

    def test_history_loading_is_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = HistoryRepository(Path(tmp) / "history")
            for hour in ("08", "18", "23"):
                repository.save_discovery(
                    **record_fields(started_at=f"2026-07-09T{hour}:00:00+00:00")
                )
            index = repository.load()
            self.assertEqual((), index.issues)
            self.assertEqual(
                ["2026-07-09_23-00-00", "2026-07-09_18-00-00", "2026-07-09_08-00-00"],
                [record.record_id for record in index.records],
            )
            self.assertEqual("2026-07-09_23-00-00", index.latest.record_id)

    def test_missing_history_loads_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = HistoryRepository(Path(tmp) / "nowhere").load()
            self.assertEqual((), index.records)
            self.assertEqual((), index.issues)
            self.assertIsNone(index.latest)

    def test_corrupt_history_is_reported_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            repository = HistoryRepository(root)
            repository.save_discovery(**record_fields())
            corrupt = root / "2026-07-08_10-00-00"
            corrupt.mkdir()
            (corrupt / "discovery_metadata.json").write_text("{not json", encoding="utf-8")
            empty = root / "2026-07-07_10-00-00"
            empty.mkdir()
            index = repository.load()
            self.assertEqual(1, len(index.records))
            self.assertEqual(2, len(index.issues))
            self.assertTrue(any("2026-07-08_10-00-00" in issue for issue in index.issues))

    def test_metadata_serialization_round_trip(self) -> None:
        record = DiscoveryRecord(record_id="2026-07-09_23-41-18", **record_fields())
        restored = DiscoveryRecord.from_dict(record.to_dict())
        self.assertEqual(record, restored)
        with self.assertRaises(ValueError):
            DiscoveryRecord.from_dict({"record_id": "x"})

    def test_folder_name_normalization(self) -> None:
        self.assertEqual(
            "2026-07-09_23-41-18", folder_name_for("2026-07-09T23:41:18+00:00")
        )


class TimelineTests(unittest.TestCase):
    def build_history(self, root: Path) -> HistoryRepository:
        repository = HistoryRepository(root)
        with tempfile.TemporaryDirectory() as tmp:
            first_snapshot = Path(tmp) / "first.json"
            first_snapshot.write_text(snapshot_json_for(("R1",)), encoding="utf-8")
            repository.save_discovery(
                **record_fields(
                    started_at="2026-07-08T18:22:00+00:00",
                    completed_at="2026-07-08T18:22:05+00:00",
                    duration_seconds=5.0,
                    device_count=1,
                    relationship_count=0,
                    configuration_status="not_requested",
                    configured_device_count=0,
                ),
                artifacts={"topology_snapshot.json": first_snapshot},
            )
            second_snapshot = Path(tmp) / "second.json"
            second_snapshot.write_text(snapshot_json_for(("R1", "SW1")), encoding="utf-8")
            repository.save_discovery(
                **record_fields(
                    started_at="2026-07-09T23:41:18+00:00",
                    device_count=2,
                    relationship_count=1,
                ),
                artifacts={"topology_snapshot.json": second_snapshot},
            )
        return repository

    def test_timeline_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = self.build_history(Path(tmp) / "history")
            timeline = generate_timeline(repository)
        self.assertIn("# Network Timeline", timeline)
        self.assertIn("## 09-Jul-2026", timeline)
        self.assertIn("## 08-Jul-2026", timeline)
        self.assertIn("### 23:41 — Discovery completed", timeline)
        self.assertIn("- Devices: 2 (+1 since previous discovery)", timeline)
        self.assertIn("- Configuration collected for 2 device(s)", timeline)
        self.assertIn("[low] SW1 was discovered for the first time", timeline)
        self.assertIn("- Status: Healthy", timeline)

    def test_timeline_with_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            timeline = generate_timeline(HistoryRepository(Path(tmp) / "history"))
        self.assertIn("No discoveries recorded yet", timeline)

    def test_timeline_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = self.build_history(Path(tmp) / "history")
            self.assertEqual(generate_timeline(repository), generate_timeline(repository))


class HistoryCliTests(unittest.TestCase):
    def invoke(self, *arguments: str, root: Path, timeline: Path | None = None):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                list(arguments),
                atlas_history_root=root,
                atlas_timeline_output=timeline or (root.parent / "timeline.md"),
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_history_command_lists_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            repository = HistoryRepository(root)
            repository.save_discovery(**record_fields())
            repository.save_discovery(
                **record_fields(
                    started_at="2026-07-09T08:15:00+00:00",
                    device_count=1,
                    duration_seconds=3.2,
                )
            )
            code, output, error = self.invoke("atlas", "history", root=root)
        self.assertEqual(0, code, error)
        self.assertIn("Atlas Discovery History", output)
        self.assertIn("09-Jul-2026 23:41", output)
        self.assertIn("2 Devices | Healthy | Duration: 4.8 sec", output)
        self.assertIn("09-Jul-2026 08:15", output)
        self.assertIn("1 Device | Healthy | Duration: 3.2 sec", output)
        self.assertIn("Folder: .atlas/history/2026-07-09_23-41-18", output)

    def test_history_command_with_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, output, error = self.invoke(
                "atlas", "history", root=Path(tmp) / "history"
            )
        self.assertEqual(0, code, error)
        self.assertIn("No discovery history yet", output)

    def test_timeline_command_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            HistoryRepository(root).save_discovery(**record_fields())
            timeline_path = Path(tmp) / "timeline.md"
            code, output, error = self.invoke(
                "atlas", "timeline", root=root, timeline=timeline_path
            )
            self.assertEqual(0, code, error)
            self.assertIn("Discoveries recorded: 1", output)
            self.assertIn("Timeline saved:", output)
            content = timeline_path.read_text(encoding="utf-8")
            self.assertIn("# Network Timeline", content)
            self.assertIn("## 09-Jul-2026", content)


class DiscoverHistoryIntegrationTests(unittest.TestCase):
    def run_discover(self, workdir: Path, clock_times: list[datetime]):
        network = ScriptedNetwork(
            {
                "10.0.0.1": device_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
                "10.0.0.2": device_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
            }
        )
        replies = iter(["10.0.0.1", "atlas", "", "", ""])
        ticks = iter(clock_times)
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
                atlas_state_diff_json_output=workdir / "state_change_report.json",
                atlas_state_diff_markdown_output=workdir / "state_change_report.md",
                atlas_clock=lambda: next(ticks),
                atlas_browser_opener=lambda uri: None,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_every_discovery_is_preserved(self) -> None:
        base = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error = self.run_discover(
                workdir, [base, base + timedelta(seconds=5)]
            )
            self.assertEqual(0, code, error)
            self.assertIn("History saved:", output)
            repository = HistoryRepository(workdir / ".atlas" / "history")
            record = repository.load().records[0]
            self.assertEqual("2026-07-09_23-41-18", record.record_id)
            self.assertEqual(5.0, record.duration_seconds)
            self.assertEqual(2, record.device_count)
            self.assertEqual(1, record.relationship_count)
            self.assertEqual("not_requested", record.configuration_status)
            self.assertEqual(1.0, record.quality_score)
            self.assertEqual("Healthy", record.network_status)
            record_dir = repository.record_directory(record.record_id)
            for name in (
                "discovery_metadata.json",
                "topology_snapshot.json",
                "morning_brief.md",
                "atlas_topology.html",
                "dashboard.html",
            ):
                self.assertTrue((record_dir / name).is_file(), name)

    def test_history_survives_multiple_runs(self) -> None:
        base = datetime(2026, 7, 9, 8, 15, 0, tzinfo=timezone.utc)
        later = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self.run_discover(workdir, [base, base + timedelta(seconds=3)])
            self.run_discover(workdir, [later, later + timedelta(seconds=5)])
            index = HistoryRepository(workdir / ".atlas" / "history").load()
            self.assertEqual(2, len(index.records))
            self.assertEqual("2026-07-09_23-41-18", index.records[0].record_id)
            self.assertEqual("2026-07-09_08-15-00", index.records[1].record_id)
            # Dashboard now reflects history.
            summary = build_dashboard_summary(**summary_kwargs(workdir))
            self.assertEqual("09-Jul-2026 23:41", summary.last_discovery)
            self.assertEqual(2, len(summary.recent_discoveries))
            self.assertIn("2 device(s)", summary.recent_discoveries[0])
            availability = {a.label: a.available for a in summary.actions}
            self.assertTrue(availability["Open History"])
            html = (workdir / "dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Recent Discoveries", html)
            self.assertIn("09-Jul-2026 23:41", html)


if __name__ == "__main__":
    unittest.main()
