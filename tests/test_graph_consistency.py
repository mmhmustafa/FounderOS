"""PR-043.8 (CONSISTENCY) — every Atlas module consumes one graph.

Proves the single-source-of-truth contract: Mission, Advisor,
Investigation, Prediction, and Topology all read the SAME Enterprise
Knowledge Graph and agree on device count, relationship count, and
enterprise health. Discovery statistics (address space) stay strictly
separate from operational health: unused addresses are Information, never
a warning, and never reduce discovery success.
"""

from __future__ import annotations

import unittest

from founderos_atlas.dashboard.summary import DashboardSummary  # noqa: F401
from founderos_atlas.enterprise import (
    EnterpriseKnowledge,
    classify_discovery_visits,
)
from founderos_atlas.discovery import resolve_plan
from founderos_atlas.live import run_discovery_plan, run_multihop_discovery
from founderos_atlas.path_intelligence import investigate_path
from founderos_atlas.prediction import ChangeRequest, predict
from founderos_atlas.visualization import TopologyRenderer

from tests.test_evidence_correlation import (
    ISP_ADDRESSES,
    discover_isp_lab,
    edge_outputs,
    isp1_outputs,
)
from tests.test_multihop_discovery import ScriptedNetwork

FIXED = "2026-07-13T00:00:00+00:00"


# -- the discovery-statistics classifier (Parts 1, 2, 7) --------------------------


class DiscoveryStatisticsTests(unittest.TestCase):
    def test_unused_addresses_are_information_not_failures(self) -> None:
        # 9 devices among 254 scanned; the 245 that never answered are
        # unused addresses, not discovery failures.
        stats = classify_discovery_visits(
            connected=9,
            failed_details=tuple(
                "did not answer a reachability probe on any management port"
                for _ in range(245)
            ),
            skipped=0,
            managed_devices=9,
        )
        self.assertEqual(254, stats.addresses_scanned)
        self.assertEqual(9, stats.reachable)
        self.assertEqual(9, stats.authenticated)
        self.assertEqual(9, stats.managed_devices)
        self.assertEqual(245, stats.unused_addresses)
        self.assertEqual(0, stats.authentication_failures)
        # Discovery success is managed / reachable — NOT managed / scanned.
        self.assertEqual(100, stats.discovery_completeness_percent)
        self.assertEqual(4, stats.address_utilization_percent)  # 9/254

    def test_addresses_atlas_declined_to_touch_are_not_scanned(self) -> None:
        """A skipped address was never scanned — it was a decision not to.

        `skipped` counts BGP/OSPF peers that are "not a verified management
        endpoint", devices already discovered under another address, and the
        max-device cap. Counting them as scanned inflated the total past the
        size of the range itself: a /24 sweep reported 270 addresses scanned
        when a /24 holds 254, and the panel's own numbers stopped adding up
        (9 reachable + 245 unused = 254, not 270). The 16 difference was
        exactly the 16 protocol peers the same run reported observing —
        routing facts counted as address space.

        Every other test here passes skipped=0, which is why it survived.
        """

        stats = classify_discovery_visits(
            connected=9,
            failed_details=tuple(
                "did not answer a reachability probe on any management port"
                for _ in range(245)
            ),
            skipped=16,  # protocol peers Atlas deliberately never attempted
            managed_devices=9,
        )
        # 254, the size of the range — not 270.
        self.assertEqual(254, stats.addresses_scanned)
        # ...and the numbers add up on their own.
        self.assertEqual(
            stats.addresses_scanned, stats.reachable + stats.unused_addresses
        )
        self.assertEqual(9, stats.reachable)
        self.assertEqual(245, stats.unused_addresses)

    def test_skipping_more_peers_never_grows_the_address_space(self) -> None:
        """The scanned range does not depend on how much routing Atlas saw."""

        def scanned(skipped: int) -> int:
            return classify_discovery_visits(
                connected=9,
                failed_details=tuple("no answer" for _ in range(245)),
                skipped=skipped,
                managed_devices=9,
            ).addresses_scanned

        self.assertEqual(scanned(0), scanned(16))
        self.assertEqual(scanned(0), scanned(500))

    def test_authentication_failure_reduces_completeness(self) -> None:
        stats = classify_discovery_visits(
            connected=7,
            failed_details=(
                "Authentication failed for 10.0.0.8. Verify the username.",
                "Authentication failed for 10.0.0.9. Verify the username.",
                "did not answer a reachability probe",
            ),
            skipped=0,
            managed_devices=7,
        )
        self.assertEqual(2, stats.authentication_failures)
        self.assertEqual(1, stats.unused_addresses)
        self.assertEqual(9, stats.reachable)  # 7 + 2 auth-failed
        self.assertEqual(78, stats.discovery_completeness_percent)  # 7/9

    def test_unsupported_platform_is_distinct(self) -> None:
        stats = classify_discovery_visits(
            connected=2,
            failed_details=(
                "Unsupported platform detected: JUNOS.",
                "did not answer a reachability probe",
            ),
            skipped=0,
            managed_devices=2,
        )
        self.assertEqual(1, stats.unsupported_platforms)
        self.assertEqual(1, stats.unused_addresses)
        self.assertEqual(3, stats.reachable)  # 2 + 1 unsupported


# -- the Enterprise Knowledge Graph is written into the snapshot ------------------


class StatisticsInSnapshotTests(unittest.TestCase):
    def test_cidr_scan_records_statistics_not_failure_inflation(self) -> None:
        alive = set(ISP_ADDRESSES)

        class Reach:
            def is_reachable(self, host):
                return host in alive

        dead = frozenset(
            f"172.20.20.{i}" for i in range(1, 15)
            if f"172.20.20.{i}" not in alive
        )
        net = ScriptedNetwork(
            {
                "172.20.20.7": isp1_outputs(),
                "172.20.20.8": edge_outputs("edge1", "172.20.20.8", "192.0.2.66"),
                "172.20.20.9": edge_outputs("edge2", "172.20.20.9", "192.0.2.70"),
            },
            unreachable=dead,
        )
        plan = resolve_plan(
            "management-network", cidr="172.20.20.0/28", policy="fast"
        )
        _r, _g, snap, _c, _summary = run_discovery_plan(
            plan, net.transport_factory, reachability=Reach()
        )
        knowledge = EnterpriseKnowledge(snap.to_dict())
        stats = knowledge.statistics
        self.assertEqual(3, stats.managed_devices)
        self.assertEqual(3, stats.reachable)
        self.assertEqual(11, stats.unused_addresses)
        self.assertEqual(100, stats.discovery_completeness_percent)
        # Health is Healthy — unused addresses are never a warning.
        level, _reason = knowledge.health()
        self.assertEqual("Healthy", level)


# -- Mission: operational health vs discovery statistics (Parts 1, 2, 7) ----------


class MissionConsistencyTests(unittest.TestCase):
    def _summary(self, workdir, snapshot_dict):
        import json

        from founderos_atlas.dashboard.summary import build_dashboard_summary

        (workdir / "topology_snapshot.json").write_text(
            json.dumps(snapshot_dict), encoding="utf-8"
        )
        return build_dashboard_summary(
            snapshot_path=workdir / "topology_snapshot.json",
            history_root=workdir / ".atlas" / "history",
            link_base=workdir,
        )

    def test_mission_reports_health_not_subnet_utilization(self) -> None:
        import tempfile
        from pathlib import Path

        alive = set(ISP_ADDRESSES)

        class Reach:
            def is_reachable(self, host):
                return host in alive

        dead = frozenset(
            f"172.20.20.{i}" for i in range(1, 15)
            if f"172.20.20.{i}" not in alive
        )
        net = ScriptedNetwork(
            {
                "172.20.20.7": isp1_outputs(),
                "172.20.20.8": edge_outputs("edge1", "172.20.20.8", "192.0.2.66"),
                "172.20.20.9": edge_outputs("edge2", "172.20.20.9", "192.0.2.70"),
            },
            unreachable=dead,
        )
        plan = resolve_plan(
            "management-network", cidr="172.20.20.0/28", policy="fast"
        )
        _r, _g, snap, _c, _s = run_discovery_plan(
            plan, net.transport_factory, reachability=Reach()
        )
        with tempfile.TemporaryDirectory() as tmp:
            summary = self._summary(Path(tmp), snap.to_dict())
        # BEFORE PR-043.8 this was managed / (managed + 11 unused) = 21%.
        self.assertEqual("100%", summary.discovery_success)
        self.assertEqual("Healthy", summary.status)
        self.assertNotIn("failed discovery", summary.status_detail)
        self.assertEqual(3, summary.managed_devices)
        self.assertEqual(11, summary.unused_addresses)
        self.assertEqual(3, summary.reachable_addresses)
        # Unused addresses are surfaced as Information, never a warning.
        self.assertTrue(
            any("unused" in line for line in summary.recent_activity)
        )
        self.assertFalse(
            any("failed" in line.casefold() for line in summary.recent_activity)
        )


# -- every consumer agrees (Part 8) -----------------------------------------------


class AllConsumersAgreeTests(unittest.TestCase):
    def setUp(self) -> None:
        _r, _g, self.snapshot = discover_isp_lab()
        self.snapshot_dict = self.snapshot.to_dict()

    def test_identical_device_and_relationship_counts(self) -> None:
        knowledge = EnterpriseKnowledge(self.snapshot_dict)
        topo = TopologyRenderer(self.snapshot).elements()
        topo_devices = sum(
            1 for node in topo["nodes"]
            if node["data"]["kind"] == "discovered"
        )
        topo_relationships = len(topo["edges"])
        self.assertEqual(3, knowledge.device_count)
        self.assertEqual(3, topo_devices)
        self.assertEqual(knowledge.relationship_count, topo_relationships)
        self.assertEqual(2, knowledge.relationship_count)

    def test_investigation_walks_a_path_topology_shows(self) -> None:
        """Part 4: a routed path visible in Topology (ISP1↔Edge1, fused
        from BGP peer + interface ownership) is walkable in Investigation.
        Before CONSISTENCY this returned no-path — edge1 was reachable
        only through a BGP peer ADDRESS, not a raw edge."""

        result = investigate_path(
            "isp1", "edge1", snapshot=self.snapshot_dict,
            generated_at=FIXED, fresh=True,
        )
        self.assertEqual("connected", result.status)
        self.assertEqual(("isp1", "edge1"), result.path)

    def test_prediction_sees_the_fused_dependency(self) -> None:
        """Part 5: shutting ISP1's link interface affects edge1 —
        Prediction reasons over the same fused relationship."""

        prediction = predict(
            ChangeRequest(
                request_id="t", change_type="shutdown-interface",
                target_device="isp1", target_object="eth1", requested_at=FIXED,
            ),
            snapshot=self.snapshot_dict, generated_at=FIXED, fresh=True,
        )
        self.assertGreaterEqual(prediction.blast_radius.device_count, 1)
        self.assertIn("edge1", prediction.blast_radius.affected_devices)

    def test_health_is_consistent_across_consumers(self) -> None:
        knowledge = EnterpriseKnowledge(self.snapshot_dict)
        level, _reason = knowledge.health()
        self.assertEqual("Healthy", level)
        # Advisor's health handler reads the same graph.
        from founderos_atlas.advisor.engine import AdvisorContext, answer

        class _Graph:
            contributions = ()
            devices = knowledge.devices

        response = answer(
            "Is there any problem in the enterprise?",
            AdvisorContext(
                base_output_dir=__import__("pathlib").Path("."),
                profiles=(),
                graph=_Graph(),
                snapshot=self.snapshot_dict,
                search_index=None,
                generated_at=FIXED,
            ),
        )
        # Advisor answers from the graph — never "not enough evidence".
        self.assertNotIn("enough evidence", response.summary.casefold())
        self.assertIn("healthy", response.summary.casefold())
        self.assertIn("3 managed device", response.summary)


# -- Advisor answers "is there a problem?" from the graph (Part 3) -----------------


class AdvisorGraphAnswerTests(unittest.TestCase):
    def test_problem_question_summarizes_graph_evidence(self) -> None:
        from founderos_atlas.advisor.engine import AdvisorContext, answer

        _r, _g, snapshot = discover_isp_lab()

        class _Graph:
            contributions = ()
            devices = True

        response = answer(
            "Is there any problem in DelhiLab?",
            AdvisorContext(
                base_output_dir=__import__("pathlib").Path("."),
                profiles=(),
                graph=_Graph(),
                snapshot=snapshot.to_dict(),
                search_index=None,
                generated_at=FIXED,
            ),
        )
        self.assertEqual("health", response.intent)
        self.assertNotIn("enough evidence", response.summary.casefold())
        self.assertIn("relationship", response.summary.casefold())

    def test_no_evidence_only_when_graph_is_empty(self) -> None:
        from founderos_atlas.advisor.engine import AdvisorContext, answer

        class _Graph:
            contributions = ()
            devices = ()

        response = answer(
            "Is there any problem in DelhiLab?",
            AdvisorContext(
                base_output_dir=__import__("pathlib").Path("."),
                profiles=(),
                graph=_Graph(),
                snapshot=None,
                search_index=None,
                generated_at=FIXED,
            ),
        )
        # With a genuinely empty graph, "no evidence" is the honest answer.
        self.assertIn("enough evidence", response.summary.casefold())


if __name__ == "__main__":
    unittest.main()
