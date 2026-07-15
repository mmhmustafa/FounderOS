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
            # PR-040: the landing page is the MISSION workspace.
            self.assertIn(b"Mission", body)
            self.assertIn(b"What would you like to do?", body)
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
                # This test binds nothing, so it must not care whether this
                # machine happens to have a server on 8765 (PR-047A).
                atlas_web_port_probe=lambda host, port: False,
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


class OneServerPerPortTests(unittest.TestCase):
    """Atlas must refuse to become the second server on a port.

    On Linux, binding a listening port fails with EADDRINUSE. On Windows,
    SO_REUSEADDR — which the dev server sets by default to dodge TIME_WAIT on
    Unix — means "steal the port" instead, so a second `atlas web` does not
    fail. It quietly becomes a second server, and the GUI answers from
    whichever process wins: possibly one started hours ago, running older code.

    That is not a mistake an operator can avoid by being careful. Nothing
    warns them, both servers look fine, and the symptom is a GUI that ignores
    the change they just made. Refusing to start is the only honest option.
    """

    def _start(self, *, port=8765, probe=None, runner=None):
        from founderos_runtime.cli.commands import atlas_web_command

        return atlas_web_command(
            host="127.0.0.1",
            port=port,
            port_probe=probe,
            server_runner=runner or (lambda **kwargs: None),
            browser_opener=lambda url: None,
        )

    def test_refuses_to_start_when_the_port_is_already_serving(self) -> None:
        from founderos_runtime.cli.commands import CliError

        with self.assertRaises(CliError) as caught:
            self._start(probe=lambda host, port: True)
        message = str(caught.exception)
        self.assertIn("already serving", message)
        # The refusal must say what to do about it, and offer a real way out.
        self.assertIn("--port", message)

    def test_starts_normally_when_the_port_is_free(self) -> None:
        started: dict = {}
        code, _ = self._start(
            port=8799,
            probe=lambda host, port: False,
            runner=lambda **kwargs: started.update(kwargs),
        )
        self.assertEqual(0, code)
        self.assertEqual({"host": "127.0.0.1", "port": 8799}, started)

    def test_the_escape_hatch_the_message_offers_actually_exists(self) -> None:
        """The refusal recommends `atlas web --port N`; that must dispatch."""

        from founderos_runtime.cli.main import _parse_port_flag

        self.assertEqual((8766, []), _parse_port_flag(["--port", "8766"]))
        self.assertEqual((8766, []), _parse_port_flag(["--port=8766"]))
        self.assertEqual((None, []), _parse_port_flag([]))

    def test_a_bad_port_is_refused_rather_than_guessed(self) -> None:
        from founderos_runtime.cli.commands import CliError
        from founderos_runtime.cli.main import _parse_port_flag

        for tokens in (["--port", "abc"], ["--port", "0"], ["--port", "99999"]):
            with self.assertRaises(CliError):
                _parse_port_flag(tokens)

    def test_the_probe_reports_a_free_port_as_free(self) -> None:
        from founderos_runtime.cli.commands import port_is_serving

        # Nothing is bound here; the probe must not claim otherwise.
        self.assertFalse(port_is_serving("127.0.0.1", 8798, timeout=0.2))


class SeedRangeIsVisibleWhereTheSeedIsShownTests(unittest.TestCase):
    """A profile created from a CIDR must not present itself as a single IP.

    The wizard expands "172.20.20.0/24" into candidate addresses and seeds from
    the first one, so every screen that showed a profile's seed showed
    "172.20.20.1" — an address the operator never typed and cannot recognise.
    These pin the operator's own path (the rendered pages), not just the model:
    the range was recorded correctly well before any of these screens showed it.
    """

    def add_cidr_profile(self, service):
        return add_profile(
            service, name="labdab", site="Lab", management_ip="172.20.20.1",
            seeds=["172.20.20.2", "172.20.20.3"], seed_cidr="172.20.20.0/24",
        )

    def test_discover_page_shows_the_range_in_the_table_and_the_dropdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            self.add_cidr_profile(service)
            _, client = build_client(Path(tmp), service)
            page = client.get("/discovery").data
            # Both the Networks table and the profile <option> label.
            self.assertEqual(2, page.count(b"172.20.20.0/24"))
            self.assertNotIn(b"172.20.20.1", page)
            # The column header no longer promises an IP it cannot deliver.
            self.assertIn(b"<th>Seed</th>", page)

    def test_profiles_page_shows_the_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            self.add_cidr_profile(service)
            _, client = build_client(Path(tmp), service)
            page = client.get("/profiles").data
            self.assertIn(b"172.20.20.0/24", page)

    def test_edit_form_explains_where_its_seed_address_came_from(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            self.add_cidr_profile(service)
            _, client = build_client(Path(tmp), service)
            form = client.get("/profiles/labdab/edit").data
            # The field must keep the real address — it is what Atlas connects
            # to — but say why it is not what was typed.
            self.assertIn(b'value="172.20.20.1"', form)
            self.assertIn(b"172.20.20.0/24", form)

    def test_a_seed_profile_still_shows_its_address_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service)  # no seed_cidr
            _, client = build_client(Path(tmp), service)
            self.assertIn(b"10.0.0.1", client.get("/discovery").data)
            self.assertIn(b"10.0.0.1", client.get("/profiles").data)

    def test_saving_an_edit_does_not_erase_the_range(self) -> None:
        # The edit form has no seed_cidr input, so an ordinary save posts
        # without it. That must not be read as "clear it".
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            self.add_cidr_profile(service)
            _, client = build_client(Path(tmp), service)
            response = client.post("/profiles/labdab", data={
                "name": "labdab", "site": "Lab", "management_ip": "172.20.20.1",
                "username": "atlas", "password": "", "max_depth": "1",
                "max_devices": "10",
            })
            self.assertIn(response.status_code, (200, 302))
            self.assertEqual("172.20.20.0/24", service.get_profile("labdab").seed_cidr)
            self.assertIn(b"172.20.20.0/24", client.get("/profiles").data)
