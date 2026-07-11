"""Acceptance tests for PR-033 enterprise discovery architecture.

Boundary policy, multi-seed traversal, cross-profile enterprise topology
with evidence-based canonical identity and provenance, site exposure in the
GUI, and the end-to-end scenario: one profile crossing a WAN boundary with
a scoped credential while per-profile baselines stay independent.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.discovery import (
    BOUNDARY_ALLOWED,
    BOUNDARY_DENIED,
    BOUNDARY_OBSERVE_ONLY,
    BoundaryPolicy,
    MultiHopConfig,
    discover_multihop,
)
from founderos_atlas.enterprise import (
    ScopeContribution,
    build_enterprise_topology,
    build_enterprise_view,
)
from founderos_atlas.sites import Site, SiteCatalog, SiteCatalogRepository
from founderos_atlas.web import create_app
from founderos_atlas.workspace import (
    InMemoryCredentialProvider,
    ProfileRepository,
    ProfileService,
)

from tests.test_atlas_transport import PASSWORD
from tests.test_credential_resolution import (
    PasswordCheckingNetwork,
    WAN_PASSWORD,
    run_profile_discover,
    wan_topology,
)
from tests.test_multihop_discovery import ScriptedNetwork, device_outputs
from tests.test_profile_isolation import (
    FIXED,
    add_profile,
    make_service,
    network_a,
    network_b,
    run_discover,
    scope_dir,
)


def snapshot_for(*devices: tuple[str, str, str | None]) -> dict:
    """Minimal snapshot dict: (hostname, ip, serial) triples."""

    return {
        "devices": [
            {
                "hostname": hostname,
                "management_ip": ip,
                "serial_number": serial,
                "vendor": "Cisco",
                "platform": "IOSv",
            }
            for hostname, ip, serial in devices
        ],
        "edges": [],
    }


class BoundaryPolicyTests(unittest.TestCase):
    def test_deny_hostname_glob_wins(self) -> None:
        policy = BoundaryPolicy(deny_hostnames=("isp-*",))
        decision = policy.evaluate_neighbor(
            hostname="ISP-PE1", management_ip="10.0.0.9", protocol="cdp"
        )
        self.assertEqual(BOUNDARY_DENIED, decision.verdict)
        self.assertIn("deny rule", decision.reason)

    def test_excluded_range_is_denied(self) -> None:
        policy = BoundaryPolicy(exclude_cidrs=("10.99.0.0/16",))
        decision = policy.evaluate_neighbor(
            hostname="R9", management_ip="10.99.1.1", protocol="cdp"
        )
        self.assertEqual(BOUNDARY_DENIED, decision.verdict)

    def test_outside_included_ranges_is_observe_only(self) -> None:
        policy = BoundaryPolicy(include_cidrs=("10.0.0.0/16",))
        decision = policy.evaluate_neighbor(
            hostname="R9", management_ip="172.16.0.1", protocol="cdp"
        )
        self.assertEqual(BOUNDARY_OBSERVE_ONLY, decision.verdict)

    def test_allow_hostname_overrides_range_scoping(self) -> None:
        policy = BoundaryPolicy(
            include_cidrs=("10.0.0.0/16",), allow_hostnames=("wan-*",)
        )
        decision = policy.evaluate_neighbor(
            hostname="WAN-R11", management_ip="172.16.0.1", protocol="cdp"
        )
        self.assertEqual(BOUNDARY_ALLOWED, decision.verdict)

    def test_missing_management_ip_is_observe_only(self) -> None:
        decision = BoundaryPolicy().evaluate_neighbor(
            hostname="R9", management_ip=None, protocol="cdp"
        )
        self.assertEqual(BOUNDARY_OBSERVE_ONLY, decision.verdict)

    def test_unfollowed_protocol_is_observe_only(self) -> None:
        decision = BoundaryPolicy(allowed_protocols=("cdp",)).evaluate_neighbor(
            hostname="R9", management_ip="10.0.0.9", protocol="lldp"
        )
        self.assertEqual(BOUNDARY_OBSERVE_ONLY, decision.verdict)

    def test_within_boundaries_is_allowed(self) -> None:
        decision = BoundaryPolicy(include_cidrs=("10.0.0.0/8",)).evaluate_neighbor(
            hostname="R9", management_ip="10.0.0.9", protocol="cdp"
        )
        self.assertEqual(BOUNDARY_ALLOWED, decision.verdict)


class BoundedTraversalTests(unittest.TestCase):
    def test_out_of_scope_neighbor_is_recorded_but_not_traversed(self) -> None:
        network = ScriptedNetwork(wan_topology())
        connected_hosts: list[str] = []

        def factory(host: str):
            connected_hosts.append(host)
            return network.transport_factory(host)

        report = discover_multihop(
            "10.0.0.1",
            factory,
            config=MultiHopConfig(max_depth=2, max_devices=10),
            policy=BoundaryPolicy(include_cidrs=("10.0.0.0/16",)),
        )
        hostnames = {result.device.hostname for result in report.results}
        self.assertEqual({"R1", "SW1"}, hostnames)  # R11 not traversed
        self.assertNotIn("10.1.0.1", connected_hosts)  # never even connected
        # ...but the relationship is preserved, with a structured reason.
        boundary_visits = [
            visit for visit in report.skipped if visit.detail.startswith("boundary")
        ]
        self.assertEqual(1, len(boundary_visits))
        self.assertEqual("R11", boundary_visits[0].hostname)
        self.assertIn("observe-only", boundary_visits[0].detail)
        self.assertIn("outside the profile's included ranges", boundary_visits[0].detail)
        # The observed edge to R11 still exists in the results.
        r1 = next(r for r in report.results if r.device.hostname == "R1")
        self.assertIn("R11", {n.remote_hostname for n in r1.neighbors})

    def test_denied_neighbor_is_recorded_with_the_deny_reason(self) -> None:
        network = ScriptedNetwork(wan_topology())
        report = discover_multihop(
            "10.0.0.1",
            lambda host: network.transport_factory(host),
            config=MultiHopConfig(max_depth=2, max_devices=10),
            policy=BoundaryPolicy(deny_hostnames=("r11",)),
        )
        hostnames = {result.device.hostname for result in report.results}
        self.assertEqual({"R1", "SW1"}, hostnames)
        denied = [v for v in report.skipped if "boundary denied" in v.detail]
        self.assertEqual(1, len(denied))

    def test_limits_still_enforced_alongside_policy(self) -> None:
        network = ScriptedNetwork(wan_topology())
        report = discover_multihop(
            "10.0.0.1",
            lambda host: network.transport_factory(host),
            config=MultiHopConfig(max_depth=2, max_devices=2),
            policy=BoundaryPolicy(),
        )
        self.assertEqual(2, len(report.results))
        self.assertTrue(
            any("maximum device limit" in visit.detail for visit in report.skipped)
        )

    def test_multiple_seeds_are_all_discovered(self) -> None:
        topology = {
            "10.0.0.1": device_outputs("R1", "10.0.0.1"),
            "10.1.0.1": device_outputs("R11", "10.1.0.1"),
        }
        network = ScriptedNetwork(topology)
        report = discover_multihop(
            "10.0.0.1",
            lambda host: network.transport_factory(host),
            config=MultiHopConfig(max_depth=1, max_devices=10),
            extra_seeds=("10.1.0.1",),
        )
        hostnames = {result.device.hostname for result in report.results}
        self.assertEqual({"R1", "R11"}, hostnames)
        self.assertEqual(("10.0.0.1", "10.1.0.1"), report.seed_hosts)

    def test_one_failed_seed_does_not_abort_a_multi_seed_run(self) -> None:
        network = ScriptedNetwork(
            {"10.1.0.1": device_outputs("R11", "10.1.0.1")},
            unreachable=frozenset({"10.0.0.1"}),
        )
        report = discover_multihop(
            "10.0.0.1",
            lambda host: network.transport_factory(host),
            extra_seeds=("10.1.0.1",),
        )
        self.assertEqual(
            {"R11"}, {result.device.hostname for result in report.results}
        )
        self.assertEqual(1, len(report.failed))


class EnterpriseTopologyTests(unittest.TestCase):
    def contribution(self, profile_id, name, snapshot, **kwargs):
        return ScopeContribution(
            profile_id=profile_id,
            profile_name=name,
            snapshot=snapshot,
            run_id=kwargs.pop("run_id", f"run-{profile_id}"),
            observed_at=kwargs.pop("observed_at", "2026-07-10T08:00:00+00:00"),
            **kwargs,
        )

    def test_multiple_profiles_contribute_to_one_topology(self) -> None:
        topology = build_enterprise_topology(
            (
                self.contribution(
                    "hyd", "Hyderabad Lab",
                    snapshot_for(("R1", "10.0.0.1", "S-R1"), ("SW1", "10.0.0.2", "S-SW1")),
                ),
                self.contribution(
                    "sec", "Secunderabad Lab",
                    snapshot_for(("R11", "10.1.0.1", "S-R11")),
                ),
            )
        )
        self.assertEqual(3, topology.device_count)
        self.assertEqual(("Hyderabad Lab", "Secunderabad Lab"), topology.networks)

    def test_strong_evidence_merges_the_same_device(self) -> None:
        topology = build_enterprise_topology(
            (
                self.contribution(
                    "hyd", "Hyderabad Lab", snapshot_for(("R11", "10.1.0.1", "S-R11")),
                    run_id="run-hyd-7",
                ),
                self.contribution(
                    "sec", "Secunderabad Lab", snapshot_for(("R11", "10.1.0.1", "S-R11")),
                    run_id="run-sec-3",
                ),
            )
        )
        self.assertEqual(1, topology.device_count)
        device = topology.devices[0]
        self.assertEqual(("hyd", "sec"), device.profile_ids)
        # Provenance: both profile ids AND both discovery run ids retained.
        self.assertEqual(
            {"run-hyd-7", "run-sec-3"},
            {observation.run_id for observation in device.observations},
        )

    def test_same_hostname_in_two_domains_is_not_merged(self) -> None:
        topology = build_enterprise_topology(
            (
                self.contribution(
                    "a", "Domain A", snapshot_for(("core-r1", "10.0.0.1", "S-A")),
                    domain_hint="corp",
                ),
                self.contribution(
                    "b", "Domain B", snapshot_for(("core-r1", "172.16.0.1", "S-B")),
                    domain_hint="acquired",
                ),
            )
        )
        self.assertEqual(2, topology.device_count)

    def test_same_private_ip_in_two_isolated_scopes_is_not_merged(self) -> None:
        topology = build_enterprise_topology(
            (
                self.contribution(
                    "a", "Site One", snapshot_for(("R1", "10.0.0.1", "S-ONE")),
                ),
                self.contribution(
                    "b", "Site Two", snapshot_for(("R1", "10.0.0.1", "S-TWO")),
                ),
            )
        )
        # Same hostname AND same RFC1918 address — but distinct serials and
        # no declared shared domain: two devices, honestly.
        self.assertEqual(2, topology.device_count)

    def test_hostname_and_ip_merge_only_in_a_declared_shared_domain(self) -> None:
        contributions = (
            self.contribution(
                "a", "Entry A", snapshot_for(("R7", "10.0.0.7", None)),
                domain_hint="corp",
            ),
            self.contribution(
                "b", "Entry B", snapshot_for(("R7", "10.0.0.7", None)),
                domain_hint="corp",
            ),
        )
        merged = build_enterprise_topology(contributions)
        self.assertEqual(1, merged.device_count)
        # Without the shared declaration the same evidence stays separate.
        undeclared = build_enterprise_topology(
            tuple(
                ScopeContribution(
                    profile_id=c.profile_id, profile_name=c.profile_name,
                    snapshot=c.snapshot, run_id=c.run_id, observed_at=c.observed_at,
                )
                for c in contributions
            )
        )
        self.assertEqual(2, undeclared.device_count)

    def test_site_assignment_flows_into_the_topology(self) -> None:
        catalog = SiteCatalog(
            sites=(
                Site(site_id="hyderabad", name="Hyderabad",
                     hostname_patterns=("hyd-*",), cidrs=("10.0.0.0/24",)),
            )
        )
        topology = build_enterprise_topology(
            (
                self.contribution(
                    "hyd", "Hyderabad Lab",
                    snapshot_for(("HYD-R1", "10.0.0.1", "S-R1"),
                                 ("R11", "10.1.0.1", "S-R11")),
                ),
            ),
            catalog=catalog,
        )
        by_name = {device.hostname: device for device in topology.devices}
        self.assertEqual("hyderabad", by_name["HYD-R1"].site.site_id)
        self.assertEqual("medium", by_name["HYD-R1"].site.confidence)
        self.assertEqual("unknown", by_name["R11"].site.label)  # honest


class EnterpriseScenarioTests(unittest.TestCase):
    """The PR-033 first working scenario, end to end through the pipeline."""

    def build_world(self, workdir: Path):
        from founderos_atlas.credentials import (
            CredentialScope,
            CredentialSetRepository,
            CredentialSetService,
        )

        provider = InMemoryCredentialProvider()
        service = ProfileService(
            ProfileRepository(workdir / "workspace"), provider,
            clock=lambda: FIXED,
        )
        CredentialSetService(
            CredentialSetRepository(workdir / "workspace"), provider
        ).add_entry(
            set_name="Enterprise Network Access",
            label="WAN ReadOnly",
            username="atlas",
            password=WAN_PASSWORD,
            priority=10,
            scope=CredentialScope(cidrs=("10.1.0.0/16",)),
        )
        # Profile A: entry point R1, allowed to cross into the WAN range.
        add_profile(
            service, "Hyderabad Lab", "10.0.0.1",
            max_depth=2,
            credential_sets=("enterprise-network-access",),
            site_hint="hyderabad",
        )
        # Profile B: entry point R11 with its own credential.
        add_profile(service, "Secunderabad Lab", "10.1.0.1",
                    password=WAN_PASSWORD, site_hint="secunderabad")
        passwords = {
            "10.0.0.1": PASSWORD, "10.0.0.2": PASSWORD, "10.1.0.1": WAN_PASSWORD,
        }
        return service, passwords

    def test_cross_site_discovery_with_independent_baselines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, passwords = self.build_world(workdir)
            # Profile A crosses the WAN and discovers R11 with the scoped
            # credential; Profile B discovers R11 through its own entry.
            network = PasswordCheckingNetwork(wan_topology(), passwords)
            code, out, err = run_profile_discover(
                workdir, service, network.factory, "Hyderabad Lab", FIXED
            )
            self.assertEqual(0, code, err)
            network = PasswordCheckingNetwork(wan_topology(), passwords)
            code, out, err = run_profile_discover(
                workdir, service, network.factory, "Secunderabad Lab",
                FIXED + timedelta(hours=1),
            )
            self.assertEqual(0, code, err)

            # Enterprise topology: R1, SW1, and ONE canonical R11 observed
            # by both profiles (strong serial evidence).
            topology = build_enterprise_view(
                workdir, service.list_profiles()
            )
            by_name = {device.hostname: device for device in topology.devices}
            self.assertEqual({"R1", "SW1", "R11"}, set(by_name))
            r11 = by_name["R11"]
            self.assertEqual(
                {"hyderabad-lab", "secunderabad-lab"}, set(r11.profile_ids)
            )
            self.assertEqual(2, len(r11.observations))
            self.assertTrue(all(o.run_id for o in r11.observations))

            # Per-profile baselines stay independent: rerunning A compares
            # against A's own previous run only — zero changes, no false
            # removals, B's scope untouched.
            snapshot_b = scope_dir(workdir, "secunderabad-lab") / "topology_snapshot.json"
            before = snapshot_b.read_bytes()
            network = PasswordCheckingNetwork(wan_topology(), passwords)
            code, out, err = run_profile_discover(
                workdir, service, network.factory, "Hyderabad Lab",
                FIXED + timedelta(hours=2),
            )
            self.assertEqual(0, code, err)
            report = json.loads(
                (scope_dir(workdir, "hyderabad-lab") / "change_report.json")
                .read_text("utf-8")
            )
            self.assertEqual(0, report["change_count"])
            self.assertEqual([], report["removed_devices"])
            self.assertEqual(before, snapshot_b.read_bytes())

    def test_gui_exposes_enterprise_view_sites_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, passwords = self.build_world(workdir)
            SiteCatalogRepository(workdir / "workspace").save(
                SiteCatalog(
                    sites=(
                        Site(site_id="hyderabad", name="Hyderabad",
                             explicit_hostnames=("R1", "SW1")),
                        Site(site_id="secunderabad", name="Secunderabad",
                             explicit_hostnames=("R11",)),
                    )
                )
            )
            network = PasswordCheckingNetwork(wan_topology(), passwords)
            run_profile_discover(
                workdir, service, network.factory, "Hyderabad Lab", FIXED
            )
            network = PasswordCheckingNetwork(wan_topology(), passwords)
            run_profile_discover(
                workdir, service, network.factory, "Secunderabad Lab",
                FIXED + timedelta(hours=1),
            )
            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            page = client.get("/topology?scope=all").data
            for expected in (
                b"Enterprise Device Inventory",
                b"<td>R1</td>", b"<td>SW1</td>", b"<td>R11",
                b"<td>hyderabad</td>", b"<td>secunderabad</td>",
                b"Observed by",
            ):
                self.assertIn(expected, page)
            # R11 is ONE canonical inventory row observed via both
            # networks — since PR-037A badged as merged — plus exactly one
            # merge-decision row explaining WHY.
            self.assertEqual(1, page.count(b"<td>R11 <span"))
            self.assertEqual(1, page.count(b"<td>R11</td>"))
            self.assertIn(b"merged", page)
            self.assertIn(b"Merge Decisions", page)
            self.assertIn(b"Hyderabad Lab, Secunderabad Lab", page)
            # Site filter, including honest unknown handling.
            page = client.get("/topology?scope=all&site=secunderabad").data
            self.assertIn(b"<td>R11</td>", page)
            self.assertNotIn(b"<td>R1</td>", page)
            # No secret anywhere in GUI output.
            for path in ("/topology?scope=all", "/credentials", "/profiles"):
                body = client.get(path).data
                self.assertNotIn(PASSWORD.encode(), body)
                self.assertNotIn(WAN_PASSWORD.encode(), body)

    def test_credentials_page_lists_scope_and_never_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, _ = self.build_world(workdir)
            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            page = client.get("/credentials").data
            self.assertIn(b"Enterprise Network Access", page)
            self.assertIn(b"WAN ReadOnly", page)
            self.assertIn(b"range: 10.1.0.0/16", page)
            self.assertNotIn(WAN_PASSWORD.encode(), page)
            # Adding through the GUI stores the secret only in the provider.
            response = client.post(
                "/credentials",
                data={
                    "set_name": "Enterprise Network Access",
                    "label": "Firewall ReadOnly",
                    "username": "fw-ro",
                    "password": "fw-fixture-secret",
                    "priority": "30",
                    "vendors": "Fortinet, Palo Alto",
                },
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Firewall ReadOnly", response.data)
            self.assertNotIn(b"fw-fixture-secret", response.data)
            sets_file = workdir / "workspace" / "credential_sets.json"
            self.assertNotIn("fw-fixture-secret", sets_file.read_text("utf-8"))

    def test_legacy_profiles_keep_working_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")  # single seed, one cred
            code, out, err = run_discover(
                workdir, service, network_a(), "Lab A", FIXED
            )
            self.assertEqual(0, code, err)
            profile = service.get_profile("Lab A")
            self.assertEqual((), profile.seeds)
            self.assertEqual((), profile.credential_sets)
            self.assertIsNone(profile.boundary)
            self.assertEqual(("10.0.0.1",), profile.all_seeds)
            snapshot = json.loads(
                (scope_dir(workdir, "lab-a") / "topology_snapshot.json")
                .read_text("utf-8")
            )
            self.assertEqual(
                {"A1", "A2"}, {d["hostname"] for d in snapshot["devices"]}
            )


if __name__ == "__main__":
    unittest.main()
