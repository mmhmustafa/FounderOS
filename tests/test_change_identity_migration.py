"""Migration v3: legacy change annotations converge onto scoped subjects.

PR-178.2A. The runtime model (v2 writes + read-only v1 fallback) is
correct WITHOUT this migration; v3 only moves the legacy records whose
owning scope is provable from the current change reports, shrinking the
fallback set. Every guarantee here mirrors the architecture review:
move unambiguous, never guess ambiguous, never delete unresolvable,
never overwrite scoped operator state, never rewrite history.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class MigrationV3Tests(unittest.TestCase):
    """v3 converges legacy records; correctness never depends on it.

    UNAMBIGUOUS → moved (v1 key removed — retaining it would let a
    future scope with the same delta reopen the leak). AMBIGUOUS and
    UNRESOLVABLE → left, still served by the read fallback. An existing
    scoped record is never overwritten. History is never rewritten.
    """

    # Two deltas: one only Hyderabad reports, one both scopes report.
    UNIQUE_CHANGE = {
        "category": "interface", "severity": "medium", "subject": "A1",
        "field": "status", "previous_value": "up", "current_value": "down",
        "description": "A1 went down",
    }
    SHARED_CHANGE = {
        "category": "neighbor", "severity": "high", "subject": "R1",
        "field": "bgp-neighbor", "previous_value": "Established",
        "current_value": "Idle",
        "description": "R1 BGP neighbour went to Idle",
    }

    def _world(self, tmp: str):
        """A workspace + output tree the migration can classify against."""

        root = Path(tmp)
        workspace = root / "workspace"
        workspace.mkdir(parents=True)
        output = root / "out"
        (workspace / "profiles.json").write_text(json.dumps({
            "schema_version": "1.0.0", "revision": 0,
            "profiles": [
                {"profile_id": "hyderabad", "name": "Hyderabad"},
                {"profile_id": "secunderabad", "name": "Secunderabad"},
            ],
        }), encoding="utf-8")
        hyd = output / ".atlas" / "profiles" / "hyderabad"
        sec = output / ".atlas" / "profiles" / "secunderabad"
        hyd.mkdir(parents=True)
        sec.mkdir(parents=True)
        stamp = {"generated_at": "2026-08-13T01:00:00+00:00"}
        (hyd / "change_report.json").write_text(json.dumps(
            {**stamp, "changes": [self.UNIQUE_CHANGE, self.SHARED_CHANGE]}
        ), encoding="utf-8")
        (sec / "change_report.json").write_text(json.dumps(
            {**stamp, "changes": [self.SHARED_CHANGE]}
        ), encoding="utf-8")
        return workspace, output

    def _hash_of(self, change: dict, kind: str = "topology") -> str:
        from founderos_atlas.change.identity import content_hash

        return content_hash({
            "kind": kind, "category": change["category"],
            "device": change["subject"], "field": change["field"],
            "before": change["previous_value"],
            "after": change["current_value"],
            "description": change["description"],
        })

    def _seed_legacy(self, workspace: Path, entries) -> None:
        from founderos_atlas.audit import AnnotationStore

        store = AnnotationStore(workspace)
        for kind, subject, fields in entries:
            store.set(kind=kind, subject=subject, fields=fields,
                      actor="pre-isolation")

    def _annotations(self, workspace: Path) -> dict:
        return json.loads(
            (workspace / "annotations.json").read_text(encoding="utf-8")
        )["annotations"]

    def test_unambiguous_records_move_per_kind_and_v1_keys_vanish(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            workspace, output = self._world(tmp)
            unique = "change:" + self._hash_of(self.UNIQUE_CHANGE)
            self._seed_legacy(workspace, [
                ("change-ack", unique, {"acknowledged": True}),
                ("change-assignment", unique, {"owner": "ahmed"}),
                ("change-note", unique, {"note": "site context"}),
                ("change-suppression", unique, {"reason": "planned"}),
            ])
            migrate_workspace(workspace, output_dir=output)
            annotations = self._annotations(workspace)
            moved = "change:v2:hyderabad:" + self._hash_of(self.UNIQUE_CHANGE)
            for kind in ("change-ack", "change-assignment", "change-note",
                         "change-suppression"):
                self.assertIn(moved, annotations[kind], kind)
                self.assertNotIn(unique, annotations[kind], kind)
                # The record's content and provenance are untouched.
                self.assertEqual(
                    "pre-isolation", annotations[kind][moved]["updated_by"]
                )

    def test_ambiguous_and_unresolvable_records_are_left_as_legacy(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            workspace, output = self._world(tmp)
            shared = "change:" + self._hash_of(self.SHARED_CHANGE)
            ghost = "change:0000deadbeef00000000"
            self._seed_legacy(workspace, [
                ("change-suppression", shared, {"reason": "which site?"}),
                ("change-ack", ghost, {"acknowledged": True}),
            ])
            migrate_workspace(workspace, output_dir=output)
            annotations = self._annotations(workspace)
            self.assertIn(shared, annotations["change-suppression"])
            self.assertIn(ghost, annotations["change-ack"])
            joined = json.dumps(annotations)
            self.assertNotIn("v2:hyderabad:" + self._hash_of(self.SHARED_CHANGE),
                             joined)
            self.assertNotIn("v2:secunderabad:", joined)

    def test_an_existing_scoped_record_is_never_overwritten(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            workspace, output = self._world(tmp)
            digest = self._hash_of(self.UNIQUE_CHANGE)
            legacy = "change:" + digest
            scoped = "change:v2:hyderabad:" + digest
            self._seed_legacy(workspace, [
                ("change-assignment", legacy, {"owner": "old-owner"}),
                ("change-assignment", scoped, {"owner": "current-owner"}),
            ])
            migrate_workspace(workspace, output_dir=output)
            annotations = self._annotations(workspace)
            self.assertEqual(
                "current-owner",
                annotations["change-assignment"][scoped]["owner"],
                "newer scoped operator state must win",
            )
            self.assertIn(legacy, annotations["change-assignment"],
                          "the shadowed legacy record is kept, not deleted")

    def test_migration_is_idempotent_and_crash_safe(self) -> None:
        from founderos_atlas.workspace.migrations import (
            SCHEMA_FILENAME, applied_version, migrate_workspace,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace, output = self._world(tmp)
            unique = "change:" + self._hash_of(self.UNIQUE_CHANGE)
            self._seed_legacy(workspace, [
                ("change-ack", unique, {"acknowledged": True}),
            ])
            migrate_workspace(workspace, output_dir=output)
            first = (workspace / "annotations.json").read_text()
            # Crash-before-stamp: lose the version marker, run again.
            (workspace / SCHEMA_FILENAME).unlink()
            migrate_workspace(workspace, output_dir=output)
            second = (workspace / "annotations.json").read_text()
            self.assertEqual(first, second, "re-run must change nothing")
            self.assertEqual(3, applied_version(workspace))
            # And a plain second run applies nothing at all.
            self.assertEqual([], migrate_workspace(workspace,
                                                   output_dir=output))

    def test_no_change_annotations_means_no_work(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            workspace, output = self._world(tmp)
            self._seed_legacy(workspace, [
                ("policy-assignment", "policy-result:X:host",
                 {"owner": "unrelated"}),
            ])
            before = (workspace / "annotations.json").read_text()
            migrate_workspace(workspace, output_dir=output)
            self.assertEqual(
                before, (workspace / "annotations.json").read_text()
            )
            self.assertFalse(
                (workspace / "migration-backups" / "v3"
                 / "annotations.json").is_file()
            )

    def test_without_an_output_dir_nothing_is_guessed(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            workspace, _output = self._world(tmp)
            unique = "change:" + self._hash_of(self.UNIQUE_CHANGE)
            self._seed_legacy(workspace, [
                ("change-ack", unique, {"acknowledged": True}),
            ])
            before = (workspace / "annotations.json").read_text()
            migrate_workspace(workspace)  # no output_dir
            self.assertEqual(
                before, (workspace / "annotations.json").read_text(),
                "a context-less run must leave every record untouched",
            )
            summary = [
                json.loads(line)
                for line in (workspace / "audit.jsonl")
                .read_text(encoding="utf-8").splitlines()
                if '"change-annotation-identity:v3"' in line
            ]
            self.assertEqual(1, len(summary))
            self.assertIn("nothing was attributed",
                          summary[0]["after"]["note"])

    def test_backup_exists_and_restores(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            workspace, output = self._world(tmp)
            unique = "change:" + self._hash_of(self.UNIQUE_CHANGE)
            self._seed_legacy(workspace, [
                ("change-ack", unique, {"acknowledged": True}),
            ])
            pre_migration = (workspace / "annotations.json").read_text()
            migrate_workspace(workspace, output_dir=output)
            backup = (workspace / "migration-backups" / "v3"
                      / "annotations.json")
            self.assertTrue(backup.is_file())
            self.assertEqual(pre_migration, backup.read_text())

    def test_audit_history_is_appended_to_never_rewritten(self) -> None:
        from founderos_atlas.workspace.migrations import migrate_workspace

        with tempfile.TemporaryDirectory() as tmp:
            workspace, output = self._world(tmp)
            unique = "change:" + self._hash_of(self.UNIQUE_CHANGE)
            self._seed_legacy(workspace, [
                ("change-ack", unique, {"acknowledged": True}),
            ])
            historical = (workspace / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            migrate_workspace(workspace, output_dir=output)
            after = (workspace / "audit.jsonl").read_text(encoding="utf-8")
            self.assertTrue(
                after.startswith(historical),
                "historical audit lines must remain byte-identical",
            )
            new_events = [
                json.loads(line)
                for line in after[len(historical):].splitlines() if line
            ]
            moves = [e for e in new_events if e["operation"] == "migrate"
                     and e["category"] == "change-ack"]
            self.assertEqual(1, len(moves))
            self.assertEqual("system", moves[0]["actor"])
            self.assertEqual("hyderabad", moves[0]["scope_id"])
            self.assertEqual(unique, moves[0]["before"]["subject"])
            summary = [e for e in new_events
                       if e["subject"] == "change-annotation-identity:v3"]
            self.assertEqual(1, len(summary))
            self.assertEqual(
                1, summary[0]["after"]["counts"]["change-ack"]["moved"]
            )

    def test_migration_events_stay_out_of_the_operator_timeline(self) -> None:
        from founderos_atlas.audit.models import AuditEvent
        from founderos_atlas.web.chronicle import chronicle_events

        event = AuditEvent.create(
            category="change-ack", operation="migrate",
            subject="change:v2:hyderabad:abc", actor="system",
            source="startup",
        )
        rows = chronicle_events(audit_events=[event])
        self.assertTrue(rows[0]["system"],
                        "migration events must be system-classified")


if __name__ == "__main__":
    unittest.main()
