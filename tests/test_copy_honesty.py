"""Copy / honesty corrections (PR-180 Step 7).

Measured defects, each pinned: Settings described the SHIPPED
retention feature as unimplemented future work one card above the
control that runs it; the backup blurb listed exclusions and omitted
the one inclusion an attacker would want (user accounts with password
hashes); every disclosure about what Restore destroys arrived AFTER
the destruction; the Credentials page named its secure store as a
Python class while Settings named the same object in operator words;
three schedule messages carried exception-class suffixes; five
degraded banners offered a "Check System Integrity" link that 403s
for every non-admin; and console Disconnect ended another named
operator's live session behind a bare verb.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests.test_web_app import build_client, make_service

TEMPLATES = (Path(__file__).resolve().parents[1]
             / "src" / "founderos_atlas" / "web" / "templates")
SRC = Path(__file__).resolve().parents[1] / "src" / "founderos_atlas"


class SettingsCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.body = (TEMPLATES / "settings.html").read_text(encoding="utf-8")

    def test_retention_no_longer_contradicts_the_shipped_feature(self) -> None:
        self.assertNotIn("in this phase", self.body)
        self.assertNotIn("A future scheduled retention job", self.body)
        self.assertIn("Nothing is\n  removed until an administrator runs "
                      "Administration → Data retention", self.body)
        self.assertIn("previews\n  the exact records and requires a typed "
                      "confirmation", self.body)

    def test_backup_blurb_names_the_password_hash_inclusion(self) -> None:
        self.assertIn("user accounts (with password hashes only)", self.body)
        self.assertIn("protect the archive accordingly", self.body)

    def test_restore_states_what_it_replaces_before_the_click(self) -> None:
        # Categories, not filenames — and the two facts the operator
        # previously learned only from the success flash.
        for phrase in (
            "Restoring replaces the current workspace metadata",
            "your accounts (with password hashes), the audit log, "
            "annotations,\n    incidents, profiles, policy exceptions "
            "and schedules",
            "Atlas snapshots the current\n    files first",
            "a restart is required",
        ):
            self.assertIn(phrase, self.body, phrase)


class ProviderNameTests(unittest.TestCase):
    def test_the_credentials_page_speaks_operator_not_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            body = client.get("/credentials").get_data(as_text=True)
            self.assertNotIn("InMemoryCredentialProvider", body)
            self.assertIn("in-memory (non-persistent", body)

    def test_settings_and_credentials_share_one_mapping(self) -> None:
        from founderos_atlas.web.system_info import (
            _provider_name,
            provider_display_name,
        )

        # The private alias survives for the internal caller; both
        # names are one function.
        self.assertIs(_provider_name, provider_display_name)


class ScheduleErrorCopyTests(unittest.TestCase):
    def test_no_exception_class_reaches_schedule_copy(self) -> None:
        for relative in ("scheduling.py", "web/schedule_routes.py"):
            body = (SRC / relative).read_text(encoding="utf-8")
            self.assertNotIn("type(error).__name__", body, relative)

    def test_the_worker_state_is_canonical(self) -> None:
        import founderos_atlas.scheduling as scheduling

        body = (SRC / "scheduling.py").read_text(encoding="utf-8")
        self.assertIn("the last scheduler pass failed; the worker is", body)
        self.assertTrue(hasattr(scheduling, "ScheduleWorker"))


class IntegrityLinkGatingTests(unittest.TestCase):
    def test_every_degraded_banner_uses_the_gated_macro(self) -> None:
        # The raw link may appear in exactly two places: inside the
        # gate itself, and on the admin-only Settings card.
        offenders = []
        for path in sorted(TEMPLATES.glob("*.html")):
            if path.name in ("_degraded.html", "settings.html"):
                continue
            if 'href="/system/integrity"' in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual([], offenders)

    def test_a_non_admin_is_told_to_ask_not_sent_to_a_403(self) -> None:
        from founderos_atlas.access import UserStore
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            workspace = workdir / "workspace"
            service = make_service(workdir)
            UserStore(workspace).create(
                username="vera", roles=("viewer",),
                password="viewer-password-abc123",
            )
            # Corrupt annotations: the degraded banner renders on
            # /changes for every role.
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "annotations.json").write_text(
                '{"annotations": {broken', encoding="utf-8"
            )
            app = create_app(
                profile_service=service, output_dir=workdir / "out",
                history_root=workdir / "out" / ".atlas" / "history",
                workspace_root=workspace, auth_mode="password",
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            login = client.post("/login", data={
                "username": "vera", "password": "viewer-password-abc123",
            })
            self.assertEqual(302, login.status_code)
            body = client.get("/changes").get_data(as_text=True)
            self.assertIn('data-degraded="annotations"', body)
            self.assertIn("Ask an administrator to open System Integrity.",
                          body)
            self.assertNotIn('href="/system/integrity"', body)

    def test_an_admin_still_gets_the_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            workspace = workdir / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "annotations.json").write_text(
                '{"annotations": {broken', encoding="utf-8"
            )
            # Local mode: the process principal holds system.admin.
            _, client = build_client(workdir, make_service(workdir))
            body = client.get("/changes").get_data(as_text=True)
            self.assertIn('data-degraded="annotations"', body)
            self.assertIn('href="/system/integrity"', body)


class ConsoleDisconnectCopyTests(unittest.TestCase):
    def test_the_control_names_whose_session_dies_and_where(self) -> None:
        body = (TEMPLATES / "console_index.html").read_text(encoding="utf-8")
        self.assertIn(
            "Ends {{ item.operator }}'s live SSH session on "
            "{{ item.hostname }}",
            body,
        )
        self.assertIn(
            'aria-label="Disconnect {{ item.operator }}\'s live SSH session',
            body,
        )


if __name__ == "__main__":
    unittest.main()
