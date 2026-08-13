"""Release identity, system truth, redirects, and SSH risk controls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from founderos_atlas.release import DISPLAY_VERSION, VERSION
from founderos_atlas.web.redirects import safe_redirect_target
from founderos_atlas.workspace import (
    InMemoryCredentialProvider,
    ProfileRepository,
    ProfileService,
)
from founderos_atlas.workspace.credentials import (
    EncryptedFileCredentialProvider,
    KeyringCredentialProvider,
)


class SafeRedirectTests(unittest.TestCase):
    VALID = (
        "/", "/inbox", "/policy?scope=lab&state=open",
        "/changes#review", "/search?q=https%3A%2F%2Fexample.test",
    )
    INVALID = (
        "", "dashboard", " https://evil.test", "https://evil.test",
        "//evil.test", "///evil.test", "/\\evil.test", "\\evil.test",
        "/%5cevil.test", "/%2f%2fevil.test", "/%252f%252fevil.test",
        "/%00evil", "/bad%2", "/bad%zz", "/line\nfeed",
        "javascript:alert(1)", "http:%2f%2fevil.test",
    )

    def test_preserves_safe_application_targets(self) -> None:
        for target in self.VALID:
            with self.subTest(target=target):
                self.assertEqual(target, safe_redirect_target(target, "/fallback"))

    def test_rejects_open_redirect_bypasses(self) -> None:
        for target in self.INVALID:
            with self.subTest(target=target):
                self.assertEqual("/fallback", safe_redirect_target(target, "/fallback"))

    def test_every_next_consumer_uses_the_central_validator(self) -> None:
        web = Path(__file__).resolve().parents[1] / "src" / "founderos_atlas" / "web"
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in web.glob("*.py")
        )
        self.assertNotIn('redirect(request.form.get("next")', combined)
        self.assertNotIn('redirect(request.args.get("next")', combined)
        self.assertNotIn('href=request.form.get("next")', combined)


class SystemInformationTests(unittest.TestCase):
    def _app(self, root: Path, provider, mode: str, *, tls: bool = False):
        from founderos_atlas.web import create_app

        service = ProfileService(ProfileRepository(root / "workspace"), provider)
        environment = {
            "ATLAS_AUTH_MODE": mode,
            "ATLAS_TLS": "1" if tls else "0",
            "ATLAS_PROXY_SECRET": "proxy-secret-at-least-16" if mode == "proxy" else "",
            "ATLAS_TRUSTED_PROXY_ADDRS": "127.0.0.1" if mode == "proxy" else "",
        }
        with patch.dict(os.environ, environment, clear=False):
            app = create_app(
                profile_service=service, workspace_root=root / "workspace",
                output_dir=root / "output", auth_mode=mode,
            )
        app.config.update(TESTING=True)
        return app

    def _info(self, app, provider):
        from founderos_atlas.web.system_info import collect_system_information
        from founderos_atlas.workspace import AdministrationRepository

        preferences = AdministrationRepository(
            app.config["ATLAS_WORKSPACE_ROOT"]
        ).preferences()
        return collect_system_information(
            app, credential_provider=provider, preferences=preferences,
        )

    def test_every_authentication_mode_and_tls_state_is_reported(self) -> None:
        for mode in ("local", "password", "proxy"):
            for tls in (False, True):
                with self.subTest(mode=mode, tls=tls), tempfile.TemporaryDirectory() as tmp:
                    provider = InMemoryCredentialProvider()
                    app = self._app(Path(tmp), provider, mode, tls=tls)
                    info = self._info(app, provider)
                    self.assertEqual(mode, info["authentication_mode"])
                    self.assertEqual(tls, info["tls_enabled"])
                    self.assertEqual(tls, info["hsts_enabled"])
                    self.assertEqual(VERSION, info["version"])
                    self.assertIn("one process", info["worker_model"])
                    self.assertIn(
                        "not observable", info["bind_observation"]
                    )
                    if mode == "proxy":
                        self.assertEqual(["127.0.0.1"], info["trusted_proxies"])

    def test_every_credential_provider_is_named_and_availability_is_effective(self) -> None:
        providers = (
            (InMemoryCredentialProvider(), "in-memory", True),
            (EncryptedFileCredentialProvider(key=b"x" * 32), "AES-256-GCM", True),
            (KeyringCredentialProvider(), "OS keyring", False),
        )
        for provider, label, available in providers:
            with self.subTest(provider=label), tempfile.TemporaryDirectory() as tmp:
                app = self._app(Path(tmp), provider, "local")
                with patch.object(provider, "available", return_value=available):
                    info = self._info(app, provider)
                self.assertIn(label, info["credential_provider"])
                self.assertEqual(available, info["credential_provider_available"])

    def test_diagnostics_and_settings_share_authoritative_tls_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = InMemoryCredentialProvider()
            app = self._app(Path(tmp), provider, "local", tls=True)
            diagnostics = app.test_client().get("/settings/diagnostics.json").get_json()
            page = app.test_client().get("/settings").get_data(as_text=True)
            self.assertTrue(diagnostics["tls_enabled"])
            self.assertEqual(VERSION, diagnostics["version"])
            self.assertIn(DISPLAY_VERSION, page)
            self.assertNotIn("local single-user", page)


class BuildIdentityTrustTests(unittest.TestCase):
    """PR-180 §3: an identifier is printed only when it provably
    describes the running bytes. A dirty tree describes bytes the
    commit does not; a foreign parent repository describes another
    project entirely. Both are worse than absence — a missing value
    announces its own absence, a wrong value announces confidence —
    so both resolve to None and share one causeless sentence.
    """

    def setUp(self) -> None:
        from founderos_atlas.release import build_commit

        build_commit.cache_clear()
        self.addCleanup(build_commit.cache_clear)

    def test_a_dirty_tree_suppresses_the_identifier(self) -> None:
        import founderos_atlas.release as release

        with patch.object(release, "_run_git",
                          return_value="abc1234-dirty"):
            self.assertIsNone(release.build_commit())

    def test_a_foreign_parent_repository_suppresses_the_identifier(self) -> None:
        import founderos_atlas.release as release

        def fake_git(repo, *args):
            if args[0] == "describe":
                return "b503ca1"
            # ls-files --error-unmatch: this file is NOT tracked by
            # the repository found two levels up — someone else's.
            return None

        with patch.object(release, "_run_git", side_effect=fake_git):
            self.assertIsNone(release.build_commit())

    def test_a_clean_own_repository_yields_the_described_identifier(self) -> None:
        import founderos_atlas.release as release

        def fake_git(repo, *args):
            if args[0] == "describe":
                return "bd50303"
            return "src/founderos_atlas/release.py"

        with patch.object(release, "_run_git", side_effect=fake_git):
            self.assertEqual("bd50303", release.build_commit())

    def test_absent_git_never_raises_and_yields_none(self) -> None:
        import founderos_atlas.release as release

        with patch.object(release.subprocess, "run",
                          side_effect=OSError("git is not installed")):
            self.assertIsNone(release.build_commit())

    def test_env_injection_wins_and_needs_no_git(self) -> None:
        import founderos_atlas.release as release

        environment = {"ATLAS_BUILD_ID": "beta.7+20260814"}
        with patch.dict(os.environ, environment, clear=False), \
                patch.object(release.subprocess, "run",
                             side_effect=AssertionError("git must not run")):
            self.assertEqual("beta.7+20260814", release.build_commit())

    def test_generated_module_seam_is_honoured(self) -> None:
        import sys as _sys
        import types

        import founderos_atlas.release as release

        stub = types.ModuleType("founderos_atlas._build_id")
        stub.BUILD_ID = "pkg-2026.08.14"
        with patch.dict(_sys.modules,
                        {"founderos_atlas._build_id": stub}), \
                patch.dict(os.environ, {"ATLAS_BUILD_ID": ""}), \
                patch.object(release.subprocess, "run",
                             side_effect=AssertionError("git must not run")):
            self.assertEqual("pkg-2026.08.14", release.build_commit())

    def test_cli_version_carries_the_identifier_and_help_does_not(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        import founderos_atlas.release as release
        from founderos_runtime.cli import main

        with patch.object(release, "build_commit",
                          return_value="bd50303"):
            version_out, help_out = StringIO(), StringIO()
            with redirect_stdout(version_out):
                self.assertEqual(0, main(["version"]))
            with redirect_stdout(help_out):
                self.assertEqual(0, main(["help"]))
        self.assertIn(f"{DISPLAY_VERSION} (build bd50303)",
                      version_out.getvalue())
        self.assertNotIn("bd50303", help_out.getvalue())

    def test_cli_version_stays_clean_when_nothing_is_provable(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        import founderos_atlas.release as release
        from founderos_runtime.cli import main

        with patch.object(release, "build_commit", return_value=None):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--version"]))
        self.assertIn(DISPLAY_VERSION, output.getvalue())
        self.assertNotIn("(build", output.getvalue())

    def test_both_templates_share_the_causeless_fallback(self) -> None:
        templates = (Path(__file__).resolve().parents[1]
                     / "src" / "founderos_atlas" / "web" / "templates")
        for name in ("settings.html", "system_update.html"):
            body = (templates / name).read_text(encoding="utf-8")
            self.assertIn("not available in this build", body, name)
            self.assertNotIn("not a git checkout", body, name)
            self.assertNotIn("not observable in this installed build",
                             body, name)


class BuildIdentityCacheTests(unittest.TestCase):
    """PR-180 Step 0: the build identifier is frozen at first call.

    The honesty property: the identifier the process reports must
    describe the bytes the process loaded. `register_observability`
    primes the cache during create_app — before any request — so the
    frozen value is read at load time, not at whatever later moment a
    page happens to render (by which time a `git pull` may have moved
    HEAD under a running process). Deleting either the cache or the
    startup priming silently inverts that property; these tests make
    the deletion loud.
    """

    def test_create_app_primes_the_cache_before_any_request(self) -> None:
        from founderos_atlas.release import build_commit

        build_commit.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ProfileService(
                ProfileRepository(root / "workspace"),
                InMemoryCredentialProvider(),
            )
            from founderos_atlas.web import create_app

            create_app(
                profile_service=service, workspace_root=root / "workspace",
                output_dir=root / "output",
            )
            # No request was made; startup alone resolved the identity.
            self.assertEqual(1, build_commit.cache_info().currsize)

    def test_settings_render_spawns_no_subprocess_after_priming(self) -> None:
        # Measured pre-PR-180: two uncached `git rev-parse` subprocesses
        # per /settings render (~47 ms each, 5 s timeout worst case).
        import founderos_atlas.release as release

        release.build_commit.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = ProfileService(
                ProfileRepository(root / "workspace"),
                InMemoryCredentialProvider(),
            )
            from founderos_atlas.web import create_app

            app = create_app(
                profile_service=service, workspace_root=root / "workspace",
                output_dir=root / "output",
            )
            app.config.update(TESTING=True)
            with patch.object(release.subprocess, "run") as spawned:
                response = app.test_client().get("/settings")
                self.assertEqual(200, response.status_code)
                diagnostics = app.test_client().get("/settings/diagnostics.json")
                self.assertEqual(200, diagnostics.status_code)
                spawned.assert_not_called()

    def test_the_frozen_value_is_served_to_every_later_caller(self) -> None:
        from founderos_atlas.release import build_commit

        build_commit.cache_clear()
        first = build_commit()
        info_after_first = build_commit.cache_info()
        second = build_commit()
        self.assertEqual(first, second)
        self.assertEqual(1, build_commit.cache_info().currsize)
        self.assertGreater(build_commit.cache_info().hits,
                           info_after_first.hits - 1)


class ReleaseIdentityTests(unittest.TestCase):
    def test_installed_cli_supports_standard_version_flag(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from founderos_runtime.cli import main

        output = StringIO()
        with redirect_stdout(output):
            code = main(["--version"])
        self.assertEqual(0, code)
        self.assertIn(DISPLAY_VERSION, output.getvalue())

    def test_update_backup_and_cli_use_the_release_module(self) -> None:
        from founderos_atlas.workspace.backup import build_manifest
        from founderos_atlas.workspace.update_info import update_information
        from founderos_runtime.cli.render import VERSION_TEXT

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(DISPLAY_VERSION, build_manifest(tmp)["application_version"])
            self.assertEqual(VERSION, update_information(tmp)["application_version"])
        self.assertEqual(DISPLAY_VERSION, VERSION_TEXT)

    def test_vulnerability_exception_is_explicit_and_expiring(self) -> None:
        path = Path(__file__).resolve().parents[1] / "security" / "vulnerability-exceptions.json"
        exception = json.loads(path.read_text(encoding="utf-8"))["exceptions"][0]
        self.assertEqual("PYSEC-2026-2858", exception["id"])
        self.assertTrue(exception["expires"])
        self.assertTrue(exception["compensating_controls"])

    def test_dependency_audit_reports_exception_and_rejects_new_findings(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "audit_dependencies.py"
        approved = {
            "dependencies": [{
                "name": "paramiko", "version": "4.0.0",
                "vulns": [{"id": "PYSEC-2026-2858"}],
            }]
        }
        unapproved = {
            "dependencies": [{
                "name": "example", "version": "1.0",
                "vulns": [{"id": "CVE-2099-0001"}],
            }]
        }
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "audit.json"
            report.write_text(json.dumps(approved), encoding="utf-8")
            accepted = subprocess.run(
                [sys.executable, str(script), "--input", str(report)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertIn("APPROVED UNTIL", accepted.stdout)

            report.write_text(json.dumps(unapproved), encoding="utf-8")
            rejected = subprocess.run(
                [sys.executable, str(script), "--input", str(report)],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(1, rejected.returncode)
            self.assertIn("UNAPPROVED", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
