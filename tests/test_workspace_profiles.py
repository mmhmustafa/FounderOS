"""Acceptance tests for PR-030 Atlas workspace and saved discovery profiles."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.workspace import (
    CredentialNotFoundError,
    CredentialProvider,
    CredentialStoreUnavailableError,
    DiscoveryProfile,
    DuplicateProfileError,
    InMemoryCredentialProvider,
    InvalidProfileError,
    KeyringCredentialProvider,
    ProfileNotFoundError,
    ProfileRepository,
    ProfileService,
    WorkspaceCorruptedError,
)
from founderos_runtime.cli import main


class UnavailableCredentialProvider(CredentialProvider):
    """A credential store that is deliberately unavailable.

    Lets the security tests exercise the "no secure store" path without
    depending on whether keyring is installed on the developer machine.
    """

    def available(self) -> bool:
        return False

    def save(self, credential_ref: str, password: str) -> None:
        raise CredentialStoreUnavailableError("no secure credential store")

    def get(self, credential_ref: str) -> str:
        raise CredentialStoreUnavailableError("no secure credential store")

    def delete(self, credential_ref: str) -> None:
        return None

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs


FIXED = datetime(2026, 7, 9, 10, 30, 0, tzinfo=timezone.utc)


def make_service(workdir: Path, clock=None) -> ProfileService:
    return ProfileService(
        ProfileRepository(workdir / "workspace"),
        InMemoryCredentialProvider(),
        clock=clock or (lambda: FIXED),
    )


def add_sample(service: ProfileService, **overrides) -> DiscoveryProfile:
    kwargs = {
        "name": "Hyderabad Lab",
        "site": "CML Lab",
        "management_ip": "192.168.1.12",
        "username": "atlas",
        "password": PASSWORD,
        "max_depth": 1,
        "max_devices": 10,
        "collect_configuration": True,
    }
    kwargs.update(overrides)
    return service.add_profile(**kwargs)


class ProfileModelTests(unittest.TestCase):
    def test_profile_has_no_password_field(self) -> None:
        fields = set(DiscoveryProfile.__dataclass_fields__)
        self.assertNotIn("password", fields)
        self.assertIn("credential_ref", fields)

    def test_invalid_ip_is_rejected(self) -> None:
        with self.assertRaises(InvalidProfileError):
            DiscoveryProfile(
                profile_id="x", name="X", management_ip="not-an-ip",
                username="u", credential_ref="atlas-profile:x",
            )

    def test_round_trip_serialization(self) -> None:
        profile = DiscoveryProfile(
            profile_id="hyderabad-lab", name="Hyderabad Lab",
            management_ip="192.168.1.12", username="atlas",
            credential_ref="atlas-profile:hyderabad-lab", site="CML Lab",
            max_depth=2, max_devices=25, collect_configuration=True,
            created_at="2026-07-09T10:30:00+00:00",
        )
        self.assertEqual(profile, DiscoveryProfile.from_dict(profile.to_dict()))


class ProfileServiceTests(unittest.TestCase):
    def test_create_and_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            profile = add_sample(service)
            self.assertEqual("Hyderabad Lab", profile.name)
            self.assertEqual("hyderabad-lab", profile.profile_id)
            self.assertEqual("atlas-profile:hyderabad-lab", profile.credential_ref)
            self.assertEqual("2026-07-09T10:30:00+00:00", profile.created_at)
            self.assertIsNone(profile.last_discovery)
            fetched = service.get_profile("hyderabad lab")  # case-insensitive
            self.assertEqual(profile, fetched)

    def test_list_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_sample(service, name="Bravo", management_ip="10.0.0.2")
            add_sample(service, name="Alpha", management_ip="10.0.0.1")
            names = [p.name for p in service.list_profiles()]
            self.assertEqual(["Alpha", "Bravo"], names)

    def test_duplicate_profile_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_sample(service)
            with self.assertRaises(DuplicateProfileError):
                add_sample(service, name="hyderabad lab")

    def test_invalid_ip_rejected_by_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            with self.assertRaises(InvalidProfileError):
                add_sample(service, management_ip="999.1.1.1")

    def test_update_changes_fields_and_keeps_credential_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            original = add_sample(service)
            updated = service.update_profile(
                "Hyderabad Lab", management_ip="10.10.10.10", max_devices=50
            )
            self.assertEqual("10.10.10.10", updated.management_ip)
            self.assertEqual(50, updated.max_devices)
            self.assertEqual(original.credential_ref, updated.credential_ref)
            self.assertEqual("atlas", updated.username)  # unchanged

    def test_update_password_resaves_credential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = InMemoryCredentialProvider()
            service = ProfileService(
                ProfileRepository(Path(tmp) / "ws"), provider, clock=lambda: FIXED
            )
            profile = add_sample(service)
            service.update_profile("Hyderabad Lab", password="new-pass-9")
            self.assertEqual("new-pass-9", provider.get(profile.credential_ref))

    def test_delete_removes_profile_and_credential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = InMemoryCredentialProvider()
            service = ProfileService(
                ProfileRepository(Path(tmp) / "ws"), provider, clock=lambda: FIXED
            )
            profile = add_sample(service)
            service.delete_profile("Hyderabad Lab")
            self.assertEqual((), service.list_profiles())
            with self.assertRaises(CredentialNotFoundError):
                provider.get(profile.credential_ref)

    def test_missing_profile_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            with self.assertRaises(ProfileNotFoundError):
                service.get_profile("nope")

    def test_resolve_discovery_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_sample(service)
            inputs = service.resolve_discovery_inputs("Hyderabad Lab")
            self.assertEqual("192.168.1.12", inputs.management_ip)
            self.assertEqual("atlas", inputs.username)
            self.assertEqual(PASSWORD, inputs.password)
            self.assertTrue(inputs.collect_configuration)

    def test_missing_credential_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provider = InMemoryCredentialProvider()
            service = ProfileService(
                ProfileRepository(Path(tmp) / "ws"), provider, clock=lambda: FIXED
            )
            profile = add_sample(service)
            provider.delete(profile.credential_ref)  # secret vanishes
            with self.assertRaises(CredentialNotFoundError):
                service.resolve_discovery_inputs("Hyderabad Lab")

    def test_last_discovery_timestamp_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_sample(service)
            when = datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc)
            updated = service.record_discovery("Hyderabad Lab", when)
            self.assertEqual("2026-07-09T23:41:18+00:00", updated.last_discovery)
            self.assertEqual(
                "2026-07-09T23:41:18+00:00",
                service.get_profile("Hyderabad Lab").last_discovery,
            )

    def test_corrupted_workspace_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir(parents=True)
            (ws / "profiles.json").write_text("{ not json", encoding="utf-8")
            with self.assertRaises(WorkspaceCorruptedError):
                ProfileRepository(ws).list()


class CredentialSecurityTests(unittest.TestCase):
    def test_password_never_written_to_profile_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_sample(service)
            profiles_file = Path(tmp) / "workspace" / "profiles.json"
            content = profiles_file.read_text(encoding="utf-8")
            self.assertNotIn(PASSWORD, content)
            data = json.loads(content)
            self.assertNotIn("password", json.dumps(data))
            self.assertIn("atlas-profile:hyderabad-lab", content)

    def test_keyring_provider_reports_availability_as_bool(self) -> None:
        # Environment-independent: the real provider must answer available()
        # with a boolean (whether or not keyring is installed on this machine).
        provider = KeyringCredentialProvider()
        self.assertIsInstance(provider.available(), bool)

    def test_unavailable_provider_raises_on_save(self) -> None:
        provider = UnavailableCredentialProvider()
        self.assertFalse(provider.available())
        with self.assertRaises(CredentialStoreUnavailableError):
            provider.save("atlas-profile:x", "secret")

    def test_service_refuses_to_save_without_secure_store(self) -> None:
        # Security requirement: no profile is persisted when the credential
        # store is unavailable. Uses a fake so it holds regardless of keyring.
        with tempfile.TemporaryDirectory() as tmp:
            service = ProfileService(
                ProfileRepository(Path(tmp) / "ws"),
                UnavailableCredentialProvider(),
                clock=lambda: FIXED,
            )
            with self.assertRaises(CredentialStoreUnavailableError):
                add_sample(service)
            self.assertFalse((Path(tmp) / "ws" / "profiles.json").exists())


class ProfileCliTests(unittest.TestCase):
    def invoke(self, *arguments, service, answers=(), password=PASSWORD):
        replies = iter(answers)
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                list(arguments),
                atlas_input_reader=lambda prompt: next(replies, ""),
                atlas_password_reader=lambda prompt: password,
                atlas_profile_service=service,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_profile_add_list_show_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            code, out, err = self.invoke(
                "atlas", "profile", "add", service=service,
                answers=("Hyderabad Lab", "CML Lab", "192.168.1.12", "atlas", "1", "10", "y"),
            )
            self.assertEqual(0, code, err)
            self.assertIn("Profile saved successfully.", out)
            self.assertNotIn(PASSWORD, out)

            code, out, _ = self.invoke("atlas", "profile", "list", service=service)
            self.assertEqual(0, code)
            self.assertIn("NAME", out)
            self.assertIn("Hyderabad Lab", out)
            self.assertIn("192.168.1.12", out)
            self.assertNotIn(PASSWORD, out)

            code, out, _ = self.invoke(
                "atlas", "profile", "show", "Hyderabad Lab", service=service
            )
            self.assertEqual(0, code)
            self.assertIn("stored securely", out)
            self.assertNotIn(PASSWORD, out)

    def test_profile_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_sample(service)
            code, out, _ = self.invoke(
                "atlas", "profile", "delete", "Hyderabad Lab", service=service
            )
            self.assertEqual(0, code)
            self.assertIn("deleted", out)
            self.assertEqual((), service.list_profiles())

    def test_show_missing_profile_is_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            code, out, err = self.invoke(
                "atlas", "profile", "show", "Ghost", service=service
            )
            self.assertEqual(1, code)
            self.assertEqual("", out)
            self.assertIn("No saved profile named 'Ghost'", err)

    def test_duplicate_add_is_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_sample(service)
            code, _, err = self.invoke(
                "atlas", "profile", "add", service=service,
                answers=("Hyderabad Lab", "", "10.0.0.9", "atlas", "", "", "n"),
            )
            self.assertEqual(1, code)
            self.assertIn("already exists", err)

    def test_profile_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            code, _, err = self.invoke("atlas", "profile", service=service)
            self.assertEqual(2, code)
            self.assertIn("Usage: founderos atlas profile", err)

    def test_help_lists_profile(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("atlas profile", stdout.getvalue())
        self.assertIn("--profile", stdout.getvalue())


class DiscoverWithProfileTests(unittest.TestCase):
    def two_device_network(self) -> ScriptedNetwork:
        return ScriptedNetwork({
            "10.0.0.1": device_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),)),
            "10.0.0.2": device_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
        })

    def run_profile_discover(self, workdir: Path, service: ProfileService, network):
        ticks = iter([
            datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc),
            datetime(2026, 7, 9, 23, 41, 54, tzinfo=timezone.utc),
        ])

        def no_prompt(prompt):
            raise AssertionError(f"unexpected prompt: {prompt!r}")

        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                ["atlas", "discover", "--profile", "Hyderabad Lab"],
                atlas_transport_factory=lambda c: network.transport_factory(c.host),
                atlas_input_reader=no_prompt,
                atlas_password_reader=no_prompt,
                atlas_topology_output=workdir / "atlas_topology.html",
                atlas_snapshot_output=workdir / "topology_snapshot.json",
                atlas_morning_brief_output=workdir / "morning_brief.md",
                atlas_config_output_dir=workdir / "configs",
                atlas_dashboard_output=workdir / "dashboard.html",
                atlas_history_root=workdir / ".atlas" / "history",
                atlas_compare_json_output=workdir / "change_report.json",
                atlas_compare_markdown_output=workdir / "change_report.md",
                atlas_config_diff_json_output=workdir / "config_change_report.json",
                atlas_config_diff_markdown_output=workdir / "config_change_report.md",
                atlas_state_diff_json_output=workdir / "state_change_report.json",
                atlas_state_diff_markdown_output=workdir / "state_change_report.md",
                atlas_clock=lambda: next(ticks),
                atlas_browser_opener=lambda uri: None,
                atlas_profile_service=service,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_discover_using_saved_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_sample(service, management_ip="10.0.0.1", collect_configuration=False)
            code, out, err = self.run_profile_discover(
                workdir, service, self.two_device_network()
            )
            self.assertEqual(0, code, err)
            self.assertIn("Using profile: Hyderabad Lab", out)
            self.assertIn("Discovery Complete", out)
            # Profile discoveries write into the profile's isolated scope
            # (PR-031A) — never the shared unscoped workspace.
            scope = workdir / ".atlas" / "profiles" / "hyderabad-lab"
            self.assertTrue((scope / "topology_snapshot.json").exists())
            self.assertTrue((scope / "dashboard.html").exists())
            self.assertFalse((workdir / "topology_snapshot.json").exists())
            # last discovery recorded on the profile
            self.assertEqual(
                "2026-07-09T23:41:54+00:00",
                service.get_profile("Hyderabad Lab").last_discovery,
            )

    def test_password_never_leaks_into_any_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_sample(service, management_ip="10.0.0.1", collect_configuration=True)
            code, out, err = self.run_profile_discover(
                workdir, service, self.two_device_network()
            )
            self.assertEqual(0, code, err)
            self.assertNotIn(PASSWORD, out)
            self.assertNotIn(PASSWORD, err)
            leaked = []
            for path in workdir.rglob("*"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    if PASSWORD in text:
                        leaked.append(str(path.relative_to(workdir)))
            self.assertEqual([], leaked)

    def test_missing_profile_discover_is_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            code, out, err = self.run_profile_discover(
                workdir, service, self.two_device_network()
            )
            self.assertEqual(1, code)
            self.assertIn("No saved profile named 'Hyderabad Lab'", err)


if __name__ == "__main__":
    unittest.main()
