"""Milestone 7 local persistence safety and recovery tests."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from founderos_runtime import (
    ConflictError,
    FounderOSApplication,
    LocalProjectStore,
    PersistenceLockError,
)


class PersistenceHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / ".founderos"
        self.app = FounderOSApplication(self.root)
        self.app.new(name="Persistence Test", founder_id="founder-1", founder_name="Founder", domain="Testing")
        self.store = LocalProjectStore(self.root)

    def create_backup(self) -> None:
        runtime = self.store.load()
        self.store.save(runtime)
        self.assertTrue((self.store.backup_path / "project-state.json").is_file())
        self.assertTrue((self.store.backup_path / "events.jsonl").is_file())

    def read_state(self) -> dict:
        return json.loads(self.store.state_path.read_text(encoding="utf-8"))

    def write_state(self, state: dict) -> None:
        self.store.state_path.write_text(json.dumps(state), encoding="utf-8")

    def test_backup_is_created_before_subsequent_write(self) -> None:
        original = self.read_state()
        self.create_backup()
        backup = json.loads((self.store.backup_path / "project-state.json").read_text(encoding="utf-8"))
        current = self.read_state()
        self.assertEqual(original["store_revision"], backup["store_revision"])
        self.assertEqual(original["store_revision"] + 1, current["store_revision"])

    def test_corrupted_project_state_is_detected_and_restored(self) -> None:
        self.create_backup()
        self.store.state_path.write_text("{broken", encoding="utf-8")
        health = self.store.health()
        self.assertEqual("recoverable", health.status)
        self.assertFalse(health.primary_valid)
        self.assertTrue(health.backup_valid)
        restored = self.store.recover()
        self.assertEqual("healthy", restored.status)
        self.assertEqual("NO_PROJECT", self.store.load().repositories.projects.all()[0]["current_state"])

    def test_corrupted_events_are_detected_and_restored(self) -> None:
        self.create_backup()
        self.store.events_path.write_text("not-json\n", encoding="utf-8")
        self.assertTrue(self.store.health().recovery_recommended)
        self.store.recover()
        events = self.store.load().repositories.events.all()
        self.assertEqual([1], [event["sequence"] for event in events])

    def test_missing_events_file_is_detected_and_restored(self) -> None:
        self.create_backup()
        self.store.events_path.unlink()
        health = self.store.health()
        self.assertFalse(health.primary_valid)
        self.assertTrue(health.recovery_recommended)
        self.store.recover()
        self.assertTrue(self.store.events_path.is_file())

    def test_missing_project_state_is_detected_and_restored(self) -> None:
        self.create_backup()
        self.store.state_path.unlink()
        health = self.store.health()
        self.assertFalse(health.primary_valid)
        self.assertTrue(health.recovery_recommended)
        self.store.recover()
        self.assertTrue(self.store.state_path.is_file())

    def test_stale_write_is_rejected_under_store_revision_check(self) -> None:
        first = self.store.load()
        stale = self.store.load()
        self.store.save(first)
        with self.assertRaisesRegex(ConflictError, "Stale local persistence write"):
            self.store.save(stale)

    def test_active_writer_lock_rejects_second_writer(self) -> None:
        runtime = self.store.load()
        with self.store.writer_lock():
            with self.assertRaises(PersistenceLockError):
                self.store.save(runtime)
        self.assertFalse(self.store.lock_path.exists())

    def test_event_replay_mismatch_is_detected(self) -> None:
        state = self.read_state()
        project = state["records"]["project"][0]
        project["current_state"] = "FOUNDER_SETUP"
        project["revision"] = 2
        self.write_state(state)
        with self.assertRaisesRegex(ConflictError, "deterministic Event replay"):
            self.store.load()

    def test_v0_snapshot_migrates_through_explicit_structure(self) -> None:
        state = self.read_state()
        state.pop("format_version")
        state.pop("store_revision")
        self.write_state(state)
        runtime = self.store.load()
        self.assertEqual(0, runtime.store_revision)
        self.store.save(runtime)
        migrated = self.read_state()
        self.assertEqual(LocalProjectStore.FORMAT_VERSION, migrated["format_version"])
        self.assertEqual(1, migrated["store_revision"])

    def test_future_format_is_rejected(self) -> None:
        state = self.read_state()
        state["format_version"] = LocalProjectStore.FORMAT_VERSION + 1
        self.write_state(state)
        with self.assertRaisesRegex(ConflictError, "Unsupported future"):
            self.store.load()

    def test_health_reports_lock_and_valid_primary(self) -> None:
        with self.store.writer_lock():
            health = self.store.health()
            self.assertTrue(health.primary_valid)
            self.assertTrue(health.locked)
            self.assertEqual("unhealthy", health.status)


if __name__ == "__main__":
    unittest.main()
