"""PR-043.9 (IDENTITY) — Network Identity & Scope tests.

Validates the three-layer model Enterprise → Network → Discovery Profile:
network identity is derived from technical evidence (serials, router IDs,
loopbacks, addresses, topology) and NEVER from the profile name; duplicate
observations of one estate are detected but never auto-merged; discovery
profiles support run/edit/duplicate/archive/delete with delete removing
only the observation point; Mission no longer classifies unused CIDR
addresses as topology changes; and scope is authoritative for every
consumer.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from founderos_atlas.change import ChangeDetector
from founderos_atlas.enterprise import (
    EnterpriseKnowledge,
    ObservationPoint,
    compare_fingerprints,
    detect_duplicate_networks,
    fingerprint_snapshot,
    resolve_networks,
)
from founderos_atlas.discovery.multihop import MultiHopConfig
from founderos_atlas.live import run_multihop_discovery
from founderos_atlas.workspace import (
    InMemoryCredentialProvider,
    ProfileRepository,
    ProfileService,
)

from tests.test_evidence_correlation import (
    ISP_ADDRESSES,
    edge_outputs,
    isp1_outputs,
)
from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_platforms import delhi_network


# -- fixtures ---------------------------------------------------------------------


def delhi_snapshot() -> dict:
    _r, _g, snap = run_multihop_discovery(
        delhi_network().transport_factory, "10.20.0.1",
        extra_seeds=("10.99.0.2",),
        config=MultiHopConfig(max_depth=1, max_devices=64),
    )
    return snap.to_dict()


def isp_snapshot() -> dict:
    net = ScriptedNetwork(
        {
            "172.20.20.7": isp1_outputs(),
            "172.20.20.8": edge_outputs("edge1", "172.20.20.8", "192.0.2.66"),
            "172.20.20.9": edge_outputs("edge2", "172.20.20.9", "192.0.2.70"),
        }
    )
    _r, _g, snap = run_multihop_discovery(
        net.transport_factory, ISP_ADDRESSES[0], extra_seeds=ISP_ADDRESSES[1:],
        config=MultiHopConfig(max_depth=0, max_devices=64),
    )
    return snap.to_dict()


# -- network identity from evidence (Part 2) --------------------------------------


class NetworkFingerprintTests(unittest.TestCase):
    def test_same_estate_two_observations_are_highly_similar(self) -> None:
        # "Delhi lab" and "Delhi lab1": one estate, discovered twice.
        a = fingerprint_snapshot(delhi_snapshot(), seeds=("10.20.0.1", "10.99.0.2"))
        b = fingerprint_snapshot(delhi_snapshot(), seeds=("10.20.0.1", "10.99.0.2"))
        result = compare_fingerprints(a, b)
        self.assertGreaterEqual(result.score, 95)
        self.assertTrue(result.is_duplicate_candidate)

    def test_different_estates_are_dissimilar(self) -> None:
        delhi = fingerprint_snapshot(delhi_snapshot(), seeds=("10.20.0.1",))
        isp = fingerprint_snapshot(isp_snapshot(), seeds=ISP_ADDRESSES)
        result = compare_fingerprints(delhi, isp)
        self.assertLess(result.score, 70)
        self.assertFalse(result.is_duplicate_candidate)

    def test_identity_ignores_the_profile_name(self) -> None:
        """Two identical estates with WILDLY different names are still the
        same network; identity is evidence, never the name."""

        a = fingerprint_snapshot(delhi_snapshot(), seeds=("10.20.0.1",))
        b = fingerprint_snapshot(delhi_snapshot(), seeds=("10.20.0.1",))
        # The fingerprints carry no name at all.
        self.assertNotIn("name", a.to_dict())
        self.assertEqual(a.serials, b.serials)
        self.assertEqual(a.management_ips, b.management_ips)

    def test_serial_overlap_drives_similarity(self) -> None:
        # Build two snapshots that share only a serial number → same device.
        from tests.test_discovery_falcon import _ios_serial_no_hostname

        net_a = ScriptedNetwork(
            {"10.0.0.1": _ios_serial_no_hostname("10.0.0.1", "SER-XYZ")}
        )
        net_b = ScriptedNetwork(
            {"10.9.9.9": _ios_serial_no_hostname("10.9.9.9", "SER-XYZ")}
        )
        _r, _g, snap_a = run_multihop_discovery(
            net_a.transport_factory, "10.0.0.1",
            config=MultiHopConfig(max_depth=0, max_devices=8),
        )
        _r2, _g2, snap_b = run_multihop_discovery(
            net_b.transport_factory, "10.9.9.9",
            config=MultiHopConfig(max_depth=0, max_devices=8),
        )
        a = fingerprint_snapshot(snap_a.to_dict(), seeds=("10.0.0.1",))
        b = fingerprint_snapshot(snap_b.to_dict(), seeds=("10.9.9.9",))
        result = compare_fingerprints(a, b)
        self.assertIn("ser-xyz", a.serials)
        self.assertIn("same serial number(s)", result.reasons)
        self.assertGreaterEqual(result.score, 70)


# -- duplicate detection (Part 3) -------------------------------------------------


class DuplicateDetectionTests(unittest.TestCase):
    def _obs(self, pid, name, snapshot, seeds, archived=False):
        return ObservationPoint(
            profile_id=pid, profile_name=name,
            fingerprint=fingerprint_snapshot(snapshot, seeds=seeds),
            archived=archived,
        )

    def test_duplicate_is_flagged_never_merged(self) -> None:
        obs = [
            self._obs("p1", "Delhi lab", delhi_snapshot(), ("10.20.0.1",)),
            self._obs("p2", "Delhi lab1", delhi_snapshot(), ("10.20.0.1",)),
        ]
        candidates = detect_duplicate_networks(obs)
        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        self.assertGreaterEqual(candidate.similarity.score, 95)
        # No automatic merge — the operator decides (PR-043.10 wording).
        self.assertEqual(
            ["keep-separate", "review-duplicate"], candidate.to_dict()["actions"]
        )

    def test_distinct_networks_are_not_flagged(self) -> None:
        obs = [
            self._obs("p1", "Delhi", delhi_snapshot(), ("10.20.0.1",)),
            self._obs("p2", "ISP edge", isp_snapshot(), ISP_ADDRESSES),
        ]
        self.assertEqual((), detect_duplicate_networks(obs))

    def test_resolve_networks_clusters_duplicates(self) -> None:
        obs = [
            self._obs("p1", "Delhi lab", delhi_snapshot(), ("10.20.0.1",)),
            self._obs("p2", "Delhi lab1", delhi_snapshot(), ("10.20.0.1",)),
            self._obs("p3", "ISP edge", isp_snapshot(), ISP_ADDRESSES),
        ]
        resolution = resolve_networks(obs)
        self.assertEqual(2, resolution.network_count)   # Delhi (x2) + ISP
        self.assertEqual(3, resolution.profile_count)
        self.assertEqual(1, len(resolution.duplicate_candidates))
        delhi = next(
            n for n in resolution.networks if len(n.profile_ids) == 2
        )
        self.assertEqual(
            {"Delhi lab", "Delhi lab1"}, set(delhi.profile_names)
        )

    def test_archived_observation_points_are_excluded(self) -> None:
        obs = [
            self._obs("p1", "Delhi lab", delhi_snapshot(), ("10.20.0.1",)),
            self._obs(
                "p2", "Delhi lab1", delhi_snapshot(), ("10.20.0.1",),
                archived=True,
            ),
        ]
        self.assertEqual((), detect_duplicate_networks(obs))
        self.assertEqual(1, resolve_networks(obs).network_count)


# -- discovery profile management (Part 4) ----------------------------------------


class ProfileManagementTests(unittest.TestCase):
    def service(self, workdir: Path) -> ProfileService:
        return ProfileService(
            ProfileRepository(workdir / "workspace"),
            InMemoryCredentialProvider(),
        )

    def _add(self, service, name="Delhi Lab"):
        return service.add_profile(
            name=name, management_ip="10.20.0.1", username="atlas",
            password="secret",
        )

    def test_duplicate_profile_clones_the_observation_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp))
            original = self._add(service)
            clone = service.duplicate_profile("Delhi Lab", new_name="Delhi Lab1")
            self.assertNotEqual(original.profile_id, clone.profile_id)
            self.assertEqual("Delhi Lab1", clone.name)
            self.assertEqual(original.management_ip, clone.management_ip)
            self.assertIsNone(clone.last_discovery)
            # Independent credential reference.
            self.assertNotEqual(original.credential_ref, clone.credential_ref)
            self.assertEqual(
                "secret",
                service._credentials.get(clone.credential_ref),
            )

    def test_archive_hides_from_active_listing_but_keeps_the_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp))
            self._add(service)
            service.archive_profile("Delhi Lab")
            self.assertEqual((), service.list_profiles())
            self.assertEqual(
                1, len(service.list_profiles(include_archived=True))
            )
            restored = service.archive_profile("Delhi Lab", archived=False)
            self.assertFalse(restored.archived)
            self.assertEqual(1, len(service.list_profiles()))

    def test_delete_removes_only_the_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp))
            self._add(service, name="Delhi A")
            self._add(service, name="Delhi B")
            service.delete_profile("Delhi A")
            names = {p.name for p in service.list_profiles(include_archived=True)}
            self.assertEqual({"Delhi B"}, names)  # only A removed


# -- Mission topology-change semantics (Part 5) -----------------------------------


class MissionChangeSemanticsTests(unittest.TestCase):
    def _snapshot(self, devices, *, stats=None, failed_hosts=None):
        from tests.test_change_intelligence import device_entry, snapshot_dict

        metadata = {}
        if stats is not None:
            metadata["discovery_statistics"] = stats
        if failed_hosts is not None:
            metadata["failed_hosts"] = failed_hosts
        return snapshot_dict(
            [device_entry(*d) for d in devices], metadata=metadata
        )

    def test_unused_cidr_addresses_are_not_topology_changes(self) -> None:
        prev = self._snapshot([("R1", "10.0.0.1")])
        # A /24 scan: 1 device, 251 unused addresses in the statistics.
        current = self._snapshot(
            [("R1", "10.0.0.1")],
            stats={
                "addresses_scanned": 254, "reachable": 1, "authenticated": 1,
                "managed_devices": 1, "unused_addresses": 253,
                "authentication_failures": 0, "unsupported_platforms": 0,
            },
        )
        report = ChangeDetector().compare(prev, current)
        discovery_changes = [
            c for c in report.changes if c.category == "discovery"
        ]
        self.assertEqual([], discovery_changes)  # unused ≠ change

    def test_authentication_failures_remain_a_change(self) -> None:
        prev = self._snapshot([("R1", "10.0.0.1")])
        current = self._snapshot(
            [("R1", "10.0.0.1")],
            stats={
                "addresses_scanned": 10, "reachable": 3, "authenticated": 1,
                "managed_devices": 1, "unused_addresses": 7,
                "authentication_failures": 2, "unsupported_platforms": 0,
            },
        )
        report = ChangeDetector().compare(prev, current)
        discovery_changes = [
            c for c in report.changes if c.category == "discovery"
        ]
        self.assertEqual(1, len(discovery_changes))
        self.assertIn("could not be authenticated", discovery_changes[0].description)

    def test_legacy_snapshots_without_statistics_keep_per_host_behavior(self) -> None:
        prev = self._snapshot([("R1", "10.0.0.1")])
        current = self._snapshot(
            [("R1", "10.0.0.1")], failed_hosts=["10.0.0.7"]
        )
        report = ChangeDetector().compare(prev, current)
        discovery_changes = [
            c for c in report.changes if c.category == "discovery"
        ]
        self.assertEqual(1, len(discovery_changes))
        self.assertIn("10.0.0.7", discovery_changes[0].description)


# -- scope consistency (Parts 1, 7) -----------------------------------------------


class ScopeConsistencyTests(unittest.TestCase):
    def test_scoped_graph_matches_scoped_consumers(self) -> None:
        """A single network's snapshot yields one consistent set of numbers
        for every consumer — the basis of scope authority. The enterprise
        (federated) view spanning two networks differs, as it must."""

        delhi = EnterpriseKnowledge(delhi_snapshot())
        isp = EnterpriseKnowledge(isp_snapshot())
        # Each scope reports ONLY its own devices.
        self.assertEqual(2, delhi.device_count)
        self.assertEqual(3, isp.device_count)
        # The two scopes are genuinely different graphs.
        self.assertNotEqual(delhi.snapshot_id, isp.snapshot_id)

    def test_advisor_answers_from_the_scoped_graph(self) -> None:
        """Advisor consuming a single network's snapshot reports that
        network's counts — not an enterprise-wide total."""

        from founderos_atlas.advisor.engine import AdvisorContext, answer

        class _Graph:
            contributions = ()
            devices = True

        response = answer(
            "Is there any problem in this network?",
            AdvisorContext(
                base_output_dir=Path("."),
                profiles=(),
                graph=_Graph(),
                snapshot=delhi_snapshot(),
                search_index=None,
                generated_at="2026-07-13T00:00:00+00:00",
            ),
        )
        self.assertEqual("health", response.intent)
        self.assertIn("2 managed device", response.summary)  # Delhi only


if __name__ == "__main__":
    unittest.main()
