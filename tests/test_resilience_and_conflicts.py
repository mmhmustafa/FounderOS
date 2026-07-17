"""Concurrency conflicts, undo, backup/restore, migrations, integrity,
job cancellation, and the notification inbox."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.test_production_security import (
    PASSWORDS,
    production_world,
    sign_in,
)


class ConflictTests(unittest.TestCase):
    def test_stale_profile_edit_is_a_409_not_an_overwrite(self) -> None:
        with production_world() as (app, workdir):
            client, csrf = sign_in(app, "operator")
            create = client.post("/profiles", data={
                "_csrf": csrf, "name": "Lab", "management_ip": "10.0.0.1",
                "username": "atlas", "password": "device-pass-123",
            })
            self.assertEqual(302, create.status_code, create.data[:300])
            from founderos_atlas.workspace import ProfileRepository

            repo = ProfileRepository(workdir / "workspace")
            revision = repo.revision()
            # Someone else edits meanwhile (any write bumps the revision).
            client.post("/profiles/Lab", data={
                "_csrf": csrf, "site": "Alpha",
                "expected_revision": str(revision),
            })
            stale = client.post("/profiles/Lab", data={
                "_csrf": csrf, "site": "Beta",
                "expected_revision": str(revision),
            })
            self.assertEqual(409, stale.status_code)
            self.assertIn(b"Nothing was overwritten", stale.data)
            # The first edit survived; the stale one changed nothing.
            self.assertEqual("Alpha", repo.get("Lab").site)

    def test_stale_policy_exception_edit_conflicts(self) -> None:
        from founderos_atlas.policy.exceptions import (
            PolicyExceptionConflictError,
            PolicyExceptionRepository,
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = PolicyExceptionRepository(tmp)
            revision = repo.revision()
            repo.grant(policy_id="P1", hostname="gw", reason="r",
                       owner="alice")
            with self.assertRaises(PolicyExceptionConflictError):
                repo.check_revision(revision)

    def test_stale_plan_edit_conflicts_and_edit_clears_approval(self) -> None:
        from founderos_atlas.compass.models import PlannedChange
        from founderos_atlas.compass.service import (
            PlanConflictError,
            PlanRepository,
            add_change,
            create_plan,
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = PlanRepository(tmp)
            plan = create_plan(
                repo, title="Window", maintenance_window="Sat",
                engineer="alice", created_at="2026-07-17T00:00:00+00:00",
            )
            revision = plan.revision
            add_change(repo, plan, PlannedChange(
                change_id="c1", device="gw", interface=None,
                change_type="configuration-change", reason="r",
            ), updated_at="2026-07-17T01:00:00+00:00")
            with self.assertRaises(PlanConflictError):
                repo.check_revision(plan.plan_id, revision)

    def test_stale_preferences_save_conflicts(self) -> None:
        from founderos_atlas.workspace.administration import (
            AdministrationRepository,
            PreferencesConflictError,
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = AdministrationRepository(tmp)
            repo.save_preferences({"theme": "dark"})
            with self.assertRaises(PreferencesConflictError):
                repo.save_preferences(
                    {"theme": "light"}, expected_updated_at="2001-01-01",
                )

    def test_conflicts_notify_and_audit(self) -> None:
        with production_world() as (app, workdir):
            client, csrf = sign_in(app, "admin")
            store = app.config["ATLAS_USER_STORE"]
            stale = client.post("/users", data={
                "_csrf": csrf, "username": "new-user",
                "password": "new-user-password-1", "roles": "viewer",
                "expected_revision": str(store.revision() + 5),
            })
            self.assertEqual(409, stale.status_code)
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"conflict"', audit)
            inbox = client.get("/inbox").data.decode("utf-8")
            self.assertIn("edit-conflict", inbox)


class UndoPreservationTests(unittest.TestCase):
    def test_site_override_undo_still_works_under_production_auth(self) -> None:
        """The topology override trails and their undo semantics predate
        this security work and must survive it unchanged."""

        from founderos_atlas.sites import (
            Site,
            SiteCatalog,
            SiteCatalogRepository,
            SiteOverrideRepository,
        )

        with production_world() as (app, workdir):
            SiteCatalogRepository(workdir / "workspace").save(
                SiteCatalog(sites=(Site(site_id="alpha", name="Alpha"),))
            )
            client, csrf = sign_in(app, "operator")
            payload = {
                "hostname": "dist2", "site_id": "alpha",
                "reason": "verified", "expected_revision": 0,
                "_csrf": csrf,
            }
            assigned = client.put(
                "/api/topology/site-assignments", json=payload,
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertEqual(200, assigned.status_code, assigned.data[:300])
            subject_key = assigned.get_json()["event"]["subject_key"]
            undone = client.post(
                "/api/topology/site-assignments/undo",
                json={"subject_key": subject_key, "expected_revision": 1},
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertEqual(200, undone.status_code, undone.data[:300])
            history = SiteOverrideRepository(workdir / "workspace").history()
            self.assertEqual(
                ["assign", "undo"], [event.action for event in history]
            )
            # Attribution: the authenticated operator, not a placeholder.
            self.assertEqual(
                {"operator"}, {event.actor for event in history}
            )


class BackupRestoreTests(unittest.TestCase):
    def test_backup_restores_into_a_fresh_workspace(self) -> None:
        with production_world() as (app, workdir):
            client, csrf = sign_in(app, "admin")
            backup = client.get("/settings/backup")
            self.assertEqual(200, backup.status_code)
            with zipfile.ZipFile(io.BytesIO(backup.data)) as archive:
                names = set(archive.namelist())
            self.assertIn("users.json", names)
            self.assertIn("audit.jsonl", names)

            restore = client.post(
                "/settings/restore",
                data={
                    "_csrf": csrf, "confirm": "RESTORE METADATA",
                    "reason": "drill",
                    "backup": (io.BytesIO(backup.data), "atlas-backup.zip"),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertIn(b"Metadata restored", restore.data)

    def test_restore_never_resurrects_sessions(self) -> None:
        with production_world() as (app, _):
            client, csrf = sign_in(app, "admin")
            evil = io.BytesIO()
            with zipfile.ZipFile(evil, "w") as archive:
                archive.writestr("sessions.json", json.dumps(
                    {"schema_version": "1.0.0", "sessions": []}
                ))
            evil.seek(0)
            response = client.post(
                "/settings/restore",
                data={
                    "_csrf": csrf, "confirm": "RESTORE METADATA",
                    "reason": "drill",
                    "backup": (evil, "bad.zip"),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertIn(b"no supported Atlas metadata", response.data)


class MigrationTests(unittest.TestCase):
    def test_legacy_workspace_gains_revisions_with_backup(self) -> None:
        from founderos_atlas.workspace.migrations import (
            applied_version,
            migrate_workspace,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = {"schema_version": "1.0.0", "profiles": []}
            (root / "profiles.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )
            applied = migrate_workspace(root)
            self.assertTrue(applied)
            migrated = json.loads(
                (root / "profiles.json").read_text(encoding="utf-8")
            )
            self.assertEqual(0, migrated["revision"])
            self.assertTrue(
                (root / "migration-backups" / "v1" / "profiles.json").is_file()
            )
            self.assertEqual(1, applied_version(root))
            # Idempotent: a second run applies nothing and changes nothing.
            self.assertEqual([], migrate_workspace(root))

    def test_migrations_run_at_app_start(self) -> None:
        from founderos_atlas.web import create_app
        from founderos_atlas.workspace.migrations import applied_version

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            (workspace / "profiles.json").write_text(
                json.dumps({"schema_version": "1.0.0", "profiles": []}),
                encoding="utf-8",
            )
            create_app(output_dir=tmp, workspace_root=workspace)
            self.assertGreaterEqual(applied_version(workspace), 1)


class IntegrityTests(unittest.TestCase):
    def test_corruption_is_detected_and_named(self) -> None:
        from founderos_atlas.workspace.integrity import verify_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profiles.json").write_text("{not json", encoding="utf-8")
            (root / "audit.jsonl").write_text(
                '{"ok": true}\n{broken\n', encoding="utf-8"
            )
            statuses = {item.name: item for item in verify_workspace(root)}
            self.assertEqual("corrupt", statuses["profiles.json"].state)
            self.assertEqual("corrupt", statuses["audit.jsonl"].state)
            self.assertIn("backup", statuses["profiles.json"].detail)
            self.assertEqual("missing", statuses["users.json"].state)

    def test_integrity_page_is_admin_only_and_reports(self) -> None:
        with production_world() as (app, workdir):
            (workdir / "workspace" / "policy-trend.json").write_text(
                "{broken", encoding="utf-8"
            )
            viewer, _ = sign_in(app, "viewer")
            self.assertEqual(403, viewer.get("/system/integrity").status_code)
            admin, _ = sign_in(app, "admin")
            page = admin.get("/system/integrity").data.decode("utf-8")
            self.assertIn("policy-trend.json", page)
            self.assertIn("corrupt", page)


class JobCancellationTests(unittest.TestCase):
    def test_cancel_stops_a_job_between_progress_events(self) -> None:
        import threading

        from founderos_atlas.web.jobs import DiscoveryJobManager

        release = threading.Event()

        class FakeProfile:
            profile_id = "p1"
            name = "Lab"
            site = None
            management_ip = "10.0.0.1"

        class FakeProfiles:
            def get_profile(self, name):
                return FakeProfile()

        def runner(profile_name, on_line, on_connect):
            on_connect("10.0.0.1")
            release.wait(5)
            on_line("[2/9] step ... running")   # cancellation lands here
            on_line("[9/9] done ... ok")
            return {}

        manager = DiscoveryJobManager(
            runner=runner, profile_service=FakeProfiles(),
        )
        job, created = manager.start("Lab")
        self.assertTrue(created)
        manager.request_cancel(job.job_id)
        release.set()
        finished = manager.wait(job.job_id, timeout=10)
        self.assertEqual("cancelled", finished.status)
        self.assertIn("cancelled", finished.message.casefold())

    def test_cancel_endpoint_requires_discovery_permission(self) -> None:
        with production_world() as (app, _):
            viewer, viewer_csrf = sign_in(app, "viewer")
            refused = viewer.post(
                "/api/discovery/jobs/xyz/cancel",
                headers={"X-Atlas-CSRF": viewer_csrf},
            )
            self.assertEqual(403, refused.status_code)
            operator, csrf = sign_in(app, "operator")
            missing = operator.post(
                "/api/discovery/jobs/xyz/cancel",
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertEqual(404, missing.status_code)


class NotificationTests(unittest.TestCase):
    def test_store_addresses_users_and_roles_separately(self) -> None:
        from founderos_atlas.notifications import NotificationStore

        with tempfile.TemporaryDirectory() as tmp:
            store = NotificationStore(tmp)
            store.notify(kind="assignment", title="For alice",
                         audience="alice")
            store.notify(kind="approval-request", title="For approvers",
                         audience="role:approver")
            alice = store.for_principal("alice", ("viewer",))
            self.assertEqual(["For alice"], [item.title for item in alice])
            approver = store.for_principal("bob", ("approver",))
            self.assertEqual(
                ["For approvers"], [item.title for item in approver]
            )
            self.assertEqual(1, store.unread_count("alice", ()))
            store.set_status(alice[0].notification_id, "done")
            self.assertEqual(0, store.unread_count("alice", ()))

    def test_analysed_plan_notifies_approvers_and_approval_flow(self) -> None:
        with production_world() as (app, workdir):
            operator, op_csrf = sign_in(app, "operator")
            created = operator.post("/compass/new", data={
                "_csrf": op_csrf, "title": "Reboot core2",
                "maintenance_window": "Sat 02:00", "engineer": "operator",
            })
            self.assertEqual(302, created.status_code)
            plan_id = created.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

            from founderos_atlas.compass.models import PlannedChange
            from founderos_atlas.compass.service import (
                PlanRepository,
                add_change,
            )

            repository = PlanRepository(app.config["ATLAS_OUTPUT_DIR"])
            plan, _ = repository.get(plan_id)
            # The HTTP add-change validates devices against discovery
            # evidence (none exists in this fixture), so the change is
            # seeded at the service layer; the approval flow under test
            # is unaffected.
            add_change(repository, plan, PlannedChange(
                change_id="c1", device="core2", interface=None,
                change_type="configuration-change", reason="maintenance",
            ), updated_at="2026-07-17T00:00:00+00:00")

            plan, _ = repository.get(plan_id)
            analysed = operator.post(f"/compass/{plan_id}/analyse", data={
                "_csrf": op_csrf, "expected_revision": str(plan.revision),
            }, follow_redirects=True)
            self.assertIn(b"approvers have been notified", analysed.data)

            approver, ap_csrf = sign_in(app, "approver")
            inbox = approver.get("/inbox").data.decode("utf-8")
            self.assertIn("Approval requested", inbox)

            # The operator cannot approve their own plan (no permission).
            plan, _ = repository.get(plan_id)
            self_approve = operator.post(f"/compass/{plan_id}/decision", data={
                "_csrf": op_csrf, "decision": "approve",
                "expected_revision": str(plan.revision),
            })
            self.assertEqual(403, self_approve.status_code)

            approved = approver.post(f"/compass/{plan_id}/decision", data={
                "_csrf": ap_csrf, "decision": "approve",
                "expected_revision": str(plan.revision),
            }, follow_redirects=True)
            self.assertIn(b"Plan approved", approved.data)
            plan, _ = repository.get(plan_id)
            self.assertEqual("approved", plan.status)
            self.assertEqual("approver", plan.approval["actor"])

            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"compass-plan"', audit)
            self.assertIn('"approve"', audit)

    def test_inbox_is_isolated_per_principal(self) -> None:
        from founderos_atlas.notifications import NotificationStore

        with production_world() as (app, workdir):
            NotificationStore(workdir / "workspace").notify(
                kind="assignment", title="Only for policy",
                audience="policy",
            )
            policy, _ = sign_in(app, "policy")
            viewer, _ = sign_in(app, "viewer")
            self.assertIn(b"Only for policy", policy.get("/inbox").data)
            self.assertNotIn(b"Only for policy", viewer.get("/inbox").data)


class ReadinessTests(unittest.TestCase):
    def test_password_mode_without_accounts_reports_degraded(self) -> None:
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(
                output_dir=tmp, workspace_root=Path(tmp) / "ws",
                auth_mode="password",
            )
            app.config.update(TESTING=True)
            response = app.test_client().get("/readyz")
            self.assertEqual(503, response.status_code)
            self.assertFalse(response.get_json()["components"]["user-store"])


if __name__ == "__main__":
    unittest.main()
