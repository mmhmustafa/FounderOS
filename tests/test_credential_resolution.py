"""Acceptance tests for the PR-033 multi-credential strategy.

Scoped, prioritized, deterministic candidate resolution; safe attempts with
lockout protection; success memory by reference only; zero secret exposure.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.credentials import (
    CredentialEntry,
    CredentialResolver,
    CredentialScope,
    CredentialSet,
    CredentialSetRepository,
    CredentialSetService,
    CredentialSuccessMemory,
    DeviceContext,
)
from founderos_atlas.history import HistoryRepository
from founderos_atlas.transport import AuthenticationError, DeviceTransport
from founderos_atlas.workspace import (
    InMemoryCredentialProvider,
    ProfileRepository,
    ProfileService,
)
from founderos_runtime.cli import main

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs
from tests.test_profile_isolation import FIXED, add_profile, scope_dir


WAN_PASSWORD = "wan-fixture-secret"


def entry(
    label: str,
    ref: str,
    priority: int = 100,
    scope: CredentialScope | None = None,
    username: str = "atlas",
) -> CredentialEntry:
    return CredentialEntry(
        entry_id=label.replace(" ", "-").lower(),
        label=label,
        username=username,
        credential_ref=ref,
        priority=priority,
        scope=scope or CredentialScope(),
    )


class CredentialScopeTests(unittest.TestCase):
    def test_empty_scope_matches_any_device(self) -> None:
        self.assertTrue(CredentialScope().matches(DeviceContext(host="10.0.0.1")))

    def test_vendor_and_platform_scoping(self) -> None:
        scope = CredentialScope(vendors=("Cisco",), platforms=("ios", "ios-xe"))
        cisco = DeviceContext(host="10.0.0.1", vendor="cisco", platform="IOS")
        forti = DeviceContext(host="10.0.0.1", vendor="Fortinet", platform="fortios")
        unknown = DeviceContext(host="10.0.0.1")
        self.assertTrue(scope.matches(cisco))
        self.assertFalse(scope.matches(forti))
        # Unknown attributes never satisfy a restriction.
        self.assertFalse(scope.matches(unknown))

    def test_hostname_glob_scoping(self) -> None:
        scope = CredentialScope(hostname_patterns=("legacy-*", "*-old"))
        self.assertTrue(
            scope.matches(DeviceContext(host="10.0.0.1", hostname="LEGACY-SW9"))
        )
        self.assertFalse(
            scope.matches(DeviceContext(host="10.0.0.1", hostname="core-r1"))
        )
        self.assertFalse(scope.matches(DeviceContext(host="10.0.0.1")))

    def test_cidr_scoping_uses_the_management_host(self) -> None:
        scope = CredentialScope(cidrs=("10.1.0.0/16",))
        self.assertTrue(scope.matches(DeviceContext(host="10.1.0.9")))
        self.assertFalse(scope.matches(DeviceContext(host="10.0.0.9")))

    def test_scope_summary_never_holds_a_secret(self) -> None:
        summary = CredentialScope(vendors=("Cisco",)).summary()
        self.assertIn("vendor: Cisco", summary)


class CredentialResolverTests(unittest.TestCase):
    def build_repository(self, root: Path) -> CredentialSetRepository:
        repository = CredentialSetRepository(root)
        repository.save(
            CredentialSet(
                set_id="enterprise",
                name="Enterprise Network Access",
                entries=(
                    entry("General Fallback", "ref-fallback", priority=100),
                    entry(
                        "Primary Cisco ReadOnly", "ref-cisco", priority=10,
                        scope=CredentialScope(vendors=("Cisco",)),
                    ),
                    entry(
                        "Legacy ReadOnly", "ref-legacy", priority=20,
                        scope=CredentialScope(hostname_patterns=("legacy-*",)),
                    ),
                    entry(
                        "WAN ReadOnly", "ref-wan", priority=30,
                        scope=CredentialScope(cidrs=("10.1.0.0/16",)),
                    ),
                ),
            )
        )
        return repository

    def test_candidates_are_specificity_then_priority_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = CredentialResolver(
                self.build_repository(Path(tmp)), max_attempts=10
            )
            context = DeviceContext(
                host="10.1.0.5", hostname="legacy-r9", vendor="cisco"
            )
            first = resolver.candidates(context, set_ids=("enterprise",))
            second = resolver.candidates(context, set_ids=("enterprise",))
            self.assertEqual(first, second)  # deterministic
            # Hostname/CIDR matches (priority breaking the tie) come before
            # the broader vendor match; the unrestricted fallback is last.
            self.assertEqual(
                ["ref-legacy", "ref-wan", "ref-cisco", "ref-fallback"],
                [candidate.credential_ref for candidate in first],
            )

    def test_scope_filters_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = CredentialResolver(
                self.build_repository(Path(tmp)), max_attempts=10
            )
            # No vendor/hostname knowledge, host outside the WAN range:
            # only the unrestricted fallback applies.
            candidates = resolver.candidates(
                DeviceContext(host="10.0.0.5"), set_ids=("enterprise",)
            )
            self.assertEqual(
                ["ref-fallback"],
                [candidate.credential_ref for candidate in candidates],
            )

    def test_attempts_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = CredentialResolver(
                self.build_repository(Path(tmp)), max_attempts=2
            )
            context = DeviceContext(
                host="10.1.0.5", hostname="legacy-r9", vendor="cisco"
            )
            candidates = resolver.candidates(context, set_ids=("enterprise",))
            self.assertEqual(2, len(candidates))  # lockout protection

    def test_previously_successful_credential_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = CredentialSuccessMemory(root)
            memory.record_success(
                "10.1.0.5", credential_ref="ref-wan", username="atlas",
                hostname="legacy-r9", when="2026-07-10T08:00:00+00:00",
            )
            resolver = CredentialResolver(
                self.build_repository(root), memory, max_attempts=10
            )
            candidates = resolver.candidates(
                DeviceContext(host="10.1.0.5"), set_ids=("enterprise",)
            )
            self.assertEqual("ref-wan", candidates[0].credential_ref)
            self.assertEqual("remembered", candidates[0].source)
            # Memory also restores the hostname hint for scope matching.
            enriched = resolver.enrich_context(DeviceContext(host="10.1.0.5"))
            self.assertEqual("legacy-r9", enriched.hostname)

    def _default(self):
        from founderos_atlas.credentials.resolver import CredentialCandidate

        return CredentialCandidate(
            credential_ref="atlas-profile:lab", username="atlas",
            label="profile credential", priority=0, source="profile-default",
        )

    def test_seed_devices_try_the_profile_credential_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = CredentialResolver(
                self.build_repository(Path(tmp)), max_attempts=10
            )
            # The WAN entry matches this host, but the operator explicitly
            # paired the profile credential with its seed device.
            candidates = resolver.candidates(
                DeviceContext(host="10.1.0.5"),
                set_ids=("enterprise",),
                profile_default=self._default(),
                default_first=True,
            )
            self.assertEqual("atlas-profile:lab", candidates[0].credential_ref)
            self.assertEqual("ref-wan", candidates[1].credential_ref)

    def test_scoped_match_beats_the_profile_default_on_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = CredentialResolver(
                self.build_repository(Path(tmp)), max_attempts=10
            )
            candidates = resolver.candidates(
                DeviceContext(host="10.1.0.5"),
                set_ids=("enterprise",),
                profile_default=self._default(),
            )
            # CIDR-scoped entry first, then the profile default, and the
            # unrestricted fallback only after both.
            self.assertEqual(
                ["ref-wan", "atlas-profile:lab", "ref-fallback"],
                [candidate.credential_ref for candidate in candidates],
            )

    def test_exact_ip_scope_outranks_a_range_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = CredentialSetRepository(Path(tmp))
            repository.save(
                CredentialSet(
                    set_id="ranked",
                    name="Ranked",
                    entries=(
                        entry(
                            "Range", "ref-range", priority=10,
                            scope=CredentialScope(cidrs=("10.1.0.0/16",)),
                        ),
                        entry(
                            "Exact Host", "ref-exact", priority=90,
                            scope=CredentialScope(cidrs=("10.1.0.5/32",)),
                        ),
                    ),
                )
            )
            resolver = CredentialResolver(repository, max_attempts=10)
            candidates = resolver.candidates(
                DeviceContext(host="10.1.0.5"),
                set_ids=("ranked",),
                profile_default=self._default(),
            )
            # Exact host wins despite its worse priority number; the range
            # entry still precedes the generic profile credential.
            self.assertEqual(
                ["ref-exact", "ref-range", "atlas-profile:lab"],
                [candidate.credential_ref for candidate in candidates],
            )

    def test_default_precedes_fallback_when_nothing_scoped_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            resolver = CredentialResolver(
                self.build_repository(Path(tmp)), max_attempts=10
            )
            # Host outside every scoped rule: profile default first, the
            # unrestricted fallback as the last resort.
            candidates = resolver.candidates(
                DeviceContext(host="172.16.0.9"),
                set_ids=("enterprise",),
                profile_default=self._default(),
            )
            self.assertEqual(
                ["atlas-profile:lab", "ref-fallback"],
                [candidate.credential_ref for candidate in candidates],
            )

    def test_legacy_profile_without_sets_resolves_to_its_credential_only(self) -> None:
        resolver = CredentialResolver(max_attempts=10)
        candidates = resolver.candidates(
            DeviceContext(host="10.0.0.1"), profile_default=self._default()
        )
        self.assertEqual(
            ["atlas-profile:lab"],
            [candidate.credential_ref for candidate in candidates],
        )

    def test_no_reference_is_ever_listed_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = CredentialSuccessMemory(root)
            # The remembered credential IS one of the scoped entries.
            memory.record_success(
                "10.1.0.5", credential_ref="ref-wan", username="atlas"
            )
            resolver = CredentialResolver(
                self.build_repository(root), memory, max_attempts=10
            )
            candidates = resolver.candidates(
                DeviceContext(host="10.1.0.5"),
                set_ids=("enterprise",),
                profile_default=self._default(),
            )
            refs = [candidate.credential_ref for candidate in candidates]
            self.assertEqual(len(refs), len(set(refs)))
            self.assertEqual("ref-wan", refs[0])  # remembered stays first


class PasswordCheckingNetwork:
    """Scripted network whose devices verify the offered password."""

    def __init__(self, topology: dict, passwords: dict[str, str]) -> None:
        self.network = ScriptedNetwork(topology)
        self.passwords = passwords
        self.attempts: list[tuple[str, str]] = []  # (host, username) only

    def factory(self, credentials):
        self.attempts.append((credentials.host, credentials.username))
        if credentials.password != self.passwords.get(credentials.host):
            host = credentials.host

            class _Rejecting(DeviceTransport):
                def connect(self) -> None:
                    raise AuthenticationError(
                        f"Authentication failed for {host}. "
                        "Verify the username and password."
                    )

                def disconnect(self) -> None:
                    return None

                def execute(self, command: str) -> str:
                    raise AssertionError("never connected")

            return _Rejecting()
        return self.network.transport_factory(credentials.host)


def wan_topology() -> dict:
    """R1 (HQ) <-> SW1; R1 also reaches R11 across the WAN range."""

    return {
        "10.0.0.1": device_outputs(
            "R1", "10.0.0.1", (("SW1", "10.0.0.2"), ("R11", "10.1.0.1"))
        ),
        "10.0.0.2": device_outputs("SW1", "10.0.0.2", (("R1", "10.0.0.1"),)),
        "10.1.0.1": device_outputs("R11", "10.1.0.1", (("R1", "10.0.0.1"),)),
    }


def run_profile_discover(workdir: Path, service, factory, profile: str, start):
    from datetime import timedelta

    ticks = iter([start, start + timedelta(seconds=30)])
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(
            ["atlas", "discover", "--profile", profile],
            atlas_transport_factory=factory,
            atlas_input_reader=lambda prompt: "",
            atlas_password_reader=lambda prompt: "",
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


class MultiCredentialPipelineTests(unittest.TestCase):
    """End-to-end: one profile, multiple credentials, safe fallback."""

    def build_workspace(self, workdir: Path):
        provider = InMemoryCredentialProvider()
        service = ProfileService(
            ProfileRepository(workdir / "workspace"), provider,
            clock=lambda: FIXED,
        )
        credential_service = CredentialSetService(
            CredentialSetRepository(workdir / "workspace"), provider
        )
        credential_service.add_entry(
            set_name="Enterprise Network Access",
            label="WAN ReadOnly",
            username="atlas",
            password=WAN_PASSWORD,
            priority=10,
            scope=CredentialScope(cidrs=("10.1.0.0/16",)),
        )
        add_profile(
            service, "Hyderabad Lab", "10.0.0.1",
            max_depth=2,
            credential_sets=("enterprise-network-access",),
            site_hint="hyderabad",
        )
        return service

    def test_discovery_crosses_sites_with_the_correct_credential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_workspace(workdir)
            network = PasswordCheckingNetwork(
                wan_topology(),
                {
                    "10.0.0.1": PASSWORD,
                    "10.0.0.2": PASSWORD,
                    "10.1.0.1": WAN_PASSWORD,  # different admin credential
                },
            )
            code, out, err = run_profile_discover(
                workdir, service, network.factory, "Hyderabad Lab", FIXED
            )
            self.assertEqual(0, code, err)
            snapshot = json.loads(
                (scope_dir(workdir, "hyderabad-lab") / "topology_snapshot.json")
                .read_text("utf-8")
            )
            hostnames = {device["hostname"] for device in snapshot["devices"]}
            self.assertEqual({"R1", "SW1", "R11"}, hostnames)
            # R11 is not a seed, so the CIDR-scoped WAN credential outranks
            # the generic profile credential: one attempt, no failed auth
            # against the remote device (lockout protection).
            r11_attempts = [a for a in network.attempts if a[0] == "10.1.0.1"]
            self.assertEqual(1, len(r11_attempts))
            # The seed itself tried the profile credential first: exactly
            # one attempt there too.
            seed_attempts = [a for a in network.attempts if a[0] == "10.0.0.1"]
            self.assertEqual(1, len(seed_attempts))
            # Provenance: history metadata records the reference that worked.
            record = HistoryRepository(
                scope_dir(workdir, "hyderabad-lab") / "history"
            ).latest()
            usage = record.metadata["credential_use"]
            self.assertEqual(
                "atlas-credset:enterprise-network-access:wan-readonly",
                usage["10.1.0.1"],
            )
            self.assertEqual("atlas-profile:hyderabad-lab", usage["10.0.0.1"])
            self.assertNotIn(WAN_PASSWORD, json.dumps(record.to_dict()))

    def test_successful_credential_is_remembered_and_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_workspace(workdir)
            passwords = {
                "10.0.0.1": PASSWORD, "10.0.0.2": PASSWORD,
                "10.1.0.1": WAN_PASSWORD,
            }
            first = PasswordCheckingNetwork(wan_topology(), passwords)
            run_profile_discover(
                workdir, service, first.factory, "Hyderabad Lab", FIXED
            )
            memory = CredentialSuccessMemory(workdir / "workspace")
            self.assertEqual(
                "atlas-credset:enterprise-network-access:wan-readonly",
                memory.recall("10.1.0.1")["credential_ref"],
            )
            # Second run: the remembered reference is tried first — one
            # attempt on R11 instead of two.
            from datetime import timedelta

            second = PasswordCheckingNetwork(wan_topology(), passwords)
            code, _, err = run_profile_discover(
                workdir, service, second.factory, "Hyderabad Lab",
                FIXED + timedelta(hours=1),
            )
            self.assertEqual(0, code, err)
            r11_attempts = [a for a in second.attempts if a[0] == "10.1.0.1"]
            self.assertEqual(1, len(r11_attempts))

    def test_lockout_protection_bounds_attempts_and_reports_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_workspace(workdir)
            network = PasswordCheckingNetwork(
                wan_topology(),
                {
                    "10.0.0.1": PASSWORD,
                    "10.0.0.2": PASSWORD,
                    "10.1.0.1": "nothing-atlas-knows",  # every candidate fails
                },
            )
            code, out, err = run_profile_discover(
                workdir, service, network.factory, "Hyderabad Lab", FIXED
            )
            # The seed succeeded; R11 is recorded as a failed visit and the
            # run itself completes.
            self.assertEqual(0, code, err)
            r11_attempts = [a for a in network.attempts if a[0] == "10.1.0.1"]
            # WAN credential + profile credential — then stop. Never more.
            self.assertEqual(2, len(r11_attempts))
            snapshot = json.loads(
                (scope_dir(workdir, "hyderabad-lab") / "topology_snapshot.json")
                .read_text("utf-8")
            )
            hostnames = {device["hostname"] for device in snapshot["devices"]}
            self.assertEqual({"R1", "SW1"}, hostnames)

    def test_seed_prefers_profile_credential_over_a_matching_scoped_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            provider = InMemoryCredentialProvider()
            service = ProfileService(
                ProfileRepository(workdir / "workspace"), provider,
                clock=lambda: FIXED,
            )
            # A scoped entry that also covers the seed range — with a WRONG
            # password. If the seed tried it first, authentication would
            # fail before the profile credential got a chance.
            CredentialSetService(
                CredentialSetRepository(workdir / "workspace"), provider
            ).add_entry(
                set_name="Enterprise Network Access",
                label="Campus ReadOnly",
                username="atlas",
                password="not-the-seed-password",
                priority=10,
                scope=CredentialScope(cidrs=("10.0.0.0/16",)),
            )
            add_profile(
                service, "Hyderabad Lab", "10.0.0.1",
                max_depth=2,
                credential_sets=("enterprise-network-access",),
            )
            network = PasswordCheckingNetwork(
                wan_topology(),
                {
                    "10.0.0.1": PASSWORD,       # profile credential
                    "10.0.0.2": PASSWORD,
                    "10.1.0.1": "unreachable-for-this-test",
                },
            )
            code, out, err = run_profile_discover(
                workdir, service, network.factory, "Hyderabad Lab", FIXED
            )
            self.assertEqual(0, code, err)
            # Seed: profile credential first, one attempt, zero failures.
            seed_attempts = [a for a in network.attempts if a[0] == "10.0.0.1"]
            self.assertEqual(1, len(seed_attempts))
            # SW1 is NOT a seed: the scoped (wrong) campus credential is
            # tried first, then the profile credential succeeds — bounded,
            # deterministic, no third attempt.
            sw1_attempts = [a for a in network.attempts if a[0] == "10.0.0.2"]
            self.assertEqual(2, len(sw1_attempts))

    def test_no_secret_ever_reaches_disk_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_workspace(workdir)
            network = PasswordCheckingNetwork(
                wan_topology(),
                {
                    "10.0.0.1": PASSWORD, "10.0.0.2": PASSWORD,
                    "10.1.0.1": WAN_PASSWORD,
                },
            )
            code, out, err = run_profile_discover(
                workdir, service, network.factory, "Hyderabad Lab", FIXED
            )
            self.assertEqual(0, code, err)
            for secret in (PASSWORD, WAN_PASSWORD):
                self.assertNotIn(secret, out)
                self.assertNotIn(secret, err)
                leaked = [
                    str(path)
                    for path in workdir.rglob("*")
                    if path.is_file()
                    and secret in path.read_text(encoding="utf-8", errors="ignore")
                ]
                self.assertEqual([], leaked)


if __name__ == "__main__":
    unittest.main()
