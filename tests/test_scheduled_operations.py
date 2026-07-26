"""Durable scheduling, leases and maintenance-window behavior."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from founderos_atlas.scheduling import (
    MISFIRE_SKIP,
    RECURRENCE_DAILY,
    RECURRENCE_INTERVAL,
    RECURRENCE_ONCE,
    RUN_FAILED,
    RUN_SUCCEEDED,
    ScheduleConflictError,
    ScheduleStore,
    ScheduleWorker,
    resolve_local_datetime,
)


UTC = timezone.utc


class ScheduledOperationsTests(unittest.TestCase):
    def test_due_schedule_is_claimed_once_with_durable_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store.create_schedule(
                profile_id="delhi",
                name="Delhi hourly",
                recurrence=RECURRENCE_INTERVAL,
                timezone_name="UTC",
                first_run_at=due,
                interval_minutes=60,
            )
            claimed = store.claim_due(worker_id="worker-1", now=due)
            self.assertEqual(1, len(claimed))
            self.assertEqual(
                [], store.claim_due(worker_id="worker-2", now=due)
            )
            reloaded = ScheduleStore(tmp)
            self.assertEqual(
                [], reloaded.claim_due(worker_id="worker-3", now=due)
            )

    def test_completion_advances_interval_and_releases_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            schedule = store.create_schedule(
                profile_id="delhi",
                name="Delhi hourly",
                recurrence=RECURRENCE_INTERVAL,
                timezone_name="UTC",
                first_run_at=due,
                interval_minutes=60,
            )
            run = store.claim_due(worker_id="worker", now=due)[0]
            completed = store.complete_run(
                run.run_id,
                status=RUN_SUCCEEDED,
                now=due + timedelta(minutes=10),
            )
            self.assertEqual(RUN_SUCCEEDED, completed.status)
            updated = next(
                item for item in store.schedules()
                if item.schedule_id == schedule.schedule_id
            )
            self.assertEqual(
                datetime(2026, 7, 26, 11, 0, tzinfo=UTC),
                datetime.fromisoformat(updated.next_run_at),
            )
            self.assertIsNone(updated.lease_owner)
            self.assertIsNone(updated.active_run_id)

    def test_once_schedule_disables_after_terminal_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store.create_schedule(
                profile_id="delhi",
                name="One time",
                recurrence=RECURRENCE_ONCE,
                timezone_name="UTC",
                first_run_at=due,
            )
            run = store.claim_due(worker_id="worker", now=due)[0]
            store.complete_run(run.run_id, status=RUN_FAILED, now=due)
            self.assertFalse(store.schedules()[0].enabled)

    def test_daily_schedule_is_timezone_and_dst_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 3, 8, 6, 30, tzinfo=UTC)
            store.create_schedule(
                profile_id="new-york",
                name="Daily local",
                recurrence=RECURRENCE_DAILY,
                timezone_name="America/New_York",
                first_run_at=due,
                daily_time="02:30",
            )
            run = store.claim_due(worker_id="worker", now=due)[0]
            store.complete_run(run.run_id, status=RUN_SUCCEEDED, now=due)
            following = datetime.fromisoformat(
                store.schedules()[0].next_run_at
            )
            self.assertGreater(following, due)
            self.assertIsNotNone(following.tzinfo)

    def test_daily_dst_gap_and_fold_have_documented_single_run_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spring = ScheduleStore(Path(tmp) / "spring")
            spring_due = datetime(2026, 3, 7, 7, 30, tzinfo=UTC)
            spring.create_schedule(
                profile_id="new-york",
                name="Spring daily",
                recurrence=RECURRENCE_DAILY,
                timezone_name="America/New_York",
                first_run_at=spring_due,
                daily_time="02:30",
            )
            run = spring.claim_due(worker_id="worker", now=spring_due)[0]
            spring.complete_run(run.run_id, status=RUN_SUCCEEDED, now=spring_due)
            self.assertEqual(
                datetime(2026, 3, 8, 7, 0, tzinfo=UTC),
                datetime.fromisoformat(spring.schedules()[0].next_run_at),
            )

            fall = ScheduleStore(Path(tmp) / "fall")
            fall_due = datetime(2026, 10, 31, 5, 30, tzinfo=UTC)
            fall.create_schedule(
                profile_id="new-york",
                name="Fall daily",
                recurrence=RECURRENCE_DAILY,
                timezone_name="America/New_York",
                first_run_at=fall_due,
                daily_time="01:30",
            )
            run = fall.claim_due(worker_id="worker", now=fall_due)[0]
            fall.complete_run(run.run_id, status=RUN_SUCCEEDED, now=fall_due)
            self.assertEqual(
                datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
                datetime.fromisoformat(fall.schedules()[0].next_run_at),
            )

    def test_one_time_dst_gap_and_fold_are_rejected_without_offset(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_local_datetime(
                datetime(2026, 3, 8, 2, 30), "America/New_York"
            )
        with self.assertRaisesRegex(ValueError, "occurs twice"):
            resolve_local_datetime(
                datetime(2026, 11, 1, 1, 30), "America/New_York"
            )
        explicit = datetime.fromisoformat("2026-11-01T01:30:00-05:00")
        self.assertEqual(
            explicit,
            resolve_local_datetime(explicit, "America/New_York"),
        )

    def test_maintenance_windows_are_scope_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store.add_maintenance_window(
                name="Delhi change",
                starts_at=now - timedelta(minutes=5),
                ends_at=now + timedelta(hours=1),
                timezone_name="Asia/Kolkata",
                scope_type="profile",
                scope_id="delhi",
                reason="CAB-123",
            )
            self.assertEqual(
                1, len(store.active_maintenance(now=now, profile_id="delhi"))
            )
            self.assertEqual(
                [], store.active_maintenance(now=now, profile_id="mumbai")
            )

    def test_catalog_revision_prevents_lost_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            expected = store.revision()
            store.create_schedule(
                profile_id="delhi",
                name="First",
                recurrence=RECURRENCE_ONCE,
                timezone_name="UTC",
                first_run_at=due,
                expected_revision=expected,
            )
            with self.assertRaises(ScheduleConflictError):
                store.create_schedule(
                    profile_id="mumbai",
                    name="Stale",
                    recurrence=RECURRENCE_ONCE,
                    timezone_name="UTC",
                    first_run_at=due,
                    expected_revision=expected,
                )

    def test_failed_run_uses_bounded_retry_then_returns_to_recurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store.create_schedule(
                profile_id="delhi",
                name="Retry once",
                recurrence=RECURRENCE_ONCE,
                timezone_name="UTC",
                first_run_at=due,
                max_retries=1,
                retry_delay_minutes=5,
            )
            first = store.claim_due(worker_id="worker", now=due)[0]
            store.complete_run(first.run_id, status=RUN_FAILED, now=due)
            retry_schedule = store.schedules()[0]
            self.assertTrue(retry_schedule.enabled)
            self.assertEqual(2, retry_schedule.retry_attempt)
            retry = store.claim_due(
                worker_id="worker", now=due + timedelta(minutes=5)
            )[0]
            self.assertEqual(2, retry.attempt)
            store.complete_run(
                retry.run_id,
                status=RUN_SUCCEEDED,
                now=due + timedelta(minutes=6),
            )
            self.assertFalse(store.schedules()[0].enabled)

    def test_interval_retry_preserves_original_recurrence_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store.create_schedule(
                profile_id="delhi",
                name="Hourly with retry",
                recurrence=RECURRENCE_INTERVAL,
                timezone_name="UTC",
                first_run_at=due,
                interval_minutes=60,
                max_retries=1,
                retry_delay_minutes=5,
            )
            first = store.claim_due(worker_id="worker", now=due)[0]
            store.complete_run(first.run_id, status=RUN_FAILED, now=due)
            retry = store.claim_due(
                worker_id="worker", now=due + timedelta(minutes=5)
            )[0]
            store.complete_run(
                retry.run_id,
                status=RUN_SUCCEEDED,
                now=due + timedelta(minutes=6),
            )
            self.assertEqual(
                datetime(2026, 7, 26, 11, 0, tzinfo=UTC),
                datetime.fromisoformat(store.schedules()[0].next_run_at),
            )

    def test_misfire_skip_does_not_launch_old_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store.create_schedule(
                profile_id="delhi",
                name="Skip stale",
                recurrence=RECURRENCE_INTERVAL,
                timezone_name="UTC",
                first_run_at=due,
                interval_minutes=60,
                misfire_policy=MISFIRE_SKIP,
            )
            self.assertEqual(
                [],
                store.claim_due(
                    worker_id="worker",
                    now=due + timedelta(minutes=10),
                ),
            )
            self.assertEqual("skipped-misfire", store.schedules()[0].last_status)

    def test_expired_lease_is_failed_and_retried_without_duplicate_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ScheduleStore(tmp)
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store.create_schedule(
                profile_id="delhi",
                name="Recover",
                recurrence=RECURRENCE_ONCE,
                timezone_name="UTC",
                first_run_at=due,
                max_retries=1,
                retry_delay_minutes=5,
            )
            first = store.claim_due(
                worker_id="lost-worker", now=due, lease_seconds=30
            )[0]
            self.assertEqual(
                [],
                store.claim_due(
                    worker_id="new-worker",
                    now=due + timedelta(seconds=31),
                ),
            )
            recovered = next(
                item for item in store.runs() if item.run_id == first.run_id
            )
            self.assertEqual(RUN_FAILED, recovered.status)
            self.assertIn("lease expired", recovered.error)
            retry = store.claim_due(
                worker_id="new-worker",
                now=due + timedelta(minutes=5, seconds=31),
            )
            self.assertEqual(1, len(retry))
            self.assertEqual(2, retry[0].attempt)
            self.assertNotEqual(first.idempotency_key, retry[0].idempotency_key)

    def test_worker_connects_claim_to_existing_job_manager(self) -> None:
        class Profile:
            profile_id = "delhi"
            name = "Delhi"

        class Profiles:
            def list_profiles(self):
                return [Profile()]

        class Job:
            job_id = "job-1"
            status = "completed"
            error = None

        class Jobs:
            def __init__(self):
                self.job = Job()

            def start(self, name):
                self.job.status = "running"
                return self.job, True

            def get(self, job_id):
                return self.job

        with tempfile.TemporaryDirectory() as tmp:
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store = ScheduleStore(tmp)
            store.create_schedule(
                profile_id="delhi",
                name="Daily",
                recurrence=RECURRENCE_INTERVAL,
                timezone_name="UTC",
                first_run_at=due,
                interval_minutes=60,
            )
            jobs = Jobs()
            worker = ScheduleWorker(
                store=store,
                job_manager=jobs,
                profile_service=Profiles(),
                worker_id="worker",
                clock=lambda: due,
            )
            self.assertEqual(1, worker.tick())
            jobs.job.status = "completed"
            worker.tick()
            self.assertEqual(RUN_SUCCEEDED, store.runs()[0].status)

    def test_worker_heartbeats_long_running_job_and_restart_reconciles_it(self) -> None:
        class Profile:
            profile_id = "delhi"
            name = "Delhi"

        class Profiles:
            def list_profiles(self):
                return [Profile()]

        class Job:
            job_id = "job-durable"
            status = "running"
            error = None

        class Jobs:
            job = Job()

            def start(self, name):
                return self.job, True

            def get(self, job_id):
                return self.job

        with tempfile.TemporaryDirectory() as tmp:
            moment = [datetime(2026, 7, 26, 10, 0, tzinfo=UTC)]
            store = ScheduleStore(tmp)
            store.create_schedule(
                profile_id="delhi",
                name="Long running",
                recurrence=RECURRENCE_INTERVAL,
                timezone_name="UTC",
                first_run_at=moment[0],
                interval_minutes=60,
            )
            jobs = Jobs()
            first_worker = ScheduleWorker(
                store=store,
                job_manager=jobs,
                profile_service=Profiles(),
                worker_id="worker",
                clock=lambda: moment[0],
            )
            self.assertEqual(1, first_worker.tick())
            persisted = store.runs()[0]
            self.assertEqual("job-durable", persisted.job_id)

            moment[0] += timedelta(minutes=6)
            self.assertEqual(0, first_worker.tick())
            self.assertEqual("claimed", store.runs()[0].status)

            jobs.job.status = "interrupted"
            restarted = ScheduleWorker(
                store=ScheduleStore(tmp),
                job_manager=jobs,
                profile_service=Profiles(),
                worker_id="worker",
                clock=lambda: moment[0],
            )
            restarted.tick()
            self.assertEqual(RUN_FAILED, store.runs()[0].status)

    def test_two_due_schedules_can_share_one_deduplicated_profile_job(self) -> None:
        class Profile:
            profile_id = "delhi"
            name = "Delhi"

        class Profiles:
            def list_profiles(self):
                return [Profile()]

        class Job:
            job_id = "shared-job"
            status = "running"
            error = None

        class Jobs:
            job = Job()
            starts = 0

            def start(self, name):
                self.starts += 1
                return self.job, self.starts == 1

            def get(self, job_id):
                return self.job

        with tempfile.TemporaryDirectory() as tmp:
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store = ScheduleStore(tmp)
            for name in ("Morning inventory", "Compliance refresh"):
                store.create_schedule(
                    profile_id="delhi",
                    name=name,
                    recurrence=RECURRENCE_ONCE,
                    timezone_name="UTC",
                    first_run_at=due,
                )
            jobs = Jobs()
            worker = ScheduleWorker(
                store=store,
                job_manager=jobs,
                profile_service=Profiles(),
                worker_id="worker",
                clock=lambda: due,
            )
            self.assertEqual(2, worker.tick())
            self.assertEqual(
                {"shared-job"}, {run.job_id for run in store.runs()}
            )
            jobs.job.status = "completed"
            worker.tick()
            self.assertEqual(
                {RUN_SUCCEEDED}, {run.status for run in store.runs()}
            )

    def test_maintenance_does_not_cancel_scheduled_collection(self) -> None:
        class Profile:
            profile_id = "delhi"
            name = "Delhi"

        class Profiles:
            def list_profiles(self):
                return [Profile()]

        class Job:
            job_id = "job-maintenance"
            status = "running"
            error = None

        class Jobs:
            def start(self, name):
                return Job(), True

            def get(self, job_id):
                return Job()

        with tempfile.TemporaryDirectory() as tmp:
            due = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            store = ScheduleStore(tmp)
            store.create_schedule(
                profile_id="delhi",
                name="During maintenance",
                recurrence=RECURRENCE_ONCE,
                timezone_name="UTC",
                first_run_at=due,
            )
            store.add_maintenance_window(
                name="CAB",
                starts_at=due - timedelta(minutes=1),
                ends_at=due + timedelta(hours=1),
                timezone_name="UTC",
                scope_type="profile",
                scope_id="delhi",
                reason="Approved maintenance",
            )
            worker = ScheduleWorker(
                store=store,
                job_manager=Jobs(),
                profile_service=Profiles(),
                worker_id="worker",
                clock=lambda: due,
            )
            self.assertEqual(1, worker.tick())
            self.assertEqual("claimed", store.runs()[0].status)


class ScheduledOperationWebTests(unittest.TestCase):
    def test_routes_enforce_permission_csrf_and_required_revision(self) -> None:
        from tests.test_production_security import production_world, sign_in

        valid_window = {
            "name": "CAB",
            "starts_at": "2026-07-26T10:00",
            "ends_at": "2026-07-26T11:00",
            "timezone_name": "UTC",
            "scope_type": "global",
            "reason": "Approved maintenance",
            "suppress_notifications": "1",
        }
        with production_world() as (app, work):
            viewer, viewer_csrf = sign_in(app, "viewer")
            self.assertEqual(200, viewer.get("/schedules").status_code)
            denied = viewer.post(
                "/schedules/maintenance",
                data={**valid_window, "_csrf": viewer_csrf},
            )
            self.assertEqual(403, denied.status_code)

            admin, csrf = sign_in(app, "admin")
            missing_csrf = admin.post(
                "/schedules/maintenance", data=valid_window
            )
            self.assertEqual(403, missing_csrf.status_code)
            stale = admin.post(
                "/schedules/maintenance",
                data={**valid_window, "_csrf": csrf},
            )
            self.assertEqual(302, stale.status_code)
            store = ScheduleStore(work / "workspace")
            self.assertEqual([], store.maintenance_windows())

            accepted = admin.post(
                "/schedules/maintenance",
                data={
                    **valid_window,
                    "_csrf": csrf,
                    "expected_revision": str(store.revision()),
                },
            )
            self.assertEqual(302, accepted.status_code)
            self.assertEqual(1, len(store.maintenance_windows()))

            schedule = store.create_schedule(
                profile_id="delhi",
                name="Operator-owned schedule",
                recurrence=RECURRENCE_ONCE,
                timezone_name="UTC",
                first_run_at=datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
            )
            operator, operator_csrf = sign_in(app, "operator")
            paused = operator.post(
                f"/schedules/{schedule.schedule_id}/state",
                data={
                    "_csrf": operator_csrf,
                    "expected_revision": str(store.revision()),
                    "enabled": "0",
                },
            )
            self.assertEqual(302, paused.status_code)
            self.assertFalse(
                next(
                    item for item in store.schedules()
                    if item.schedule_id == schedule.schedule_id
                ).enabled
            )

    def test_corrupt_catalog_is_reported_without_overwrite(self) -> None:
        from founderos_atlas.web import create_app
        from founderos_atlas.workspace.integrity import verify_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            catalog = workspace / "schedules.json"
            catalog.write_text("{broken", encoding="utf-8")
            app = create_app(
                output_dir=root / "out", workspace_root=workspace
            )
            app.config.update(TESTING=True)
            response = app.test_client().get("/schedules")
            self.assertEqual(200, response.status_code)
            self.assertIn(
                "Catalog unavailable", response.get_data(as_text=True)
            )
            self.assertEqual("{broken", catalog.read_text(encoding="utf-8"))
            status = next(
                item for item in verify_workspace(workspace)
                if item.name == "schedules.json"
            )
            self.assertEqual("corrupt", status.state)

    def test_restore_rejects_semantically_invalid_schedule_catalog(self) -> None:
        import json

        from founderos_atlas.workspace.backup import build_backup
        from founderos_atlas.workspace.restore import RestoreError, perform_restore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "schedules.json").write_text(
                json.dumps({
                    "schema_version": "1.0.0",
                    "revision": 1,
                    "schedules": [{
                        "schedule_id": "bad",
                        "profile_id": "delhi",
                        "name": "Invalid",
                        "recurrence": "whenever",
                        "timezone_name": "UTC",
                        "next_run_at": "2026-07-26T10:00:00+00:00",
                        "created_at": "2026-07-26T09:00:00+00:00",
                        "updated_at": "2026-07-26T09:00:00+00:00",
                    }],
                    "runs": [],
                    "maintenance_windows": [],
                }),
                encoding="utf-8",
            )
            archive, _manifest = build_backup(source)
            destination = root / "destination"
            destination.mkdir()
            with self.assertRaises(RestoreError):
                perform_restore(destination, archive)
            self.assertFalse((destination / "schedules.json").exists())

    def test_active_maintenance_suppresses_only_failure_notification(self) -> None:
        from founderos_atlas.notifications import NotificationStore
        from founderos_atlas.web import create_app

        class Job:
            profile_id = "delhi"
            profile_name = "Delhi"
            site = "Delhi"
            job_id = "job-failed"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            app = create_app(
                output_dir=root / "out",
                workspace_root=workspace,
                clock=lambda: now,
            )
            ScheduleStore(workspace).add_maintenance_window(
                name="Quiet CAB",
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(minutes=30),
                timezone_name="UTC",
                scope_type="profile",
                scope_id="delhi",
                suppress_notifications=True,
                reason="Approved maintenance",
            )
            callback = app.config["ATLAS_JOB_MANAGER"]._on_failure
            self.assertIsNotNone(callback)
            with patch.object(NotificationStore, "notify") as notify:
                callback(Job())
                notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
