"""One line of product identity (PR-180 Step 2).

Measured before this change: version identity rendered on exactly two
system.admin-gated surfaces — across 14 pages, a viewer, investigator
or network-operator beta tester could reach NO build identity anywhere,
and the Settings page showed every role a "System information" jump
link whose anchor only admins receive. The chrome line closes that:
DISPLAY_VERSION plus the Beta token, for every IDENTIFIED principal,
on every page including error pages — and never the commit hash, and
never to an unauthenticated visitor.
"""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from founderos_atlas.release import (
    DISPLAY_VERSION,
    IDENTITY_LINE,
    IS_PRERELEASE,
    is_prerelease,
)

from tests.test_web_app import build_client, make_service


class PrereleaseDetectionTests(unittest.TestCase):
    def test_anchored_pep440_detection(self) -> None:
        # The adversarial pass killed the naive substring scan with the
        # first two rows: a dev build must not read as finished, and a
        # final release with local build metadata must not read as beta.
        cases = {
            "0.3.0a1": True,
            "0.3.0.dev1": True,
            "0.3.0a1.dev2": True,
            "1.2.0b3": True,
            "2.0.0rc1": True,
            "1.0.0": False,
            "1.0.0+build.5": False,
            "0.3.0.post1": False,
            "10.20.30": False,
        }
        for version, expected in cases.items():
            with self.subTest(version=version):
                self.assertEqual(expected, is_prerelease(version))

    def test_the_current_version_is_a_beta_and_the_line_says_so(self) -> None:
        # 0.3.0a1 is pre-release; when that changes, this pin and the
        # identity line change together in release.py.
        self.assertTrue(IS_PRERELEASE)
        self.assertEqual(f"{DISPLAY_VERSION} · Beta", IDENTITY_LINE)
        self.assertNotIn("channel", IDENTITY_LINE.lower())


class IdentityChromeTests(unittest.TestCase):
    def _footer(self, body: str) -> str | None:
        match = re.search(
            r'<footer class="app-identity">([^<]*)</footer>', body
        )
        return match.group(1).strip() if match else None

    def test_every_identified_page_carries_the_line_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            for path in ("/", "/settings", "/discovery", "/timeline"):
                body = client.get(path).get_data(as_text=True)
                self.assertEqual(IDENTITY_LINE, self._footer(body), path)

    def test_error_pages_carry_the_line_for_an_identified_principal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            body = client.get("/no-such-page").get_data(as_text=True)
            self.assertEqual(IDENTITY_LINE, self._footer(body))

    def test_the_chrome_line_never_carries_a_commit_hash(self) -> None:
        # The footer renders the IDENTITY_LINE constant and nothing
        # else; the commit hash stays on the system.admin Settings
        # card, the update page, diagnostics and the CLI.
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            footer = self._footer(client.get("/").get_data(as_text=True))
            self.assertEqual(IDENTITY_LINE, footer)
            self.assertNotIn("build", footer.lower())
            self.assertIsNone(re.search(r"\b[0-9a-f]{7,12}\b", footer))

    def test_the_posture_line_names_security_not_build_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_client(workdir, make_service(workdir))
            body = client.get("/").get_data(as_text=True)
            self.assertIn("Single-operator access · loopback only", body)
            self.assertNotIn("Local development mode", body)


class UnauthenticatedSurfaceTests(unittest.TestCase):
    def _password_app(self, workdir: Path):
        from founderos_atlas.access import UserStore
        from founderos_atlas.web import create_app

        workspace = workdir / "workspace"
        service = make_service(workdir)
        users = UserStore(workspace)
        users.create(username="vera", roles=("viewer",),
                     password="viewer-password-abc123")
        users.create(username="root", roles=("system-admin",),
                     password="admin-password-abc1234")
        app = create_app(
            profile_service=service, output_dir=workdir / "out",
            history_root=workdir / "out" / ".atlas" / "history",
            workspace_root=workspace, auth_mode="password",
        )
        app.config.update(TESTING=True)
        return app

    def _login(self, app, username: str, password: str):
        client = app.test_client()
        response = client.post("/login", data={
            "username": username, "password": password,
        })
        self.assertEqual(302, response.status_code)
        return client

    def test_the_login_screen_reveals_no_build_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._password_app(Path(tmp))
            body = app.test_client().get("/login").get_data(as_text=True)
            self.assertNotIn("app-identity", body)
            self.assertNotIn(DISPLAY_VERSION, body)

    def test_an_authenticated_viewer_finally_sees_the_version(self) -> None:
        # The measured gap: across 14 pages, non-admin roles could
        # reach no build identity at all.
        with tempfile.TemporaryDirectory() as tmp:
            app = self._password_app(Path(tmp))
            client = self._login(app, "vera", "viewer-password-abc123")
            body = client.get("/settings").get_data(as_text=True)
            self.assertIn(IDENTITY_LINE, body)

    def test_the_jump_link_renders_only_with_its_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._password_app(Path(tmp))
            viewer = self._login(
                app, "vera", "viewer-password-abc123"
            ).get("/settings").get_data(as_text=True)
            admin = self._login(
                app, "root", "admin-password-abc1234"
            ).get("/settings").get_data(as_text=True)
            self.assertNotIn('href="#system-information"', viewer)
            self.assertNotIn('id="system-information"', viewer)
            self.assertIn('href="#system-information"', admin)
            self.assertIn('id="system-information"', admin)


if __name__ == "__main__":
    unittest.main()
