"""Runtime service boundaries, persistence ports, and command idempotency."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from founderos_runtime import (
    ApprovalLifecycleService,
    ArtifactLifecycleService,
    ConflictError,
    ContractRegistry,
    EvaluationLifecycleService,
    FounderOSApplication,
    FounderSetupService,
    LocalProjectStore,
    PersistenceLockError,
    ProjectStateService,
    RuntimeRepositories,
)


class ServiceBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / ".founderos"

    def test_repository_import_export_ports_round_trip_without_private_calls(self) -> None:
        app = FounderOSApplication(self.root)
        app.new(name="Ports", founder_id="founder-1", founder_name="Founder", domain="Testing")
        loaded = LocalProjectStore(self.root).load()
        records = loaded.repositories.export_records()
        events = loaded.repositories.events.export_records()
        restored = RuntimeRepositories(ContractRegistry())
        restored.import_records(records)
        restored.import_events(events)
        self.assertEqual(records, restored.export_records())
        self.assertEqual(events, restored.events.export_records())

    def test_founder_setup_uses_reusable_lifecycle_services(self) -> None:
        repositories = RuntimeRepositories(ContractRegistry())
        service = FounderSetupService(repositories)
        self.assertIsInstance(service.artifacts, ArtifactLifecycleService)
        self.assertIsInstance(service.evaluations, EvaluationLifecycleService)
        self.assertIsInstance(service.approvals, ApprovalLifecycleService)

    def test_new_command_idempotency_survives_reload(self) -> None:
        first = FounderOSApplication(self.root).new(
            name="Idempotent", founder_id="founder-1", founder_name="Founder", domain="Testing",
            command_key="new-1",
        )
        second = FounderOSApplication(self.root).new(
            name="Ignored duplicate", founder_id="founder-1", founder_name="Founder", domain="Other",
            command_key="new-1",
        )
        self.assertEqual(first, second)
        runtime = LocalProjectStore(self.root).load()
        self.assertEqual(1, len(runtime.repositories.projects.all()))
        self.assertIn("new-1", runtime.commands or {})

    def test_founder_brief_and_approval_are_restart_idempotent(self) -> None:
        app = FounderOSApplication(self.root)
        app.new(name="Idempotent", founder_id="founder-1", founder_name="Founder", domain="Testing")
        content = {
            "founder_profile": {
                "name": "Founder", "background": "Engineer", "domain_expertise": ["testing"],
                "technical_skills": ["Python"], "business_skills": [], "available_time_per_week": 10,
                "available_budget": {"amount": 1000, "currency": "USD"},
            },
            "startup_context": {
                "domain": "testing", "target_users": ["teams"], "known_problem_area": "Slow feedback",
                "constraints": [], "success_definition": "Validated need",
            },
        }
        first = app.founder_brief(content, command_key="brief-1")
        event_count = len(LocalProjectStore(self.root).load().repositories.events.all())
        second = FounderOSApplication(self.root).founder_brief(content, command_key="brief-1")
        self.assertEqual(first, second)
        self.assertEqual(event_count, len(LocalProjectStore(self.root).load().repositories.events.all()))
        approved = FounderOSApplication(self.root).approve(rationale="Accurate", command_key="approve-1")
        final_count = len(LocalProjectStore(self.root).load().repositories.events.all())
        repeated = FounderOSApplication(self.root).approve(rationale="Different", command_key="approve-1")
        self.assertEqual(approved, repeated)
        self.assertEqual(final_count, len(LocalProjectStore(self.root).load().repositories.events.all()))

    def test_idempotency_key_cannot_be_reused_for_another_operation(self) -> None:
        app = FounderOSApplication(self.root)
        app.new(name="Idempotent", founder_id="founder-1", founder_name="Founder", domain="Testing", command_key="shared")
        with self.assertRaisesRegex(Exception, "different command"):
            app.founder_brief({}, command_key="shared")

    def test_lock_inspection_and_safe_stale_lock_policy(self) -> None:
        store = LocalProjectStore(self.root)
        with store.writer_lock():
            info = store.inspect_lock()
            self.assertEqual(os.getpid(), info["pid"])
            self.assertTrue(info["owner_alive"])
            with self.assertRaisesRegex(PersistenceLockError, "still alive"):
                store.clear_stale_lock(expected_pid=os.getpid(), minimum_age_seconds=0)
        self.root.mkdir(parents=True, exist_ok=True)
        dead_pid = 2_000_000_000
        store.lock_path.write_text(
            json.dumps({"pid": dead_pid, "created_at": "2000-01-01T00:00:00+00:00"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(PersistenceLockError, "PID changed"):
            store.clear_stale_lock(expected_pid=dead_pid - 1, minimum_age_seconds=0)
        store.clear_stale_lock(expected_pid=dead_pid, minimum_age_seconds=0)
        self.assertFalse(store.lock_path.exists())

    def test_recent_dead_lock_is_not_broken(self) -> None:
        store = LocalProjectStore(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        dead_pid = 2_000_000_000
        store.lock_path.write_text(
            json.dumps({"pid": dead_pid, "created_at": datetime.now(UTC).isoformat()}), encoding="utf-8"
        )
        with self.assertRaisesRegex(PersistenceLockError, "too recent"):
            store.clear_stale_lock(expected_pid=dead_pid, minimum_age_seconds=300)

    def test_write_phase_failures_release_lock_and_leave_recovery_path(self) -> None:
        phases = ("after_backup", "after_artifacts", "after_events", "before_state", "after_state")
        for phase in phases:
            with self.subTest(phase=phase):
                root = Path(self.temporary.name) / phase
                FounderOSApplication(root).new(
                    name=phase, founder_id="founder-1", founder_name="Founder", domain="Testing"
                )
                baseline = LocalProjectStore(root)
                runtime = baseline.load()
                project = runtime.repositories.projects.all()[0]
                ProjectStateService(runtime.repositories).update_details(
                    project["id"], expected_revision=project["revision"],
                    actor={"type": "human", "id": "founder-1", "display_name": "Founder"},
                    correlation_id=f"update-{phase}", next_action="Injected write",
                )
                def inject(current: str, target: str = phase) -> None:
                    if current == target:
                        raise OSError(f"injected {target}")
                failing = LocalProjectStore(root, failure_injector=inject)
                with self.assertRaisesRegex(OSError, phase):
                    failing.save(runtime)
                self.assertFalse(failing.lock_path.exists())
                health = baseline.health()
                self.assertTrue(health.primary_valid or health.recovery_recommended)
                if health.recovery_recommended:
                    self.assertEqual("healthy", baseline.recover().status)


if __name__ == "__main__":
    unittest.main()
