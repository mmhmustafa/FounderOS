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
                    if mode == "proxy":
                        self.assertIn("not observable", info["bind_observation"])
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
