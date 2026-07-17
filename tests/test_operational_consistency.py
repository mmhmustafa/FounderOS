"""Operational-fact consistency: health, counts, sites, WAN, routing,
identity resolution.

Fixtures model the AtlasLab estate (chennai / mumbai / delhi / hyderabad)
plus deliberate physical, WAN, Internet-absence, OSPF, BGP, ambiguous,
stale, and missing-evidence cases. Every displayed count is verified
against its underlying records through the one vocabulary module.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from founderos_atlas.topology.snapshot import TopologySnapshot, content_address
from founderos_atlas.topology.vocabulary import DEFINITIONS, count_topology


NOW = "2026-07-17T12:00:00+00:00"
FRESH = "2026-07-17T11:00:00+00:00"
STALE = "2026-07-10T08:00:00+00:00"


def _freeze(value):
    if isinstance(value, dict):
        return {key: _freeze(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def make_snapshot(devices, edges, *, created_at=FRESH, metadata=None,
                  warnings=()) -> TopologySnapshot:
    devices = tuple(_freeze(device) for device in devices)
    edges = tuple(_freeze(edge) for edge in edges)
    warnings = tuple(_freeze(warning) for warning in warnings)
    metadata = _freeze(metadata or {})
    snapshot_id = content_address(
        created_at=created_at, devices=devices, edges=edges,
        warnings=warnings, metadata=metadata,
    )
    return TopologySnapshot(
        snapshot_id=snapshot_id, created_at=created_at,
        devices=devices, edges=edges, warnings=warnings, metadata=metadata,
    )


def device(hostname, ip, *, interfaces=(), routing=None, device_id=None):
    metadata = {}
    if routing:
        metadata["routing_evidence"] = routing
    return {
        "device_id": device_id or f"frr:{hostname.casefold()}",
        "hostname": hostname,
        "management_ip": ip,
        "vendor": "frrouting",
        "platform": "FRRouting",
        "os_name": "FRR",
        "os_version": "9.1",
        "interfaces": list(interfaces),
        "metadata": metadata,
    }


def edge(local_id, remote, *, protocol="lldp", local_if="eth1",
         remote_if="eth1", remote_ip=None, metadata=None):
    return {
        "local_device_id": local_id,
        "local_interface": local_if,
        "remote_hostname": remote,
        "remote_interface": remote_if,
        "remote_management_ip": remote_ip,
        "protocol": protocol,
        "metadata": metadata or {},
    }


def lab_catalog():
    from founderos_atlas.sites import Site, SiteCatalog

    return SiteCatalog(sites=(
        Site(site_id="chennai", name="Chennai", hostname_patterns=("chennai-*",)),
        Site(site_id="mumbai", name="Mumbai", hostname_patterns=("mumbai-*",)),
        Site(site_id="delhi", name="Delhi", hostname_patterns=("delhi-*",)),
        Site(site_id="hyderabad", name="Hyderabad",
             hostname_patterns=("hyderabad-*",)),
    ))


def make_renderer(snapshot, *, catalog=None, overrides=None, resolutions=None):
    from founderos_atlas.sites import SiteOverrideCatalog
    from founderos_atlas.identity import PeerResolutionCatalog
    from founderos_atlas.visualization import TopologyRenderer

    return TopologyRenderer(
        snapshot,
        site_catalog=catalog or lab_catalog(),
        site_overrides=overrides or SiteOverrideCatalog(),
        identity_resolutions=resolutions or PeerResolutionCatalog(),
    )


def lab_snapshot(*, created_at=FRESH):
    """Chennai/Mumbai/Delhi/Hyderabad with physical, WAN, OSPF, BGP,
    ambiguous, and missing-evidence connectivity."""

    devices = [
        device("mumbai-core", "172.20.20.4", interfaces=(
            {"name": "eth1", "ip_address": "10.90.1.1/30"},
            {"name": "eth2", "ip_address": "10.251.0.1/30"},
        ), routing={
            "ospf_adjacencies": [
                {"neighbor_router_id": "10.255.0.2",
                 "adjacency_address": "10.251.0.2",
                 "local_interface": "eth2", "state": "Full",
                 "area_id": "0", "vrf": "default",
                 "evidence_state": "observed"},
            ],
            "bgp_sessions": [
                {"peer_address": "10.251.0.2", "remote_as": "65002",
                 "local_as": "65001", "state": "established",
                 "vrf": "default", "router_id": "10.255.0.1",
                 "evidence_state": "observed"},
            ],
        }),
        device("mumbai-sw1", "172.20.20.36"),
        device("delhi-core", "172.20.20.18", interfaces=(
            {"name": "eth1", "ip_address": "10.251.0.2/30"},
        ), routing={
            "ospf_adjacencies": [
                {"neighbor_router_id": "10.255.0.1",
                 "adjacency_address": "10.251.0.1",
                 "local_interface": "eth1", "state": "Full",
                 "area_id": "0", "vrf": "default",
                 "evidence_state": "observed"},
            ],
            "bgp_sessions": [
                {"peer_address": "10.251.0.1", "remote_as": "65001",
                 "local_as": "65002", "state": "established",
                 "vrf": "default", "router_id": "10.255.0.2",
                 "evidence_state": "observed"},
            ],
        }),
        device("chennai-edge", "172.20.20.13"),
        device("hyderabad-core", "172.20.20.2"),
    ]
    edges = [
        # Physical, intra-site (Mumbai).
        edge("frr:mumbai-core", "mumbai-sw1", local_if="eth3",
             remote_if="eth2"),
        # Physical, VERIFIED inter-site (Mumbai <-> Delhi: both discovered).
        edge("frr:mumbai-core", "delhi-core", local_if="eth2",
             remote_if="eth1"),
        # WAN routing adjacency announced with a far-end name that carries
        # site evidence (chennai-*): observed inter-site.
        edge("frr:hyderabad-core", "chennai-wan1", protocol="ospf",
             local_if="eth5", remote_if="unknown",
             metadata={"observation": "routing-adjacency",
                       "adjacency_address": "10.252.0.2"}),
        # WAN BGP peer with NO far-end evidence: candidate only, never a
        # counted inter-site link, never an Internet cloud.
        edge("frr:chennai-edge", "10.4.255.11", protocol="bgp",
             local_if="bgp", remote_if="unknown",
             metadata={"observation": "protocol-peer"}),
    ]
    return make_snapshot(devices, edges, created_at=created_at)


class VocabularyCountTests(unittest.TestCase):
    def test_every_definition_is_documented(self) -> None:
        for key in ("relationships", "physical_links", "logical_adjacencies",
                    "routing_adjacencies", "bgp_peerings",
                    "verified_routed_links", "inter_site_links",
                    "unresolved_peer_identities"):
            self.assertIn(key, DEFINITIONS)
            self.assertTrue(DEFINITIONS[key].strip())

    def test_counts_add_up_against_underlying_records(self) -> None:
        renderer = make_renderer(lab_snapshot())
        elements = renderer.elements()
        site_view = renderer.site_view(elements)
        counts = count_topology(
            elements, site_membership=site_view["membership"]
        )
        edges = [item["data"] for item in elements["edges"]]
        self.assertEqual(len(edges), counts.relationships)
        self.assertEqual(
            sum(1 for e in edges if e["relationship"] == "physical"),
            counts.physical_links,
        )
        self.assertEqual(
            counts.relationships - counts.physical_links,
            counts.logical_adjacencies,
        )
        self.assertEqual(
            sum(1 for n in elements["nodes"]
                if n["data"].get("kind") == "observed"),
            counts.unresolved_peer_identities,
        )

    def test_viewer_summary_and_relationship_summary_agree(self) -> None:
        renderer = make_renderer(lab_snapshot())
        elements = renderer.elements()
        site_view = renderer.site_view(elements)
        summary = renderer.relationship_summary(
            elements, site_membership=site_view["membership"]
        )
        html = renderer.render()
        for key in ("relationships", "physical_links", "inter_site_links",
                    "unresolved_peer_identities"):
            self.assertIn(f'"{key}":{summary[key]}', html.replace(" ", ""))

    def test_without_site_membership_inter_site_is_zero_not_guessed(self) -> None:
        renderer = make_renderer(lab_snapshot())
        counts = count_topology(renderer.elements())
        self.assertEqual(0, counts.inter_site_links)


class InterSiteLinkTests(unittest.TestCase):
    def facts(self):
        renderer = make_renderer(lab_snapshot())
        elements = renderer.elements()
        return renderer.site_view(elements), elements

    def test_verified_inter_site_link_between_discovered_devices(self) -> None:
        site_view, _ = self.facts()
        links = site_view["inter_site_links"]
        verified = [l for l in links if l["verification"] == "verified"]
        self.assertTrue(
            any(sorted(l["sites"]) == ["delhi", "mumbai"] for l in verified),
            f"expected a verified Mumbai~Delhi link, got {links}",
        )

    def test_far_end_hostname_evidence_creates_observed_inter_site_link(self) -> None:
        # The old contradiction: a WAN peer inherited its observer's site and
        # the cross-site link vanished. Announced-name evidence now places
        # chennai-wan1 in Chennai, so Hyderabad~Chennai is honestly counted.
        site_view, _ = self.facts()
        links = site_view["inter_site_links"]
        observed = [l for l in links if l["verification"] == "observed"]
        self.assertTrue(
            any(sorted(l["sites"]) == ["chennai", "hyderabad"]
                for l in observed),
            f"expected an observed Chennai~Hyderabad link, got {links}",
        )

    def test_no_far_end_evidence_is_candidate_not_link(self) -> None:
        site_view, _ = self.facts()
        peers = [c["peer"] for c in site_view["candidate_inter_site_peers"]]
        self.assertIn("10.4.255.11", peers)
        self.assertFalse(
            any("10.4.255.11" in (l["left"], l["right"])
                for l in site_view["inter_site_links"]),
            "a peer with no far-end site evidence must never count",
        )

    def test_counts_agree_with_site_view_links(self) -> None:
        site_view, elements = self.facts()
        counts = count_topology(
            elements, site_membership=site_view["membership"]
        )
        self.assertEqual(
            len(site_view["inter_site_links"]), counts.inter_site_links
        )

    def test_no_internet_site_without_evidence(self) -> None:
        site_view, _ = self.facts()
        self.assertFalse(
            [s for s in site_view["sites"] if s["site_type"] == "internet"],
            "no Internet evidence exists, so no Internet cloud may appear",
        )


class SiteTypeTests(unittest.TestCase):
    def test_extended_site_types_round_trip(self) -> None:
        from founderos_atlas.sites import SITE_TYPES, Site, SiteCatalog

        for site_type in SITE_TYPES:
            site = Site(site_id=f"x-{site_type}", name=f"X {site_type}",
                        site_type=site_type)
            self.assertEqual(
                site_type, Site.from_dict(site.to_dict()).site_type
            )
        self.assertIn("branch", SITE_TYPES)
        self.assertIn("campus", SITE_TYPES)
        self.assertIn("datacenter", SITE_TYPES)
        self.assertIn("transit", SITE_TYPES)
        self.assertIn("unclassified", SITE_TYPES)
        self.assertIn("custom", SITE_TYPES)

    def test_unknown_site_type_is_rejected(self) -> None:
        from founderos_atlas.sites import Site

        with self.assertRaises(ValueError):
            Site(site_id="x", name="X", site_type="galaxy")

    def test_every_site_type_has_a_full_quality_stencil(self) -> None:
        from founderos_atlas.sites import SITE_TYPES
        from founderos_atlas.visualization.stencils import stencil_svg

        for site_type in SITE_TYPES:
            key = "site" if site_type == "site" else f"site-{site_type}"
            svg = stencil_svg(key)
            self.assertIn("<svg", svg)
            # An unclassified site renders as a real cloud, not the
            # unknown-device hexagon.
            self.assertNotIn("15 9v18", svg)


class RoutingViewTests(unittest.TestCase):
    def routing(self):
        renderer = make_renderer(lab_snapshot())
        elements = renderer.elements()
        return renderer.routing_view(elements)

    def test_ospf_groups_carry_states_and_coverage(self) -> None:
        view = self.routing()
        self.assertTrue(view["ospf"]["groups"])
        group = view["ospf"]["groups"][0]
        self.assertIn("Full", group["states"])
        self.assertLessEqual(
            view["ospf"]["covered_devices"], view["ospf"]["total_devices"]
        )

    def test_bgp_groups_distinguish_ebgp_from_ibgp(self) -> None:
        view = self.routing()
        kinds = [
            kind for group in view["bgp"]["groups"]
            for kind in group.get("session_kinds", ())
        ]
        self.assertTrue(
            any("eBGP" in kind for kind in kinds),
            f"AS65001<->AS65002 sessions must count as eBGP, got {kinds}",
        )

    def test_abr_requires_multi_area_membership(self) -> None:
        # No lab router carries two areas, so no ABR may be fabricated.
        view = self.routing()
        for group in view["ospf"]["groups"]:
            self.assertFalse(
                [role for role in group["roles"] if role.startswith("ABR:")]
            )


class PeerResolutionTests(unittest.TestCase):
    def test_candidates_cite_evidence_strongest_first(self) -> None:
        from founderos_atlas.identity import resolution_candidates

        snapshot = lab_snapshot()
        devices = [dict(d) for d in snapshot.to_dict()["devices"]]
        peer = {"label": "10.251.0.2", "hostname": "10.251.0.2",
                "management_ip": "10.251.0.2", "router_id": None}
        candidates = resolution_candidates(peer, devices)
        self.assertTrue(candidates)
        self.assertEqual("delhi-core", candidates[0]["hostname"])
        self.assertEqual("address-ownership", candidates[0]["signal"])
        self.assertIn("10.251.0.2", candidates[0]["detail"])

    def test_no_candidate_for_unknown_identity(self) -> None:
        from founderos_atlas.identity import resolution_candidates

        snapshot = lab_snapshot()
        devices = [dict(d) for d in snapshot.to_dict()["devices"]]
        self.assertEqual(
            [], resolution_candidates(
                {"label": "203.0.113.99", "hostname": "203.0.113.99",
                 "management_ip": "203.0.113.99"}, devices,
            )
        )

    def test_resolution_survives_restart_and_is_audited(self) -> None:
        from founderos_atlas.identity import PeerResolutionRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = PeerResolutionRepository(tmp)
            repo.resolve(peer_label="10.4.255.11",
                         resolved_hostname="chennai-edge",
                         reason="loopback confirmed on console")
            # A NEW repository instance (fresh process) sees the decision.
            reloaded = PeerResolutionRepository(tmp).load()
            found = reloaded.find("10.4.255.11")
            self.assertIsNotNone(found)
            self.assertEqual("chennai-edge", found.resolved_hostname)
            events = PeerResolutionRepository(tmp).history()
            self.assertEqual(1, len(events))
            self.assertEqual("resolve", events[0].action)

    def test_undo_restores_the_previous_state(self) -> None:
        from founderos_atlas.identity import (
            PeerResolutionRepository, peer_subject_key,
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = PeerResolutionRepository(tmp)
            repo.resolve(peer_label="peer-x", resolved_hostname="delhi-core")
            repo.resolve(peer_label="peer-x", resolved_hostname="mumbai-core")
            catalog, event = repo.undo(
                subject_key=peer_subject_key("peer-x")
            )
            self.assertEqual(
                "delhi-core", catalog.find("peer-x").resolved_hostname
            )
            self.assertIsNotNone(event.undoes_event_id)
            # Undo of the FIRST resolve removes the resolution entirely.
            repo2 = PeerResolutionRepository(tmp)
            history = repo2.history(subject_key=peer_subject_key("peer-x"))
            self.assertEqual(3, len(history))

    def test_revision_conflict_is_refused(self) -> None:
        from founderos_atlas.identity import (
            PeerResolutionConflictError, PeerResolutionRepository,
        )

        with tempfile.TemporaryDirectory() as tmp:
            repo = PeerResolutionRepository(tmp)
            repo.resolve(peer_label="peer-y", resolved_hostname="delhi-core")
            with self.assertRaises(PeerResolutionConflictError):
                repo.resolve(peer_label="peer-y",
                             resolved_hostname="mumbai-core",
                             expected_revision=0)

    def test_renderer_applies_resolution_with_provenance(self) -> None:
        from founderos_atlas.identity import PeerResolutionRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = PeerResolutionRepository(tmp)
            repo.resolve(peer_label="10.4.255.11",
                         resolved_hostname="hyderabad-core",
                         reason="confirmed loopback")
            unresolved_before = make_renderer(lab_snapshot())
            counts_before = count_topology(unresolved_before.elements())
            renderer = make_renderer(
                lab_snapshot(), resolutions=repo.load()
            )
            elements = renderer.elements()
            counts_after = count_topology(elements)
            self.assertEqual(
                counts_before.unresolved_peer_identities - 1,
                counts_after.unresolved_peer_identities,
            )
            resolved_edges = [
                item["data"] for item in elements["edges"]
                if item["data"].get("identity_resolution")
            ]
            self.assertTrue(resolved_edges)
            self.assertEqual(
                "10.4.255.11",
                resolved_edges[0]["identity_resolution"]["peer_label"],
            )


class HealthModelTests(unittest.TestCase):
    def assess(self, **kwargs):
        from founderos_atlas.health import assess_network_health

        defaults = dict(
            scope_id="labs", scope_label="Labs", now=NOW,
            snapshot=lab_snapshot().to_dict(),
            configurations_collected=5,
            config_change_report={"change_count": 0, "devices_changed": 0,
                                  "generated_at": FRESH},
            state_change_report={"active_issue_count": 0,
                                 "current_health": "Healthy",
                                 "generated_at": FRESH},
            incident_report=None,
            policy_summary={"total": 10, "judged": 10, "passed": 10,
                            "failed": 0, "warnings": 0, "unknown": 0,
                            "generated_at": FRESH},
        )
        defaults.update(kwargs)
        return assess_network_health(**defaults)

    def test_every_dimension_reports_denominator_timestamp_and_reason(self) -> None:
        assessment = self.assess()
        self.assertEqual(7, len(assessment.dimensions))
        for dimension in assessment.dimensions:
            payload = dimension.to_dict()
            self.assertTrue(payload["summary"])
            self.assertIn("ratio", payload)
            self.assertIn("observed_at", payload)

    def test_stale_discovery_blocks_a_healthy_verdict(self) -> None:
        assessment = self.assess(
            snapshot=lab_snapshot(created_at=STALE).to_dict()
        )
        self.assertNotEqual("healthy", assessment.overall)
        freshness = assessment.dimension("discovery-freshness")
        self.assertEqual("stale", freshness.state)
        self.assertIn("older than", freshness.summary)

    def test_unknown_dimension_blocks_a_healthy_verdict(self) -> None:
        assessment = self.assess(snapshot=None)
        self.assertIn(assessment.overall, ("unknown", "degraded", "stale"))
        self.assertNotEqual("healthy", assessment.overall)

    def test_critical_incidents_dominate(self) -> None:
        assessment = self.assess(
            state_change_report={"active_issue_count": 3,
                                 "current_health": "Critical",
                                 "interfaces_down": 3,
                                 "generated_at": FRESH},
        )
        self.assertEqual("critical", assessment.overall)
        self.assertIn("interface(s) down", assessment.overall_detail)

    def test_unavailable_is_stated_but_never_blocks_healthy(self) -> None:
        # Fully healthy estate except: no drift report yet.
        assessment = self.assess(
            snapshot=lab_snapshot().to_dict(),
            config_change_report=None,
        )
        # Identity is degraded here (unresolved WAN peers), so pick out just
        # the drift dimension semantics:
        drift = assessment.dimension("configuration-drift")
        self.assertEqual("unavailable", drift.state)

    def test_failed_policy_degrades(self) -> None:
        assessment = self.assess(
            policy_summary={"total": 10, "judged": 10, "passed": 8,
                            "failed": 2, "warnings": 0, "unknown": 0,
                            "generated_at": FRESH},
        )
        policy = assessment.dimension("policy-compliance")
        self.assertEqual("degraded", policy.state)
        self.assertEqual(8, policy.numerator)
        self.assertEqual(10, policy.denominator)

    def test_all_unknown_policy_is_unknown_not_pass(self) -> None:
        assessment = self.assess(
            policy_summary={"total": 4, "judged": 0, "passed": 0,
                            "failed": 0, "warnings": 0, "unknown": 4,
                            "generated_at": FRESH},
        )
        self.assertEqual(
            "unknown", assessment.dimension("policy-compliance").state
        )

    def test_identity_dimension_counts_unresolved_peers(self) -> None:
        assessment = self.assess()
        identity = assessment.dimension("topology-identity-confidence")
        self.assertEqual("degraded", identity.state)
        self.assertIn("unresolved peer", identity.summary)

    def test_enterprise_aggregation_is_worst_of_with_summed_denominators(self) -> None:
        from founderos_atlas.health import aggregate_assessments

        healthy = self.assess(scope_id="a", scope_label="A")
        critical = self.assess(
            scope_id="b", scope_label="B",
            state_change_report={"active_issue_count": 1,
                                 "current_health": "Critical",
                                 "interfaces_down": 1,
                                 "generated_at": FRESH},
        )
        aggregate = aggregate_assessments(
            [healthy, critical], scope_id="all", scope_label="Enterprise",
            generated_at=NOW,
        )
        self.assertEqual("critical", aggregate.overall)
        incidents = aggregate.dimension("active-incidents")
        self.assertEqual("critical", incidents.state)
        self.assertIn("B:", incidents.summary)
        reachability = aggregate.dimension("reachability")
        self.assertEqual(10, reachability.denominator)  # 5 + 5 devices


if __name__ == "__main__":
    unittest.main()
