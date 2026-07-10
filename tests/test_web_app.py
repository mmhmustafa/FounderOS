"""Acceptance tests for PR-031 Atlas web GUI shell (Flask test client)."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.web import DEFAULT_HOST, create_app
from founderos_atlas.workspace import (
    InMemoryCredentialProvider,
    ProfileRepository,
    ProfileService,
)
from founderos_runtime.cli import main

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


FIXED = datetime(2026, 7, 10, 10, 30, 0, tzinfo=timezone.utc)


def make_service(workdir: Path) -> ProfileService:
    return ProfileService(
        ProfileRepository(workdir / "workspace"),
        InMemoryCredentialProvider(),
        clock=lambda: FIXED,
    )


def add_profile(service: ProfileService, **overrides):
    kwargs = {
        "name": "Hyderabad Lab",
        "site": "CML Lab",
        "management_ip": "10.0.0.1",
        "username": "atlas",
        "password": PASSWORD,
        "max_depth": 1,
        "max_devices": 10,
        "collect_configuration": False,
    }
    kwargs.update(overrides)
    return service.add_profile(**kwargs)


def build_client(workdir: Path, service, *, transport_factory=None, clock=None):
    app = create_app(
        profile_service=service,
        output_dir=workdir / "out",
        history_root=workdir / "out" / ".atlas" / "history",
        transport_factory=transport_factory,
        clock=clock,
    )
    app.config.update(TESTING=True)
    return app, app.test_client()


class WebShellTests(unittest.TestCase):
    def test_app_starts_and_binds_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app, _ = build_client(Path(tmp), make_service(Path(tmp)))
            self.assertEqual("127.0.0.1", app.config["ATLAS_HOST"])
            self.assertEqual("127.0.0.1", DEFAULT_HOST)

    def test_dashboard_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_client(Path(tmp), make_service(Path(tmp)))
            response = client.get("/")
            self.assertEqual(200, response.status_code)
            body = response.data
            self.assertIn(b"Atlas", body)
            self.assertIn(b"Enterprise Network Intelligence", body)
            self.assertIn(b"Dashboard", body)
            self.assertIn(b"Run Discovery", body)

    def test_profiles_route_lists_without_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service)
            _, client = build_client(Path(tmp), service)
            response = client.get("/profiles")
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Hyderabad Lab", response.data)
            self.assertIn(b"10.0.0.1", response.data)
            self.assertNotIn(PASSWORD.encode(), response.data)

    def test_add_profile_form_has_masked_password_and_no_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service)
            _, client = build_client(Path(tmp), service)
            new_form = client.get("/profiles/new").data
            self.assertIn(b'type="password"', new_form)
            # Editing must not pre-fill the password field with any value.
            edit_form = client.get("/profiles/Hyderabad%20Lab/edit").data
            self.assertIn(b'type="password"', edit_form)
            self.assertNotIn(PASSWORD.encode(), edit_form)

    def test_create_profile_via_form_stores_password_securely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            _, client = build_client(workdir, service)
            response = client.post(
                "/profiles",
                data={
                    "name": "Lab One",
                    "site": "CML",
                    "management_ip": "10.0.0.5",
                    "username": "atlas",
                    "password": PASSWORD,
                    "max_depth": "1",
                    "max_devices": "10",
                    "collect_configuration": "on",
                },
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertNotIn(PASSWORD.encode(), response.data)
            profiles_file = workdir / "workspace" / "profiles.json"
            self.assertNotIn(PASSWORD, profiles_file.read_text(encoding="utf-8"))
            self.assertEqual(1, len(service.list_profiles()))

    def test_settings_shows_credential_provider_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_client(Path(tmp), make_service(Path(tmp)))
            response = client.get("/settings")
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Credential provider", response.data)
            self.assertIn(b"127.0.0.1", response.data)
            self.assertIn(b"local", response.data.lower() if False else response.data)

    def test_missing_workspace_is_handled_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # A fresh workspace with no profiles and no artifacts.
            _, client = build_client(Path(tmp), make_service(Path(tmp)))
            for path in ("/", "/profiles", "/history", "/changes", "/topology", "/incidents"):
                self.assertEqual(200, client.get(path).status_code, path)

    def test_discovery_page_lists_saved_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service)
            _, client = build_client(Path(tmp), service)
            response = client.get("/discovery")
            self.assertIn(b"Hyderabad Lab", response.data)
            # No credential/IP entry fields on the discovery page itself.
            self.assertNotIn(b'name="password"', response.data)
            self.assertNotIn(b'name="management_ip"', response.data)


class WebDiscoveryTests(unittest.TestCase):
    def two_device_network(self) -> ScriptedNetwork:
        return ScriptedNetwork({
            "10.0.0.1": device_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
            "10.0.0.2": device_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
        })

    def test_discovery_runs_from_saved_profile_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, management_ip="10.0.0.1")
            network = self.two_device_network()
            ticks = iter([
                datetime(2026, 7, 10, 23, 41, 18, tzinfo=timezone.utc),
                datetime(2026, 7, 10, 23, 41, 54, tzinfo=timezone.utc),
            ])
            _, client = build_client(
                workdir,
                service,
                transport_factory=lambda c: network.transport_factory(c.host),
                clock=lambda: next(ticks),
            )
            response = client.post(
                "/discovery/run",
                data={"profile": "Hyderabad Lab"},  # no IP/username/password
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"finished successfully", response.data)
            self.assertNotIn(PASSWORD.encode(), response.data)
            # Real pipeline artifacts were produced in-process (no subprocess),
            # inside the profile's isolated scope (PR-031A).
            scope = workdir / "out" / ".atlas" / "profiles" / "hyderabad-lab"
            self.assertTrue((scope / "topology_snapshot.json").is_file())
            self.assertTrue((scope / "dashboard.html").is_file())
            # The profile's last-discovery timestamp was updated.
            self.assertEqual(
                "2026-07-10T23:41:54+00:00",
                service.get_profile("Hyderabad Lab").last_discovery,
            )

    def test_discovery_run_requires_a_profile_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service)
            _, client = build_client(Path(tmp), service)
            response = client.post("/discovery/run", data={"profile": ""}, follow_redirects=True)
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Select a saved profile", response.data)

    def test_no_cli_subprocess_is_used_for_discovery(self) -> None:
        # The discovery route imports the pipeline function directly; assert the
        # web package never spawns a subprocess.
        import founderos_atlas.web.routes as routes
        import founderos_atlas.web.app as app_module

        for module in (routes, app_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            # Guard against actual process spawning (not the word in prose).
            for pattern in ("import subprocess", "subprocess.", "os.system(", "Popen("):
                self.assertNotIn(pattern, source)


class WebCliCommandTests(unittest.TestCase):
    def test_atlas_web_prints_url_and_binds_loopback(self) -> None:
        captured = {}

        def runner(**kwargs):
            captured.update(kwargs)

        opened: list[str] = []
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(
                ["atlas", "web"],
                atlas_browser_opener=opened.append,
                atlas_web_server_runner=runner,
            )
        self.assertEqual(0, code)
        self.assertIn("http://127.0.0.1:8765", stdout.getvalue())
        self.assertEqual(["http://127.0.0.1:8765"], opened)
        self.assertEqual("127.0.0.1", captured.get("host"))
        self.assertNotEqual("0.0.0.0", captured.get("host"))

    def test_help_lists_web(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("atlas web", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
