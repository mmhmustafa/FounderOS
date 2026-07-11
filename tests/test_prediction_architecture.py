"""Acceptance tests for the PR-036A predictive change intelligence architecture.

Architecture-focused: models and relationships, serialization,
deterministic behaviour, extensibility (change types, evaluators, graph
layers), honest unknowns, and the first working slice — "what happens if
I shut this interface?" answered from real topology evidence.
"""

from __future__ import annotations

import unittest

from founderos_atlas.prediction import (
    Boundary,
    ChangeRequest,
    ChangeTypeSpec,
    DependencyEdge,
    DependencyNode,
    Evaluation,
    PredictedOutcome,
    assess_confidence,
    build_topology_dependency_graph,
    change_type,
    device_node_id,
    estimate_rollback,
    interface_node_id,
    known_change_types,
    predict,
    register_change_type,
    register_evaluator,
    registered_evaluators,
)
from founderos_atlas.prediction.simulator import _EVALUATORS


NOW = "2026-07-11T08:00:00+00:00"


def topology(devices: dict[str, list[str]], links: tuple[tuple[str, str, str, str], ...]) -> dict:
    """Snapshot fixture: hostname -> interfaces; links (dev, if, dev, if)."""

    return {
        "snapshot_id": "atlas-topology:" + "0" * 64,
        "device_count": len(devices),
        "devices": [
            {
                "device_id": hostname,
                "hostname": hostname,
                "management_ip": f"10.0.0.{index + 1}",
                "platform": "IOSv",
                "interfaces": [{"name": name, "status": "up"} for name in names],
            }
            for index, (hostname, names) in enumerate(sorted(devices.items()))
        ],
        "edges": [
            {
                "local_device_id": local,
                "local_interface": local_if,
                "remote_hostname": remote,
                "remote_interface": remote_if,
            }
            for local, local_if, remote, remote_if in links
        ],
    }


def chain() -> dict:
    """R1 -- SW1 -- SW2: SW1 is the only path between R1 and SW2."""

    return topology(
        {"R1": ["Gi0/1"], "SW1": ["Gi0/1", "Gi0/2"], "SW2": ["Gi0/1"]},
        (
            ("R1", "Gi0/1", "SW1", "Gi0/1"),
            ("SW1", "Gi0/2", "SW2", "Gi0/1"),
        ),
    )


def triangle() -> dict:
    """R1 -- SW1 -- SW2 -- R1: every pair has an alternate path."""

    return topology(
        {"R1": ["Gi0/1", "Gi0/2"], "SW1": ["Gi0/1", "Gi0/2"], "SW2": ["Gi0/1", "Gi0/2"]},
        (
            ("R1", "Gi0/1", "SW1", "Gi0/1"),
            ("SW1", "Gi0/2", "SW2", "Gi0/1"),
            ("SW2", "Gi0/2", "R1", "Gi0/2"),
        ),
    )


def shutdown_request(device: str = "SW1", interface: str = "Gi0/2") -> ChangeRequest:
    return ChangeRequest(
        request_id="cr-1",
        change_type="shutdown-interface",
        target_device=device,
        target_object=interface,
        description=f"Shut {interface} on {device}",
        requested_at=NOW,
    )


class ModelTests(unittest.TestCase):
    def test_change_request_round_trips(self) -> None:
        request = shutdown_request()
        self.assertEqual(request, ChangeRequest.from_dict(request.to_dict()))
        self.assertEqual("SW1 Gi0/2", request.subject)

    def test_change_request_validation(self) -> None:
        with self.assertRaises(ValueError):
            ChangeRequest(request_id="", change_type="x", target_device="R1")

    def test_boundary_defaults_to_enterprise_wide(self) -> None:
        self.assertTrue(Boundary().is_enterprise_wide)
        self.assertFalse(Boundary(profile_ids=("hyd",)).is_enterprise_wide)

    def test_prediction_serializes_completely(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW
        )
        data = prediction.to_dict()
        for key in (
            "schema_version", "change_request", "boundary", "outcomes",
            "blast_radius", "critical_paths", "redundancy", "rollback",
            "severity", "confidence", "recommendations", "unknowns", "basis",
        ):
            self.assertIn(key, data)
        # Everything is plain JSON-compatible data.
        import json

        json.dumps(data)


class ChangeTypeRegistryTests(unittest.TestCase):
    def test_builtin_change_vocabulary(self) -> None:
        names = {spec.name for spec in known_change_types()}
        for expected in (
            "shutdown-interface", "remove-vlan", "delete-route",
            "modify-acl", "disable-protocol", "reboot-device",
            "upgrade-firmware",
        ):
            self.assertIn(expected, names)

    def test_new_change_types_register_without_core_changes(self) -> None:
        register_change_type(
            ChangeTypeSpec(
                name="restart-kubernetes-cni",
                category="cloud",
                reversible_by_default=True,
                description="Restart a CNI daemonset.",
            )
        )
        try:
            self.assertIsNotNone(change_type("restart-kubernetes-cni"))
        finally:
            from founderos_atlas.prediction.change_requests import _REGISTRY

            _REGISTRY.pop("restart-kubernetes-cni", None)


class DependencyGraphTests(unittest.TestCase):
    def test_graph_builds_devices_interfaces_and_links(self) -> None:
        graph = build_topology_dependency_graph(chain())
        self.assertEqual(3, len(graph.nodes("device")))
        self.assertEqual(4, len(graph.nodes("interface")))
        self.assertIsNotNone(graph.node(interface_node_id("SW1", "Gi0/2")))

    def test_links_traverse_both_interface_endpoints(self) -> None:
        graph = build_topology_dependency_graph(chain())
        # R1 <-> SW2 only through SW1's interfaces: removing either endpoint
        # of the SW1--SW2 link breaks the path.
        r1, sw2 = device_node_id("R1"), device_node_id("SW2")
        self.assertTrue(graph.path_exists(r1, sw2))
        for endpoint in (
            interface_node_id("SW1", "Gi0/2"),
            interface_node_id("SW2", "Gi0/1"),
        ):
            self.assertFalse(
                graph.path_exists(r1, sw2, without=frozenset({endpoint}))
            )

    def test_graph_accepts_future_layers_without_model_changes(self) -> None:
        graph = build_topology_dependency_graph(chain())
        graph.add_node(
            DependencyNode(
                node_id="service:dns", kind="service", name="dns", device="SW2"
            )
        )
        graph.add_node(
            DependencyNode(
                node_id="application:erp", kind="application", name="erp"
            )
        )
        graph.add_edge(
            DependencyEdge(device_node_id("SW2"), "service:dns", "hosts")
        )
        graph.add_edge(DependencyEdge("service:dns", "application:erp", "depends-on"))
        # Kubernetes/cloud kinds are just strings — nothing to extend.
        graph.add_node(
            DependencyNode(node_id="cni:calico", kind="kubernetes-cni", name="calico")
        )
        self.assertEqual(1, len(graph.nodes("kubernetes-cni")))
        dependents = graph.dependents_of(device_node_id("SW2"))
        self.assertIn("service:dns", [node.node_id for node in dependents])
        self.assertIn("application:erp", [node.node_id for node in dependents])


class PredictionPipelineTests(unittest.TestCase):
    def test_shutdown_prediction_answers_what_happens(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW
        )
        # SW2 loses its only path: expected outcomes, blast radius, and a
        # broken critical path — the customer WOW answer.
        self.assertEqual("high", prediction.severity)
        self.assertIn("SW2", prediction.blast_radius.affected_devices)
        self.assertTrue(prediction.critical_paths)
        self.assertFalse(prediction.redundancy.redundant)
        descriptions = " ".join(o.description for o in prediction.outcomes)
        self.assertIn("administratively down", descriptions)
        self.assertIn("SW2", descriptions)
        self.assertTrue(
            any("maintenance window" in line for line in prediction.recommendations)
        )

    def test_redundancy_absorbs_the_same_change_in_a_triangle(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=triangle(), generated_at=NOW
        )
        self.assertEqual((), prediction.critical_paths)
        self.assertTrue(prediction.redundancy.redundant)
        self.assertEqual((), prediction.blast_radius.affected_devices)
        self.assertNotEqual("high", prediction.severity)
        self.assertTrue(
            any("Alternate" in line for line in prediction.recommendations)
        )

    def test_richer_graphs_produce_richer_blast_radii(self) -> None:
        graph = build_topology_dependency_graph(chain())
        graph.add_node(
            DependencyNode(
                node_id="service:dns", kind="service", name="dns", device="SW2"
            )
        )
        graph.add_edge(
            DependencyEdge(device_node_id("SW2"), "service:dns", "hosts")
        )
        prediction = predict(
            shutdown_request(), snapshot=chain(), graph=graph, generated_at=NOW
        )
        # The service behind the isolated device is affected — no impact
        # code changed, only the graph grew.
        self.assertIn("dns", prediction.blast_radius.affected_services)

    def test_reboot_prediction_uses_the_device_as_the_change(self) -> None:
        request = ChangeRequest(
            request_id="cr-2",
            change_type="reboot-device",
            target_device="SW1",
        )
        prediction = predict(request, snapshot=chain(), generated_at=NOW)
        self.assertIn("SW2", prediction.blast_radius.affected_devices)
        self.assertFalse(prediction.rollback.reversible)

    def test_unregistered_change_type_predicts_honestly(self) -> None:
        request = ChangeRequest(
            request_id="cr-3",
            change_type="disable-hsrp",
            target_device="SW1",
        )
        prediction = predict(request, snapshot=chain(), generated_at=NOW)
        self.assertTrue(
            any("not yet" in unknown or "no evaluator" in unknown
                for unknown in prediction.unknowns)
        )
        self.assertIn(prediction.confidence.band, ("low", "medium"))
        self.assertEqual("possible", prediction.outcomes[0].likelihood)

    def test_unknown_target_is_stated_not_guessed(self) -> None:
        prediction = predict(
            shutdown_request(device="GHOST", interface="Gi0/9"),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual("low", prediction.severity)
        self.assertTrue(
            any("not present" in unknown for unknown in prediction.unknowns)
        )

    def test_evaluator_registry_is_extensible(self) -> None:
        def custom(request: ChangeRequest, graph) -> Evaluation:
            return Evaluation(
                target_node_id=device_node_id(request.target_device),
                outcomes=(
                    PredictedOutcome(
                        category="policy",
                        description="ACL evaluation placeholder",
                        likelihood="possible",
                    ),
                ),
            )

        register_evaluator("modify-acl", custom)
        try:
            self.assertIn("modify-acl", registered_evaluators())
            prediction = predict(
                ChangeRequest(
                    request_id="cr-4", change_type="modify-acl",
                    target_device="SW1",
                ),
                snapshot=chain(),
                generated_at=NOW,
            )
            self.assertEqual(
                "ACL evaluation placeholder", prediction.outcomes[0].description
            )
        finally:
            _EVALUATORS.pop("modify-acl", None)

    def test_prediction_is_deterministic(self) -> None:
        import json

        first = predict(shutdown_request(), snapshot=chain(), generated_at=NOW)
        second = predict(shutdown_request(), snapshot=chain(), generated_at=NOW)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )


class ConfidenceAndRollbackTests(unittest.TestCase):
    def test_confidence_is_documented_and_never_100(self) -> None:
        best = assess_confidence(
            topology_available=True,
            fresh=True,
            configuration_captured=True,
            history_available=True,
            evaluator_registered=True,
        )
        self.assertLessEqual(best.score, 0.95)
        self.assertLess(best.percent, 100)
        self.assertEqual(
            round(sum(factor.points for factor in best.factors), 4),
            round(best.score, 4),
        )

    def test_unknown_layers_and_contradictions_lower_confidence(self) -> None:
        clean = assess_confidence(
            topology_available=True, fresh=True, configuration_captured=False,
            history_available=False, evaluator_registered=True,
        )
        murky = assess_confidence(
            topology_available=True, fresh=True, configuration_captured=False,
            history_available=False, evaluator_registered=True,
            unknown_layers=2, contradictions=1,
        )
        self.assertLess(murky.score, clean.score)
        names = {factor.name for factor in murky.factors}
        self.assertIn("unknown-dependency-layers", names)
        self.assertIn("contradicting-evidence", names)

    def test_prediction_confidence_reflects_missing_evidence(self) -> None:
        with_config = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW,
            configuration_captured=True, history_available=True,
        )
        without = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW,
        )
        self.assertGreater(
            with_config.confidence.score, without.confidence.score
        )

    def test_rollback_estimates_per_change_type(self) -> None:
        trivial = estimate_rollback(shutdown_request())
        self.assertEqual("trivial", trivial.complexity)
        self.assertTrue(trivial.reversible)
        upgrade = estimate_rollback(
            ChangeRequest(
                request_id="cr-5", change_type="upgrade-firmware",
                target_device="R1",
            )
        )
        self.assertEqual("high", upgrade.complexity)
        self.assertFalse(upgrade.reversible)
        self.assertTrue(upgrade.prerequisites)
        route_without_config = estimate_rollback(
            ChangeRequest(
                request_id="cr-6", change_type="delete-route",
                target_device="R1",
            ),
            configuration_captured=False,
        )
        route_with_config = estimate_rollback(
            ChangeRequest(
                request_id="cr-7", change_type="delete-route",
                target_device="R1",
            ),
            configuration_captured=True,
        )
        self.assertEqual("moderate", route_without_config.complexity)
        self.assertEqual("low", route_with_config.complexity)
        unknown = estimate_rollback(
            ChangeRequest(
                request_id="cr-8", change_type="totally-new-thing",
                target_device="R1",
            )
        )
        self.assertEqual("unknown", unknown.complexity)


if __name__ == "__main__":
    unittest.main()
