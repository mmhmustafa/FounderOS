"""Completed administration workflows (PR-059).

Wizard multi-value drafts, honest credential connection testing, evidence
saved filters, retention preview/protections/manifest, update info, and
the structured-editor / chip enhancement — all with secret-hygiene and
RBAC checks.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.test_polish import build_world
from tests.test_production_security import (
    PASSWORDS,
    production_world,
    sign_in,
)


class WizardDraftTests(unittest.TestCase):
    def test_candidate_preview_reports_platform_support_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            response = client.post(
                "/discovery/wizard/preview",
                data={
                    "name": "Support preview",
                    "mode": "seed",
                    "seed": "10.0.0.1",
                    "policy": "balanced",
                    "max_depth": "1",
                    "max_devices": "8",
                    "timeout_seconds": "5",
                    "concurrency": "1",
                },
            )
            page = response.get_data(as_text=True)
            self.assertEqual(200, response.status_code)
            self.assertIn("Supported platforms:", page)
            self.assertIn("Platform support", page)
            self.assertIn("Pending identity probe", page)

    def test_every_credential_set_survives_a_form_draft_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            # Two credential sets selected — the old flatten kept only one.
            response = client.post("/api/discovery/wizard/drafts", data={
                "name": "Multi",
                "mode": "seed",
                "credential_sets": ["set-a", "set-b", "set-c"],
            })
            draft_id = response.get_json()["draft_id"]
            from founderos_atlas.workspace.administration import (
                AdministrationRepository,
            )

            draft = AdministrationRepository(
                workdir / "workspace"
            ).get_draft(draft_id)
            self.assertEqual(
                ["set-a", "set-b", "set-c"], draft["credential_sets"]
            )

    def test_json_autosave_preserves_arrays_and_excludes_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            response = client.post(
                "/api/discovery/wizard/drafts",
                json={
                    "name": "JSON draft",
                    "credential_sets": ["set-a", "set-b"],
                    "password": "must-not-persist-1",
                    "seed": "10.0.0.1",
                },
            )
            draft_id = response.get_json()["draft_id"]
            from founderos_atlas.workspace.administration import (
                AdministrationRepository,
            )

            draft = AdministrationRepository(
                workdir / "workspace"
            ).get_draft(draft_id)
            self.assertEqual(["set-a", "set-b"], draft["credential_sets"])
            self.assertNotIn("password", draft)
            raw = (workdir / "workspace" / "discovery_drafts.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("must-not-persist-1", raw)

    def test_resume_picker_lists_newest_draft_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            older = client.post("/api/discovery/wizard/drafts", data={
                "name": "Older draft", "mode": "seed",
            }).get_json()["draft_id"]
            import time as _time
            _time.sleep(0.02)
            newer = client.post("/api/discovery/wizard/drafts", data={
                "name": "Newer draft", "mode": "seed",
            }).get_json()["draft_id"]
            page = client.get("/discovery/wizard").get_data(as_text=True)
            self.assertLess(
                page.index(newer), page.index(older),
                "the resume picker must list the newest draft first",
            )

    def test_single_credential_set_is_still_stored_as_a_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            response = client.post("/api/discovery/wizard/drafts", data={
                "name": "One", "credential_sets": "only-set",
            })
            from founderos_atlas.workspace.administration import (
                AdministrationRepository,
            )

            draft = AdministrationRepository(workdir / "workspace").get_draft(
                response.get_json()["draft_id"]
            )
            self.assertEqual(["only-set"], draft["credential_sets"])


class ConnectionTestTests(unittest.TestCase):
    def _service(self, workdir):
        from founderos_atlas.credentials.repository import (
            CredentialSetRepository,
        )
        from founderos_atlas.credentials.service import CredentialSetService
        from founderos_atlas.workspace.credentials import (
            InMemoryCredentialProvider,
        )

        provider = InMemoryCredentialProvider()
        service = CredentialSetService(
            CredentialSetRepository(workdir), provider,
        )
        service.add_entry(
            set_name="Lab", label="Admin", username="atlas",
            password="device-secret-123456",
        )
        return service, provider

    def test_production_default_factory_accepts_the_built_config(self) -> None:
        """The web route falls back to SSHDeviceTransport as the factory,
        and SSHDeviceTransport type-checks for DeviceCredentials — the
        old ad-hoc config object made EVERY production connection test
        return transport-failed before a packet was sent. This pins the
        wire-up: the object test_connection builds must initialise the
        real transport (network stubbed out at the netmiko seam)."""

        from founderos_atlas.credentials.connection_test import (
            OUTCOME_IDENTIFIED,
            test_connection,
        )
        from founderos_atlas.transport import SSHDeviceTransport
        from founderos_atlas.workspace.credentials import (
            InMemoryCredentialProvider,
        )

        provider = InMemoryCredentialProvider()
        provider.save("ref", "secret-123456")

        class FakeNetmikoSession:
            def send_command(self, command, **kwargs):
                return "AtlasOS 1.0 device-core"

            def send_command_timing(self, command, **kwargs):
                return ""

            def disconnect(self):
                pass

        seen = {}

        def fake_netmiko(**kwargs):
            seen.update(kwargs)
            return FakeNetmikoSession()

        result = test_connection(
            target="10.0.0.1", credential_ref="ref", provider=provider,
            username="atlas",
            transport_factory=lambda config: SSHDeviceTransport(
                config, connection_factory=fake_netmiko,
            ),
        )
        self.assertEqual(OUTCOME_IDENTIFIED, result.outcome)
        self.assertEqual("10.0.0.1", seen.get("host"))
        self.assertEqual("atlas", seen.get("username"))

    def test_outcome_ladder_maps_each_failure_layer(self) -> None:
        from founderos_atlas.credentials.connection_test import (
            OUTCOME_AUTH_FAILED,
            OUTCOME_IDENTIFIED,
            OUTCOME_PROVIDER_UNREADABLE,
            OUTCOME_UNREACHABLE,
            test_connection,
        )
        from founderos_atlas.transport.exceptions import (
            AuthenticationError,
            SSHUnavailableError,
        )
        from founderos_atlas.workspace.credentials import (
            InMemoryCredentialProvider,
        )

        provider = InMemoryCredentialProvider()
        provider.save("ref", "secret-123456")

        # Provider unreadable.
        result = test_connection(
            target="10.0.0.1", credential_ref="missing", provider=provider,
            transport_factory=lambda c: None,
        )
        self.assertEqual(OUTCOME_PROVIDER_UNREADABLE, result.outcome)
        self.assertFalse(result.succeeded)

        class FakeTransport:
            def __init__(self, behavior):
                self.behavior = behavior

            def connect(self):
                if self.behavior == "unreachable":
                    raise SSHUnavailableError("no ssh")
                if self.behavior == "auth":
                    raise AuthenticationError("bad creds")

            def execute(self, command):
                return "AtlasOS 1.0 device-core\nmore lines"

            def disconnect(self):
                pass

        self.assertEqual(OUTCOME_UNREACHABLE, test_connection(
            target="10.0.0.1", credential_ref="ref", provider=provider,
            transport_factory=lambda c: FakeTransport("unreachable"),
        ).outcome)
        self.assertEqual(OUTCOME_AUTH_FAILED, test_connection(
            target="10.0.0.1", credential_ref="ref", provider=provider,
            transport_factory=lambda c: FakeTransport("auth"),
        ).outcome)
        ok = test_connection(
            target="10.0.0.1", credential_ref="ref", provider=provider,
            transport_factory=lambda c: FakeTransport("ok"),
        )
        self.assertEqual(OUTCOME_IDENTIFIED, ok.outcome)
        self.assertTrue(ok.succeeded)
        self.assertEqual("AtlasOS 1.0 device-core", ok.platform)

    def test_route_requires_target_audits_outcome_not_secret(self) -> None:
        with production_world() as (app, workdir):
            store = app.config["ATLAS_USER_STORE"]
            store.update("credadmin",
                         expected_revision=store.revision())  # touch: no-op
            admin, csrf = sign_in(app, "credadmin")
            admin.post("/credentials", data={
                "_csrf": csrf, "set_name": "Lab", "label": "Admin",
                "username": "atlas", "password": "device-secret-777",
            }, follow_redirects=True)
            # Missing target is refused.
            refused = admin.post(
                "/credentials/lab/admin/test-connection",
                data={"_csrf": csrf}, follow_redirects=True,
            )
            self.assertIn(b"authorized to test", refused.data)
            # A test against an unreachable target still audits the outcome,
            # never the password.
            admin.post(
                "/credentials/lab/admin/test-connection",
                data={"_csrf": csrf, "target": "203.0.113.200"},
                follow_redirects=True,
            )
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"test-connection"', audit)
            self.assertNotIn("device-secret-777", audit)

    def test_viewer_cannot_run_connection_test(self) -> None:
        with production_world() as (app, _):
            viewer, csrf = sign_in(app, "viewer")
            response = viewer.post(
                "/credentials/lab/admin/test-connection",
                data={"_csrf": csrf, "target": "10.0.0.1"},
            )
            self.assertEqual(403, response.status_code)


class SavedFilterTests(unittest.TestCase):
    def test_save_list_apply_rename_delete_persist_across_restart(self) -> None:
        from founderos_atlas.web.saved_filters import SavedFilterStore

        with tempfile.TemporaryDirectory() as tmp:
            store = SavedFilterStore(tmp)
            saved = store.save(
                owner="alice", surface="evidence", name="Failures",
                query="?status=failed&platform=ios&empty=",
            )
            # Empty values dropped, keys sorted, shareable.
            self.assertEqual("platform=ios&status=failed", saved.query)
            self.assertEqual(
                ["Failures"],
                [f.name for f in store.list(owner="alice", surface="evidence")],
            )
            # Scope isolation: bob sees nothing of alice's.
            self.assertEqual(
                [], store.list(owner="bob", surface="evidence")
            )
            store.rename(saved.filter_id, owner="alice", name="Renamed")
            # A fresh store over the same path (server restart).
            reopened = SavedFilterStore(tmp)
            self.assertEqual(
                ["Renamed"],
                [f.name for f in reopened.list(owner="alice",
                                               surface="evidence")],
            )
            self.assertTrue(reopened.delete(saved.filter_id, owner="alice"))
            self.assertEqual(
                [], reopened.list(owner="alice", surface="evidence")
            )

    def test_evidence_page_shows_server_saved_filters_not_localstorage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            client.post("/evidence/saved-filters", data={
                "name": "My view", "query": "status=failed",
            })
            page = client.get("/evidence?scope=all").data.decode("utf-8")
            self.assertIn("My view", page)
            self.assertIn("/evidence/saved-filters", page)
            self.assertNotIn("localStorage", page)


class RetentionTests(unittest.TestCase):
    def _history(self, root: Path, record_id: str, started_at: str) -> None:
        from founderos_atlas.history.models import DiscoveryRecord

        directory = root / record_id
        directory.mkdir(parents=True, exist_ok=True)
        record = DiscoveryRecord(
            record_id=record_id, started_at=started_at,
            completed_at=started_at, duration_seconds=1.0, device_count=1,
            relationship_count=0, warning_count=0, failures=(),
            configuration_status="collected", configured_device_count=1,
            quality_score=1.0, network_status="healthy",
            snapshot_id=f"snap-{record_id}",
        )
        (directory / "discovery_metadata.json").write_text(
            json.dumps(record.to_dict()), encoding="utf-8"
        )

    def test_preview_protects_latest_and_young_records(self) -> None:
        from founderos_atlas.workspace.retention import build_preview

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history"
            self._history(history, "2020-01-01_00-00-00",
                          "2020-01-01T00:00:00+00:00")   # very old
            self._history(history, "2020-06-01_00-00-00",
                          "2020-06-01T00:00:00+00:00")   # old
            self._history(history, "2999-01-01_00-00-00",
                          "2999-01-01T00:00:00+00:00")   # newest (future)
            preview = build_preview(
                history_roots={"lab": history}, retention_days=365,
                workspace_root=root,
            )
            reasons = {d.record_id: (d.removable, d.reason)
                       for d in preview.decisions}
            # Newest is protected regardless of age.
            self.assertFalse(reasons["2999-01-01_00-00-00"][0])
            self.assertIn("latest", reasons["2999-01-01_00-00-00"][1])
            # The two genuinely old ones are removable.
            self.assertTrue(reasons["2020-01-01_00-00-00"][0])
            self.assertTrue(reasons["2020-06-01_00-00-00"][0])

    def test_execute_removes_only_removable_and_writes_manifest(self) -> None:
        from founderos_atlas.workspace.retention import (
            build_preview,
            execute_retention,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history"
            self._history(history, "2020-01-01_00-00-00", "2020-01-01T00:00:00+00:00")
            self._history(history, "2999-01-01_00-00-00", "2999-01-01T00:00:00+00:00")
            preview = build_preview(
                history_roots={"lab": history}, retention_days=365,
                workspace_root=root,
            )
            manifest = execute_retention(
                history_roots={"lab": history}, preview=preview,
                workspace_root=root, actor="admin",
            )
            self.assertEqual(1, manifest["removed_count"])
            self.assertFalse((history / "2020-01-01_00-00-00").exists())
            self.assertTrue((history / "2999-01-01_00-00-00").exists())
            manifests = list((root / "retention-manifests").iterdir())
            self.assertTrue(manifests)

    def test_cancellation_before_delete_removes_nothing(self) -> None:
        from founderos_atlas.workspace.retention import (
            build_preview,
            execute_retention,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = root / "history"
            self._history(history, "2020-01-01_00-00-00", "2020-01-01T00:00:00+00:00")
            self._history(history, "2999-01-01_00-00-00", "2999-01-01T00:00:00+00:00")
            preview = build_preview(
                history_roots={"lab": history}, retention_days=365,
                workspace_root=root,
            )
            manifest = execute_retention(
                history_roots={"lab": history}, preview=preview,
                workspace_root=root, actor="admin",
                should_cancel=lambda: True,
            )
            self.assertEqual(0, manifest["removed_count"])
            self.assertTrue((history / "2020-01-01_00-00-00").exists())

    def test_route_requires_confirmation_and_is_admin_only(self) -> None:
        with production_world() as (app, _):
            viewer, vcsrf = sign_in(app, "viewer")
            self.assertEqual(
                403, viewer.get("/settings/retention").status_code
            )
            self.assertEqual(403, viewer.post(
                "/settings/retention/execute",
                data={"_csrf": vcsrf, "confirm": "DELETE OLD HISTORY"},
            ).status_code)
            admin, csrf = sign_in(app, "admin")
            self.assertEqual(
                200, admin.get("/settings/retention").status_code
            )
            wrong = admin.post(
                "/settings/retention/execute",
                data={"_csrf": csrf, "confirm": "nope"},
                follow_redirects=True,
            )
            self.assertIn(b"nothing was deleted", wrong.data)


class UpdateInfoTests(unittest.TestCase):
    def test_update_info_is_honest_without_a_provider(self) -> None:
        from founderos_atlas.workspace.update_info import update_information
        from founderos_atlas.release import VERSION

        with tempfile.TemporaryDirectory() as tmp:
            info = update_information(tmp)
            self.assertEqual(VERSION, info["application_version"])
            self.assertIsNotNone(info["schema_target"])
            self.assertEqual("unconfigured", info["update_provider"]["state"])
            self.assertIsNone(info["update_provider"]["latest_version"])

    def test_update_page_never_offers_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/system/update").data.decode("utf-8")
            self.assertIn("Application version", page)
            self.assertNotIn("Install update", page)
            self.assertNotIn("Download and install", page)
            self.assertIn("never checks for or installs", page)


class ChipEditorTests(unittest.TestCase):
    def test_chip_fields_are_present_and_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            form = client.get("/profiles/new").data.decode("utf-8")
            self.assertIn('data-chips data-chip-kind="cidr"', form)
            self.assertIn('data-chips data-chip-kind="ip"', form)
            self.assertIn("/static/atlas-chips.js", form)
            # The original comma-separated inputs remain (name preserved),
            # so a no-JS submit and stored records are unaffected.
            self.assertIn('name="include_cidrs"', form)
            self.assertIn('name="tags"', form)

    def test_chip_script_keeps_the_original_input_for_no_js(self) -> None:
        script = Path(
            "src/founderos_atlas/web/static/atlas-chips.js"
        ).read_text(encoding="utf-8")
        # The enhancement hides but keeps the named input the form submits.
        self.assertIn('input.type = "hidden"', script)
        self.assertIn("progressive enhancement", script.lower())


if __name__ == "__main__":
    unittest.main()
