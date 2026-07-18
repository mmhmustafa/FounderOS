"""Prompt 5 administration workflows: persistence, safety, and web contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.credentials import (
    CredentialScope, CredentialSetRepository, CredentialSetService,
)
from founderos_atlas.workspace import (
    AdministrationRepository, InMemoryCredentialProvider,
    ProfileRepository, ProfileService,
)
from founderos_atlas.web import create_app


FIXED = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def client_for(root: Path):
    provider = InMemoryCredentialProvider()
    service = ProfileService(
        ProfileRepository(root / "workspace"), provider, clock=lambda: FIXED
    )
    app = create_app(
        profile_service=service, workspace_root=root / "workspace",
        output_dir=root / "out", history_root=root / "out" / ".atlas" / "history",
    )
    app.config.update(TESTING=True)
    return app.test_client(), service, provider


class AdministrationPersistenceTests(unittest.TestCase):
    def test_wizard_draft_survives_repository_restart_without_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = AdministrationRepository(root)
            draft_id = first.save_draft(None, {"name": "Lab", "cidr": "10.0.0.0/24"})
            loaded = AdministrationRepository(root).get_draft(draft_id)
            self.assertEqual("Lab", loaded["name"])
            self.assertNotIn("password", root.joinpath("discovery_drafts.json").read_text())

    def test_draft_store_structurally_rejects_secret_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                AdministrationRepository(tmp).save_draft(None, {"password": "never"})

    def test_preferences_round_trip_and_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = AdministrationRepository(tmp)
            saved = repo.save_preferences({
                "timezone": "UTC", "theme": "dark", "density": "compact",
                "retention_days": 90, "log_level": "WARNING",
            })
            self.assertEqual("dark", AdministrationRepository(tmp).preferences().theme)
            self.assertIsNotNone(saved.updated_at)
            self.assertEqual("system", repo.reset_preferences().theme)


class CredentialLifecycleTests(unittest.TestCase):
    def test_metadata_contains_lifecycle_but_never_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = InMemoryCredentialProvider()
            service = CredentialSetService(
                CredentialSetRepository(tmp), provider, clock=lambda: FIXED
            )
            created = service.add_entry(
                set_name="Lab", label="Routers", username="atlas",
                password="do-not-serialize", priority=10,
                scope=CredentialScope(cidrs=("10.0.0.0/24",)),
                rotation_due_at="2026-08-01", expires_at="2026-12-01",
            )
            entry = created.entries[0]
            self.assertTrue(service.test_store_access(created.set_id, entry.entry_id))
            text = Path(tmp, "credential_sets.json").read_text(encoding="utf-8")
            self.assertNotIn("do-not-serialize", text)
            self.assertIn("store-readable", text)


class AdministrationWebTests(unittest.TestCase):
    def test_wizard_api_drops_password_and_resumes_after_new_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, service, _provider = client_for(root)
            response = client.post("/api/discovery/wizard/drafts", json={
                "name": "Persistent Lab", "seed": "10.0.0.1",
                "password": "must-not-persist",
            })
            draft_id = response.get_json()["draft_id"]
            second, _service, _provider = client_for(root)
            page = second.get(f"/discovery/wizard?draft={draft_id}").get_data(as_text=True)
            self.assertIn("Persistent Lab", page)
            self.assertNotIn("must-not-persist", page)

    def test_settings_update_is_persistent_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, _service, _provider = client_for(root)
            response = client.post("/settings", data={
                "timezone": "UTC", "theme": "dark", "density": "compact",
                "retention_days": "180", "log_level": "INFO", "reason": "NOC standard",
            })
            self.assertEqual(302, response.status_code)
            self.assertEqual("dark", AdministrationRepository(root / "workspace").preferences().theme)
            audit = (root / "workspace" / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn("NOC standard", audit)
            self.assertNotIn("password", audit.casefold())

    def test_diagnostics_and_backup_explicitly_exclude_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            client, _service, _provider = client_for(Path(tmp))
            diagnostics = client.get("/settings/diagnostics.json")
            self.assertEqual(200, diagnostics.status_code)
            self.assertNotIn(b"password", diagnostics.data.lower())
            backup = client.get("/settings/backup")
            self.assertEqual("application/zip", backup.content_type)
            self.assertNotIn(b"password", backup.data.lower())

    def test_profiles_page_has_filters_and_structured_credential_picker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, service, _provider = client_for(root)
            service.add_profile(
                name="Campus", management_ip="10.0.0.1", username="atlas",
                password="not-rendered", owner="NOC", tags=("critical", "campus"),
            )
            page = client.get("/profiles?q=campus&status=active").get_data(as_text=True)
            self.assertIn("NOC", page)
            self.assertIn("critical", page)
            self.assertNotIn("not-rendered", page)
            form = client.get("/profiles/Campus/edit").get_data(as_text=True)
            self.assertIn("Credential sets", form)
            # Dirty-form protection moved to the external CSP-safe module,
            # activated by the data hook.
            self.assertIn("data-dirty-guard", form)


if __name__ == "__main__":
    unittest.main()
