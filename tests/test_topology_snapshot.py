"""Contract and exporter tests for Atlas TopologySnapshot."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from founderos_atlas.demo import atlas_app_root, run_atlas_discovery_demo
from founderos_atlas.topology import (
    SNAPSHOT_SCHEMA_VERSION,
    TopologyReconciler,
    TopologySnapshot,
    TopologySnapshotExporter,
)


class TopologySnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.discovery, self.graph, self.snapshot = run_atlas_discovery_demo()
        self.exporter = TopologySnapshotExporter(self.snapshot)

    def test_build_snapshot_from_graph(self) -> None:
        self.assertTrue(self.snapshot.snapshot_id.startswith("atlas-topology:"))
        self.assertIsNone(self.snapshot.created_at)
        self.assertEqual(self.graph.device_count(), self.snapshot.device_count)
        self.assertEqual(self.graph.edge_count(), self.snapshot.edge_count)

    def test_snapshot_contains_devices_edges_warnings_and_metadata(self) -> None:
        self.assertEqual(1, len(self.snapshot.devices))
        self.assertEqual(3, len(self.snapshot.edges))
        self.assertEqual((), self.snapshot.warnings)
        self.assertEqual(SNAPSHOT_SCHEMA_VERSION, self.snapshot.metadata["schema_version"])
        self.assertEqual(1, self.snapshot.metadata["duplicates_removed"])

    def test_conflict_warnings_are_included(self) -> None:
        conflict = replace(
            self.discovery,
            device=replace(
                self.discovery.device,
                device_id="snapshot-session:conflict",
                vendor="juniper",
            ),
            neighbors=(),
        )
        graph = TopologyReconciler().reconcile((self.discovery, conflict))
        snapshot = TopologySnapshot.from_graph(graph)
        self.assertEqual(1, len(snapshot.warnings))
        self.assertEqual("vendor", snapshot.warnings[0]["field"])
        self.assertEqual(1, snapshot.metadata["warning_count"])

    def test_to_dict_is_defensive(self) -> None:
        value = self.exporter.to_dict()
        value["devices"][0]["hostname"] = "changed"
        value["metadata"]["schema_version"] = "changed"
        self.assertEqual("access-sw-01", self.snapshot.devices[0]["hostname"])
        self.assertEqual("1.0.0", self.snapshot.metadata["schema_version"])

    def test_to_json_is_deterministic_and_round_trips(self) -> None:
        first = self.exporter.to_json()
        second = TopologySnapshotExporter(
            TopologySnapshot.from_graph(
                self.graph, metadata={"source": "atlas_discovery_demo"}
            )
        ).to_json()
        self.assertEqual(first, second)
        self.assertEqual(self.exporter.to_dict(), json.loads(first))

    def test_to_markdown_is_human_readable(self) -> None:
        markdown = self.exporter.to_markdown()
        self.assertIn("# Atlas Topology Snapshot", markdown)
        self.assertIn("### access-sw-01", markdown)
        self.assertIn("| Local device | Local interface |", markdown)
        self.assertIn("No reconciliation warnings.", markdown)
        self.assertNotIn("mappingproxy", markdown)

    def test_created_at_is_optional_and_deterministic(self) -> None:
        timestamp = "2026-07-04T00:00:00Z"
        first = TopologySnapshot.from_graph(self.graph, created_at=timestamp)
        second = TopologySnapshot.from_graph(self.graph, created_at=timestamp)
        self.assertEqual(first, second)
        self.assertEqual(timestamp, first.created_at)
        self.assertNotEqual(self.snapshot.snapshot_id, first.snapshot_id)

    def test_output_ordering_is_stable(self) -> None:
        data = self.exporter.to_dict()
        self.assertEqual(
            sorted(data["devices"], key=lambda item: item["device_id"]),
            data["devices"],
        )
        self.assertEqual(
            sorted(
                data["edges"],
                key=lambda item: (
                    item["local_device_id"], item["local_interface"].casefold(),
                    item["remote_hostname"].casefold(),
                    (item["remote_interface"] or "").casefold(),
                ),
            ),
            data["edges"],
        )

    def test_snapshot_matches_versioned_json_schema(self) -> None:
        schema_path = atlas_app_root() / "manifests" / "schemas" / "topology-snapshot.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                self.exporter.to_dict()
            )
        )
        self.assertEqual([], errors)

    def test_exporter_rejects_non_snapshot(self) -> None:
        with self.assertRaisesRegex(TypeError, "TopologySnapshot"):
            TopologySnapshotExporter(self.graph)  # type: ignore[arg-type]

    def test_snapshot_is_content_addressed(self) -> None:
        same = TopologySnapshot.from_graph(
            self.graph, metadata={"source": "atlas_discovery_demo"}
        )
        different = TopologySnapshot.from_graph(
            self.graph, metadata={"source": "different"}
        )
        self.assertEqual(self.snapshot.snapshot_id, same.snapshot_id)
        self.assertNotEqual(self.snapshot.snapshot_id, different.snapshot_id)
        with self.assertRaisesRegex(ValueError, "does not match canonical"):
            replace(self.snapshot, snapshot_id="atlas-topology:" + "0" * 64)

    def test_snapshot_and_exports_do_not_write_files(self) -> None:
        root = atlas_app_root()
        before = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
        self.exporter.to_dict()
        self.exporter.to_json()
        self.exporter.to_markdown()
        after = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
