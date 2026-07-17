"""Acceptance tests for PR-036C — plane-aware logical-interface prediction.

The Vlan1 lesson: an SVI can carry the management address Atlas itself
uses. These tests pin the management/control/data/observability plane
evaluation, management reachability and alternate-path honesty, the
extended risk arithmetic, plane-specific confidence, and the GUI cards —
while proving physical-interface predictions did not change.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.prediction import (
    ChangeRequest,
    classify_interface,
    predict,
    render_prediction_json,
    resolve_interface,
)

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_prediction_architecture import NOW, chain, shutdown_request
from tests.test_profile_isolation import FIXED, add_profile, make_service, run_discover, scope_dir
from tests.test_unified_pipeline import full_outputs


def interface(name: str, ip: str | None = None, status: str = "up") -> dict:
    return {
        "name": name,
        "ip_address": ip,
        "status": status,
        "protocol_status": "up",
        "description": None,
    }


def switch_snapshot(*extra_interfaces: dict, management_ip: str = "10.10.10.2") -> dict:
    """SW1 managed via its Vlan1 SVI; physical uplinks carry no IP."""

    return {
        "snapshot_id": "atlas-topology:" + "0" * 64,
        "device_count": 1,
        "devices": [
            {
                "device_id": "SW1",
                "hostname": "SW1",
                "management_ip": management_ip,
                "platform": "IOSv",
                "interfaces": [
                    interface("GigabitEthernet0/0"),
                    interface("GigabitEthernet0/1"),
                    interface("Vlan1", ip="10.10.10.2"),
                    *extra_interfaces,
                ],
            }
        ],
        "edges": [],
    }


def shut_vlan1(**kwargs) -> ChangeRequest:
    return ChangeRequest(
        request_id="cr-vlan1",
        change_type="shutdown-interface",
        target_device="SW1",
        target_object="Vlan1",
        **kwargs,
    )


def plane(prediction, name: str):
    return next(p for p in prediction.planes if p.plane == name)


class InterfaceClassificationTests(unittest.TestCase):
    def test_types_from_canonical_names(self) -> None:
        self.assertEqual("svi", classify_interface("Vlan1"))
        self.assertEqual("loopback", classify_interface("Loopback0"))
        self.assertEqual("tunnel", classify_interface("Tunnel5"))
        self.assertEqual("port-channel", classify_interface("Port-channel2"))
        self.assertEqual("physical", classify_interface("GigabitEthernet0/1"))
        self.assertEqual("subinterface", classify_interface("GigabitEthernet0/1.20"))
        self.assertEqual("unknown", classify_interface("Weird9"))

    def test_svi_aliases_still_resolve(self) -> None:
        inventory = ("GigabitEthernet0/1", "Vlan1")
        self.assertEqual(("Vlan1", None), resolve_interface("vlan1", inventory))
        self.assertEqual(("Vlan1", None), resolve_interface("Vl1", inventory))


class ManagementPlaneTests(unittest.TestCase):
    def test_svi_owning_the_management_address_predicts_loss(self) -> None:
        prediction = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        management = plane(prediction, "management")
        self.assertEqual("lost", management.status)
        self.assertIn("10.10.10.2", management.explanation)
        self.assertIn("management address Atlas", management.explanation)
        # Consequences: discovery and configuration collection impact.
        self.assertIn("discovery", management.explanation)
        self.assertIn("configuration collection", management.explanation)
        # Careful wording: MAY become unavailable, never a claim about
        # protocols Atlas has not observed.
        self.assertIn("may become unavailable", management.explanation)
        self.assertTrue(management.evidence)

    def test_risk_and_recommendation_reflect_manageability_loss(self) -> None:
        prediction = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        # +25 management loss +10 no alternate = 35 -> high.
        self.assertEqual("high", prediction.risk.level)
        self.assertEqual(35, prediction.risk.score)
        self.assertEqual(
            prediction.risk.score,
            sum(factor.points for factor in prediction.risk.factors),
        )
        names = {factor.name for factor in prediction.risk.factors}
        self.assertIn("management-address-loss", names)
        self.assertIn("no-alternate-management", names)
        self.assertEqual(
            "Do not proceed until an alternate management path is verified",
            prediction.advice.action,
        )

    def test_physical_links_are_not_reported_down(self) -> None:
        prediction = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        data = plane(prediction, "data")
        self.assertIn("remain up", data.explanation)
        self.assertIn("Layer-2 switching continues", data.explanation)
        self.assertEqual((), prediction.blast_radius.affected_devices)
        outcomes = " ".join(o.description for o in prediction.outcomes)
        self.assertNotIn("GigabitEthernet0/0", outcomes)

    def test_verified_alternate_management_path_reduces_risk(self) -> None:
        snapshot = switch_snapshot(interface("Loopback0", ip="192.168.255.1"))
        prediction = predict(
            shut_vlan1(),
            snapshot=snapshot,
            generated_at=NOW,
            seed_addresses=("192.168.255.1",),  # a proven entry address
        )
        management = plane(prediction, "management")
        self.assertEqual("degraded", management.status)
        self.assertIn("verified alternate", management.explanation)
        names = {factor.name for factor in prediction.risk.factors}
        self.assertIn("verified-alternate-management", names)
        self.assertEqual(15, prediction.risk.score)  # 25 - 10
        self.assertNotEqual(
            "Do not proceed until an alternate management path is verified",
            prediction.advice.action,
        )

    def test_candidate_alternate_is_never_treated_as_verified(self) -> None:
        snapshot = switch_snapshot(interface("Loopback0", ip="192.168.255.1"))
        prediction = predict(shut_vlan1(), snapshot=snapshot, generated_at=NOW)
        management = plane(prediction, "management")
        self.assertEqual("lost", management.status)
        self.assertIn("unverified", management.explanation)
        names = {factor.name for factor in prediction.risk.factors}
        self.assertIn("no-alternate-management", names)
        self.assertEqual(
            "Do not proceed until an alternate management path is verified",
            prediction.advice.action,
        )

    def test_loopback_management_dependency(self) -> None:
        snapshot = {
            "snapshot_id": "atlas-topology:" + "0" * 64,
            "device_count": 1,
            "devices": [
                {
                    "device_id": "R1",
                    "hostname": "R1",
                    "management_ip": "192.168.255.1",
                    "platform": "IOSv",
                    "interfaces": [
                        interface("GigabitEthernet0/0", ip="10.0.0.1"),
                        interface("Loopback0", ip="192.168.255.1"),
                    ],
                }
            ],
            "edges": [],
        }
        prediction = predict(
            ChangeRequest(
                request_id="cr-lo0", change_type="shutdown-interface",
                target_device="R1", target_object="Loopback0",
            ),
            snapshot=snapshot,
            generated_at=NOW,
        )
        self.assertEqual("lost", plane(prediction, "management").status)

    def test_dedicated_oob_interface_keeps_management_safe(self) -> None:
        snapshot = {
            "snapshot_id": "atlas-topology:" + "0" * 64,
            "device_count": 1,
            "devices": [
                {
                    "device_id": "SW1",
                    "hostname": "SW1",
                    "management_ip": "172.16.0.5",
                    "platform": "IOSv",
                    "interfaces": [
                        interface("Management0/0", ip="172.16.0.5"),
                        interface("Vlan20", ip="10.20.0.1"),
                    ],
                }
            ],
            "edges": [],
        }
        prediction = predict(
            ChangeRequest(
                request_id="cr-v20", change_type="shutdown-interface",
                target_device="SW1", target_object="Vlan20",
            ),
            snapshot=snapshot,
            generated_at=NOW,
        )
        management = plane(prediction, "management")
        self.assertEqual("no_known_impact", management.status)
        self.assertIn("not the management address", management.explanation)
        names = {factor.name for factor in prediction.risk.factors}
        self.assertNotIn("management-address-loss", names)


class ControlAndDataPlaneTests(unittest.TestCase):
    def test_data_plane_unknown_without_gateway_evidence(self) -> None:
        prediction = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        data = plane(prediction, "data")
        self.assertEqual("unknown", data.status)
        self.assertTrue(
            any("gateway" in item for item in data.missing_evidence)
        )
        # The unknown surfaces in the prediction's stated unknowns too.
        self.assertTrue(
            any("gateway" in unknown for unknown in prediction.unknowns)
        )

    def test_verified_gateway_role_predicts_gateway_impact(self) -> None:
        prediction = predict(
            shut_vlan1(),
            snapshot=switch_snapshot(),
            generated_at=NOW,
            role_evidence={"gateway": True},
        )
        data = plane(prediction, "data")
        self.assertEqual("lost", data.status)
        self.assertIn("default gateway", data.explanation)
        names = {factor.name for factor in prediction.risk.factors}
        self.assertIn("verified-gateway-loss", names)

    def test_routing_adjacency_evidence_predicts_control_impact(self) -> None:
        prediction = predict(
            shut_vlan1(),
            snapshot=switch_snapshot(),
            generated_at=NOW,
            role_evidence={"routing_protocols": ("ospf",)},
        )
        control = plane(prediction, "control")
        self.assertEqual("lost", control.status)
        self.assertIn("ospf", control.explanation)
        names = {factor.name for factor in prediction.risk.factors}
        self.assertIn("control-plane-loss", names)

    def test_absent_protocol_evidence_invents_nothing(self) -> None:
        prediction = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        control = plane(prediction, "control")
        self.assertEqual("no_known_impact", control.status)
        self.assertTrue(control.missing_evidence)
        names = {factor.name for factor in prediction.risk.factors}
        self.assertNotIn("control-plane-loss", names)

    def test_observability_follows_the_management_plane(self) -> None:
        prediction = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        observability = plane(prediction, "observability")
        self.assertEqual("lost", observability.status)
        self.assertIn("blind spot", observability.explanation)
        self.assertIn("stale", observability.explanation)


class ConfidenceAndDeterminismTests(unittest.TestCase):
    def test_plane_specific_confidence(self) -> None:
        prediction = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        management = plane(prediction, "management")
        data = plane(prediction, "data")
        # Direct address-ownership evidence beats missing VLAN evidence.
        self.assertGreater(
            management.confidence_percent, data.confidence_percent
        )
        self.assertLessEqual(management.confidence_percent, 95)

    def test_stale_discovery_lowers_plane_confidence(self) -> None:
        fresh = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        stale = predict(
            shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW, fresh=False
        )
        self.assertLess(
            plane(stale, "management").confidence,
            plane(fresh, "management").confidence,
        )

    def test_plane_serialization_is_deterministic(self) -> None:
        first = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        second = predict(shut_vlan1(), snapshot=switch_snapshot(), generated_at=NOW)
        self.assertEqual(
            render_prediction_json(first), render_prediction_json(second)
        )
        data = first.to_dict()
        self.assertEqual(4, len(data["planes"]))
        json.dumps(data)

    def test_physical_interface_predictions_are_unchanged(self) -> None:
        prediction = predict(shutdown_request(), snapshot=chain(), generated_at=NOW)
        # Same score and action as PR-036B pinned: no management factors
        # fire when the target carries no management address.
        self.assertEqual(45, prediction.risk.score)
        self.assertIn("CAB", prediction.advice.action)
        names = {factor.name for factor in prediction.risk.factors}
        self.assertNotIn("management-address-loss", names)
        # Planes are still evaluated (management via reachability).
        self.assertTrue(prediction.planes)


SVI_BRIEF = (
    "Interface                  IP-Address      OK? Method Status                Protocol\n"
    "GigabitEthernet0/0         unassigned      YES unset  up                    up\n"
    "GigabitEthernet0/1         unassigned      YES unset  up                    up\n"
    "Vlan1                      10.10.10.2      YES manual up                    up\n"
)


class PlaneGuiTests(unittest.TestCase):
    """The CML scenario end to end: SW1 managed through Vlan1."""

    def build_world(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Hyderabad Lab", "10.10.10.2")
        network = ScriptedNetwork(
            {
                "10.10.10.2": full_outputs(
                    "SW1", "10.10.10.2", interfaces_brief=SVI_BRIEF
                )
            }
        )
        run_discover(workdir, service, network, "Hyderabad Lab", FIXED)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_gui_shows_svi_badge_and_management_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_world(Path(tmp))
            # The SVI badge and management context ride the async interface
            # API's detail text — the same evidence the old dropdown showed.
            client.get("/predict?scope=hyderabad-lab")
            details = " | ".join(
                item["detail"] for item in client.get(
                    "/api/device-interfaces?device=SW1&scope=hyderabad-lab"
                ).get_json()["results"]
            )
            self.assertIn("[SVI]", details)
            self.assertIn("10.10.10.2", details)
            self.assertIn("management address", details)

    def test_gui_prediction_shows_plane_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_world(workdir)
            client.get("/predict?scope=hyderabad-lab")
            response = client.post(
                "/predict/run",
                data={"device": "SW1", "interface": "Vlan1"},
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            body = response.data.decode("utf-8")
            for expected in (
                "Management Plane", "Control Plane", "Data Plane",
                "Observability Plane", "Lost",
                "Do not proceed until an alternate management path is verified",
            ):
                self.assertIn(expected, body)
            self.assertNotIn(PASSWORD, body)
            report = json.loads(
                (scope_dir(workdir, "hyderabad-lab") / "prediction_report.json")
                .read_text("utf-8")
            )
            planes = {p["plane"]: p for p in report["planes"]}
            self.assertEqual("lost", planes["management"]["status"])
            self.assertEqual("unknown", planes["data"]["status"])
            self.assertEqual("no_known_impact", planes["control"]["status"])
            self.assertNotIn(PASSWORD, json.dumps(report))

    def test_gui_physical_prediction_remains_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_world(Path(tmp))
            client.get("/predict?scope=hyderabad-lab")
            response = client.post(
                "/predict/run",
                data={"device": "SW1", "interface": "Gi0/1"},  # alias intact
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Risk:", response.data)
            # Physical target with no address: no management-loss claim.
            self.assertNotIn(
                b"Do not proceed until an alternate management path",
                response.data,
            )


if __name__ == "__main__":
    unittest.main()
