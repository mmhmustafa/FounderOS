"""Regression: the federated Enterprise snapshot must carry Evidence
Correlation — address ownership, fused relationships, honest unresolved
observations with provenance, and fail-closed ownership conflicts.

Reproduces the fresh-discovery failure where the Site overview showed
raw edge counts, zero inter-site links, and dozens of unresolved peers
whose addresses were provably owned by devices discovered in OTHER
profiles: ``build_enterprise_snapshot`` never ran the correlation
engine, so every consumer of the enterprise snapshot (site overview,
topology map, exports, counts) operated on raw observations only.
"""

from __future__ import annotations

import unittest

from founderos_atlas.enterprise import EnterpriseKnowledge, ScopeContribution
from founderos_atlas.federation import (
    build_enterprise_graph,
    build_enterprise_snapshot,
)

OBSERVED = "2026-07-18T07:00:00+00:00"


def _device(
    hostname: str,
    ip: str,
    *,
    loopback: str | None = None,
    extra_interface: tuple[str, str] | None = None,
    routing: dict | None = None,
) -> dict:
    interfaces = [
        {"name": "GigabitEthernet0/0", "ip_address": ip, "status": "up"},
    ]
    if loopback:
        interfaces.append(
            {"name": "Loopback0", "ip_address": loopback, "status": "up"}
        )
    if extra_interface:
        interfaces.append({
            "name": extra_interface[0],
            "ip_address": extra_interface[1],
            "status": "up",
        })
    return {
        "device_id": f"ios:{hostname}",
        "hostname": hostname,
        "management_ip": ip,
        "platform": "IOSv",
        "serial_number": f"SN-{hostname}",
        "interfaces": interfaces,
        "metadata": (
            {"routing_evidence": routing} if routing else {}
        ),
    }


def _edge(
    local_id: str,
    remote_identity: str,
    *,
    protocol: str = "ospf",
    interface: str = "GigabitEthernet0/0",
    adjacency: str | None = None,
) -> dict:
    return {
        "local_device_id": local_id,
        "local_interface": interface,
        "remote_hostname": remote_identity,
        "remote_interface": None,
        "protocol": protocol,
        "metadata": (
            {"adjacency_address": adjacency} if adjacency else {}
        ),
    }


def _contribution(profile_id, site, devices, edges) -> ScopeContribution:
    return ScopeContribution(
        profile_id=profile_id,
        profile_name=profile_id.title(),
        snapshot={"snapshot_id": f"snap-{profile_id}", "devices": devices,
                  "edges": list(edges)},
        run_id=f"run-{profile_id}",
        observed_at=OBSERVED,
        site_hint=site,
        domain_hint="corp",
    )


def _two_site_world():
    """Two profiles, two sites. Each core names the OTHER site's loopback
    in an OSPF adjacency — resolvable ONLY through the enterprise-wide
    address ownership index. Plus one genuinely unknown peer, and one
    address claimed by two different devices (a conflict)."""

    hyd_core = _device(
        "hyd-core", "10.1.0.1", loopback="10.255.0.1",
        extra_interface=("GigabitEthernet0/9", "192.0.2.10"),
        routing={
            "schema_version": "1.0.0",
            "ospf_adjacencies": [
                {"neighbor_id": "10.255.0.2", "state": "FULL"}
            ],
            "bgp_sessions": [],
        },
    )
    sec_core = _device(
        "sec-core", "10.2.0.1", loopback="10.255.0.2",
        # Same address as hyd-core's extra interface: a genuine
        # ownership conflict that must fail closed.
        extra_interface=("GigabitEthernet0/9", "192.0.2.10"),
    )
    hyd = _contribution(
        "hyderabad", "hyderabad",
        [hyd_core],
        [
            # Cross-site OSPF adjacency naming sec-core's loopback: only
            # the ENTERPRISE ownership index can resolve this.
            _edge("ios:hyd-core", "10.255.0.2", adjacency="10.255.0.2"),
            # A peer no discovered device owns: must stay unresolved.
            _edge("ios:hyd-core", "203.0.113.99", adjacency="203.0.113.99"),
            # A conflicted address: two devices claim 192.0.2.10, so the
            # observation must NOT resolve to either.
            _edge("ios:hyd-core", "192.0.2.10", adjacency="192.0.2.10"),
        ],
    )
    sec = _contribution(
        "secunderabad", "secunderabad",
        [sec_core],
        [_edge("ios:sec-core", "10.255.0.1", adjacency="10.255.0.1")],
    )
    return build_enterprise_graph((hyd, sec))


class FederatedCorrelationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = _two_site_world()
        self.snapshot = build_enterprise_snapshot(self.graph)
        self.metadata = dict(self.snapshot.metadata)
        self.by_hostname = {
            str(d["hostname"]): str(d["device_id"])
            for d in self.snapshot.devices
        }

    def test_snapshot_preserves_address_ownership(self) -> None:
        ownership = self.metadata.get("address_ownership")
        self.assertTrue(
            ownership,
            "enterprise snapshot lost the address ownership index",
        )
        claim = ownership.get("10.255.0.2")
        self.assertIsNotNone(
            claim, "sec-core's loopback is missing from ownership"
        )
        self.assertEqual(self.by_hostname["sec-core"], claim["device_id"])
        self.assertEqual("loopback", claim["kind"])

    def test_cross_profile_adjacency_resolves_to_discovered_device(self) -> None:
        fused = self.metadata.get("correlated_relationships") or ()
        pairs = {
            tuple(sorted((r["left_device_id"], r["right_device_id"])))
            for r in fused
        }
        expected = tuple(sorted((
            self.by_hostname["hyd-core"], self.by_hostname["sec-core"],
        )))
        self.assertIn(
            expected, pairs,
            "the cross-site OSPF adjacency did not fuse into a relationship",
        )
        relationship = next(
            r for r in fused
            if tuple(sorted((r["left_device_id"], r["right_device_id"])))
            == expected
        )
        kinds = {e["kind"] for e in relationship["evidence"]}
        self.assertIn("interface-ownership", kinds)
        self.assertTrue(relationship["contributing_devices"])

    def test_genuine_unknown_stays_unresolved_with_provenance(self) -> None:
        unresolved = self.metadata.get("unresolved_observations") or ()
        identities = {item["remote_identity"] for item in unresolved}
        self.assertIn("203.0.113.99", identities)
        self.assertNotIn(
            "10.255.0.2", identities,
            "a provably-owned address was left unresolved",
        )
        entry = next(
            item for item in unresolved
            if item["remote_identity"] == "203.0.113.99"
        )
        self.assertTrue(entry["reason"])
        self.assertTrue(entry["local_device_id"])
        self.assertEqual("ospf", entry["protocol"])

    def test_ownership_conflict_fails_closed_and_stays_visible(self) -> None:
        conflicts = self.metadata.get("ownership_conflicts") or ()
        addresses = {c["address"] for c in conflicts}
        self.assertIn(
            "192.0.2.10", addresses,
            "the two-device address claim is not reported as a conflict",
        )
        # The observation naming the conflicted address must not resolve.
        unresolved = {
            item["remote_identity"]
            for item in self.metadata.get("unresolved_observations") or ()
        }
        self.assertIn("192.0.2.10", unresolved)

    def test_fused_relationship_spans_two_sites(self) -> None:
        sites = {
            str(d["device_id"]): str(dict(d["metadata"]).get("site"))
            for d in self.snapshot.devices
        }
        fused = self.metadata.get("correlated_relationships") or ()
        spanning = [
            r for r in fused
            if sites.get(r["left_device_id"]) != sites.get(r["right_device_id"])
        ]
        self.assertTrue(
            spanning,
            "no fused relationship spans two sites — the site overview "
            "would show zero inter-site links",
        )

    def test_knowledge_counts_use_fused_relationships(self) -> None:
        knowledge = EnterpriseKnowledge(self.snapshot.to_dict())
        self.assertEqual(1, knowledge.relationship_count)
        # Two honest leftovers: the unknown peer and the conflicted one.
        self.assertEqual(2, knowledge.unresolved_count)
        self.assertEqual(1, knowledge.ownership_conflicts)

    def test_host_local_addresses_are_never_ownership_claims(self) -> None:
        """127.0.0.1 on every device's ``lo`` must not manufacture an
        ownership conflict between unrelated devices (which would
        wrongly degrade enterprise health)."""

        left = _device("lin-a", "10.9.0.1")
        left["interfaces"].append(
            {"name": "lo", "ip_address": "127.0.0.1", "status": "up"}
        )
        right = _device("lin-b", "10.9.0.2")
        right["interfaces"].append(
            {"name": "lo", "ip_address": "127.0.0.1", "status": "up"}
        )
        graph = build_enterprise_graph((
            _contribution("linux-a", "hyderabad", [left], []),
            _contribution("linux-b", "secunderabad", [right], []),
        ))
        snapshot = build_enterprise_snapshot(graph)
        metadata = dict(snapshot.metadata)
        self.assertNotIn(
            "127.0.0.1", metadata.get("address_ownership") or {}
        )
        conflicted = {
            c["address"] for c in metadata.get("ownership_conflicts") or ()
        }
        self.assertNotIn("127.0.0.1", conflicted)

    def test_routing_evidence_provenance_survives_federation(self) -> None:
        hyd_id = self.by_hostname["hyd-core"]
        entry = next(
            d for d in self.snapshot.devices if d["device_id"] == hyd_id
        )
        routing = dict(entry["metadata"]).get("routing_evidence") or {}
        adjacencies = routing.get("ospf_adjacencies") or ()
        self.assertTrue(
            adjacencies, "OSPF routing evidence was lost in federation"
        )
        self.assertEqual("10.255.0.2", adjacencies[0]["neighbor_id"])

    def test_correlation_summary_is_present_for_diagnostics(self) -> None:
        summary = self.metadata.get("correlation")
        self.assertTrue(summary)
        self.assertTrue(summary["deterministic"])
        self.assertEqual(1, summary["relationships"])


if __name__ == "__main__":
    unittest.main()
