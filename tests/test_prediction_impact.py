"""Acceptance tests for PR-036B — the first working prediction engine.

Vertical slice: interface-shutdown predictions with documented risk
(low/medium/high/critical), honest unknown redundancy, structured advice
with the WHY, evidence-citing explanations, service-level prediction over
real scope artifacts, and the GUI Predict page + dashboard panel.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.prediction import (
    ChangeRequest,
    predict,
    predict_change,
    render_prediction_markdown,
    resolve_interface,
)

from tests.test_atlas_transport import PASSWORD
from tests.test_prediction_architecture import (
    NOW,
    chain,
    shutdown_request,
    topology,
    triangle,
)
from tests.test_profile_isolation import (
    FIXED,
    add_profile,
    make_service,
    network_a,
    run_discover,
    scope_dir,
)


def access_port_topology() -> dict:
    """SW1 has Gi0/9 with no discovered neighbor: a plain access port."""

    data = topology(
        {"R1": ["Gi0/1"], "SW1": ["Gi0/1", "Gi0/9"]},
        (("R1", "Gi0/1", "SW1", "Gi0/1"),),
    )
    return data


class RiskAndAdviceTests(unittest.TestCase):
    def test_access_port_shutdown_is_low_risk_proceed(self) -> None:
        prediction = predict(
            shutdown_request(device="SW1", interface="Gi0/9"),
            snapshot=access_port_topology(),
            generated_at=NOW,
        )
        self.assertEqual("low", prediction.risk.level)
        self.assertEqual("Proceed", prediction.advice.action)
        self.assertEqual((), prediction.blast_radius.affected_devices)
        self.assertEqual((), prediction.critical_paths)

    def test_transit_shutdown_breaks_paths_and_recommends_cab(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW
        )
        # +25 broken paths, +5 device, +5 links, +10 unknown redundancy = 45.
        self.assertEqual("high", prediction.risk.level)
        self.assertEqual(45, prediction.risk.score)
        self.assertIn("CAB", prediction.advice.action)
        self.assertTrue(prediction.advice.reasons)
        # The risk arithmetic is auditable: factors sum to the score.
        self.assertEqual(
            prediction.risk.score,
            sum(factor.points for factor in prediction.risk.factors),
        )

    def test_verified_redundancy_downgrades_to_maintenance_window(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=triangle(), generated_at=NOW
        )
        self.assertEqual("low", prediction.risk.level)
        self.assertEqual(
            "Proceed during a maintenance window", prediction.advice.action
        )
        self.assertTrue(prediction.redundancy.redundant)
        self.assertTrue(
            any("Alternate" in reason for reason in prediction.advice.reasons)
        )

    def test_unknown_redundancy_is_never_assumed(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW
        )
        self.assertIsNone(prediction.redundancy.redundant)
        self.assertIn("not assumed", prediction.redundancy.detail)
        factor_names = {factor.name for factor in prediction.risk.factors}
        self.assertIn("unknown-redundancy", factor_names)
        self.assertTrue(
            any("never assumes" in reason for reason in prediction.advice.reasons)
        )

    def test_degraded_health_and_instability_raise_risk_to_critical(self) -> None:
        prediction = predict(
            shutdown_request(),
            snapshot=chain(),
            generated_at=NOW,
            health_score=60,
            historically_unstable=True,
        )
        self.assertEqual("critical", prediction.risk.level)  # 45 + 10 + 10
        self.assertIn("CAB", prediction.advice.action)
        factor_names = {factor.name for factor in prediction.risk.factors}
        self.assertIn("degraded-enterprise-health", factor_names)
        self.assertIn("historical-instability", factor_names)

    def test_unknown_interface_requires_fresh_discovery(self) -> None:
        prediction = predict(
            shutdown_request(device="SW1", interface="Gi0/99"),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual("Run a fresh discovery first", prediction.advice.action)
        self.assertTrue(
            any("not present" in unknown for unknown in prediction.unknowns)
        )

    def test_unknown_device_requires_fresh_discovery(self) -> None:
        prediction = predict(
            shutdown_request(device="GHOST", interface="Gi0/1"),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual("Run a fresh discovery first", prediction.advice.action)

    def test_no_topology_lowers_confidence_and_states_it(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=None, generated_at=NOW
        )
        self.assertEqual("low", prediction.confidence.band)
        self.assertTrue(prediction.unknowns)


class BlastRadiusAndExplanationTests(unittest.TestCase):
    def test_blast_radius_includes_sites_and_health_impact(self) -> None:
        prediction = predict(
            shutdown_request(),
            snapshot=chain(),
            generated_at=NOW,
            device_sites={"SW2": "secunderabad", "R1": "hyderabad"},
        )
        self.assertEqual(("secunderabad",), prediction.blast_radius.affected_sites)
        self.assertEqual(
            -14,  # -8 link + -6 x 1 isolated device (intelligence weights)
            prediction.blast_radius.attributes["estimated_health_impact"],
        )

    def test_explanation_cites_evidence_and_confidence(self) -> None:
        prediction = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW,
            history_available=True,
        )
        text = " ".join(prediction.explanation)
        self.assertIn("SW2", text)
        self.assertIn("topology snapshot", text)
        self.assertIn("Redundancy:", text)
        self.assertIn("Confidence", text)
        self.assertIn("discovery history", text)

    def test_confidence_rises_with_evidence_and_never_exceeds_95(self) -> None:
        rich = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW,
            history_available=True, configuration_captured=True, fresh=True,
        )
        poor = predict(
            shutdown_request(), snapshot=chain(), generated_at=NOW,
            history_available=False, configuration_captured=False, fresh=False,
        )
        self.assertGreater(rich.confidence.score, poor.confidence.score)
        self.assertLessEqual(rich.confidence.percent, 95)

    def test_prediction_serializes_with_risk_advice_and_context(self) -> None:
        request = ChangeRequest(
            request_id="cr-9",
            change_type="shutdown-interface",
            target_device="SW1",
            target_object="Gi0/2",
            reason="port migration",
            maintenance_window="Sat 02:00-04:00",
            requester="netops",
        )
        self.assertEqual(request, ChangeRequest.from_dict(request.to_dict()))
        prediction = predict(request, snapshot=chain(), generated_at=NOW)
        data = prediction.to_dict()
        self.assertEqual("high", data["risk"]["level"])
        self.assertTrue(data["risk"]["factors"])
        self.assertIn("CAB", data["advice"]["action"])
        self.assertTrue(data["explanation"])
        self.assertEqual("port migration", data["change_request"]["reason"])
        json.dumps(data)  # fully JSON-serializable

    def test_markdown_report_is_cab_ready(self) -> None:
        request = ChangeRequest(
            request_id="cr-10",
            change_type="shutdown-interface",
            target_device="SW1",
            target_object="Gi0/2",
            reason="port migration",
            maintenance_window="Sat 02:00-04:00",
            requester="netops",
        )
        prediction = predict(request, snapshot=chain(), generated_at=NOW)
        markdown = render_prediction_markdown(prediction)
        for section in (
            "# Atlas Change Prediction",
            "Predicted risk",
            "## Blast Radius",
            "## Risk Factors",
            "## Why",
            "## Recommendation",
            "## Rollback",
            "## What Atlas Cannot See",
            "Sat 02:00-04:00",
            "netops",
        ):
            self.assertIn(section, markdown)
        self.assertNotIn("100%", markdown)


class PredictionServiceTests(unittest.TestCase):
    """predict_change over a real discovered scope's artifacts."""

    def build_scope(self, workdir: Path):
        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        run_discover(workdir, service, network_a(), "Lab A", FIXED)
        return service, scope_dir(workdir, "lab-a")

    def test_service_predicts_from_scope_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, scope = self.build_scope(workdir)
            request = ChangeRequest(
                request_id="cab-1",
                change_type="shutdown-interface",
                target_device="A1",
                target_object="GigabitEthernet0/1",
            )
            prediction = predict_change(
                request,
                output_dir=scope,
                history_root=scope / "history",
                generated_at=(FIXED + timedelta(hours=1)).isoformat(
                    timespec="seconds"
                ),
            )
            # A2 sits behind A1's Gi0/1: the path breaks, CAB recommended.
            self.assertIn("A2", prediction.blast_radius.affected_devices)
            self.assertIn(prediction.risk.level, ("high", "critical"))
            self.assertIn("CAB", prediction.advice.action)
            # History made it into the evidence and the confidence factors.
            self.assertIn("discovery history", prediction.evidence_refs)
            names = {factor.name for factor in prediction.confidence.factors}
            self.assertIn("historical-observations", names)
            self.assertIn("fresh-discovery", names)

    def test_stale_scope_evidence_lowers_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, scope = self.build_scope(workdir)
            request = ChangeRequest(
                request_id="cab-2",
                change_type="shutdown-interface",
                target_device="A1",
                target_object="GigabitEthernet0/1",
            )
            stale = predict_change(
                request,
                output_dir=scope,
                history_root=scope / "history",
                generated_at=(FIXED + timedelta(days=3)).isoformat(
                    timespec="seconds"
                ),
            )
            names = {factor.name for factor in stale.confidence.factors}
            self.assertNotIn("fresh-discovery", names)


class PredictGuiTests(unittest.TestCase):
    def build_world(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        run_discover(workdir, service, network_a(), "Lab A", FIXED)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_predict_page_and_run_produce_a_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_world(workdir)
            page = client.get("/predict?scope=lab-a").data
            self.assertIn(b"Propose a change", page)
            self.assertIn(b"data-picker", page)
            names = {
                item["value"] for item in client.get(
                    "/api/entities?kind=device&scope=lab-a"
                ).get_json()["results"]
            }
            self.assertIn("A1", names)
            response = client.post(
                "/predict/run",
                data={
                    "device": "A1",
                    "interface": "GigabitEthernet0/1",
                    "reason": "port migration",
                    "maintenance_window": "Sat 02:00-04:00",
                    "requester": "netops",
                },
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Risk:", response.data)
            self.assertIn(b"CAB", response.data)
            self.assertIn(b"Blast Radius", response.data)
            self.assertIn(b"Why", response.data)
            scope = scope_dir(workdir, "lab-a")
            self.assertTrue((scope / "prediction_report.json").is_file())
            self.assertTrue((scope / "prediction_report.md").is_file())
            self.assertNotIn(PASSWORD.encode(), response.data)
            report = (scope / "prediction_report.json").read_text("utf-8")
            self.assertNotIn(PASSWORD, report)

    def test_dashboard_shows_the_latest_prediction_panel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_world(workdir)
            client.get("/predict?scope=lab-a")
            client.post(
                "/predict/run",
                data={"device": "A1", "interface": "GigabitEthernet0/1"},
                follow_redirects=True,
            )
            page = client.get("/?scope=lab-a").data
            self.assertIn(b"Latest Prediction", page)
            self.assertIn(b"shutdown-interface: A1 GigabitEthernet0/1", page)
            self.assertIn(b"Recommendation:", page)

    def test_all_networks_scope_predicts_against_the_enterprise(self) -> None:
        """PR-037A: All Networks is the enterprise scope, not a refusal."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            client = self.build_world(workdir)
            page = client.get("/predict?scope=all").data
            self.assertNotIn(b"Select a specific network", page)
            self.assertIn(b"Enterprise scope", page)
            names = {
                item["value"] for item in client.get(
                    "/api/entities?kind=device&scope=all"
                ).get_json()["results"]
            }
            self.assertIn("A1", names)
            response = client.post(
                "/predict/run",
                data={"device": "A1", "interface": "Gi0/1"},
                follow_redirects=True,
            )
            self.assertIn(b"Risk:", response.data)
            self.assertNotIn(PASSWORD.encode(), response.data)


class InterfaceResolutionTests(unittest.TestCase):
    """Canonical interface resolution with deterministic alias handling."""

    INVENTORY = ("GigabitEthernet0/0", "GigabitEthernet0/1", "Loopback0")

    def test_exact_and_case_insensitive_matches(self) -> None:
        self.assertEqual(
            ("GigabitEthernet0/1", None),
            resolve_interface("GigabitEthernet0/1", self.INVENTORY),
        )
        self.assertEqual(
            ("GigabitEthernet0/1", None),
            resolve_interface("gigabitethernet0/1", self.INVENTORY),
        )

    def test_common_aliases_resolve_deterministically(self) -> None:
        for alias in ("Gi0/1", "Gig0/1", "GI0/1", "GigabitEth0/1"):
            canonical, problem = resolve_interface(alias, self.INVENTORY)
            self.assertEqual("GigabitEthernet0/1", canonical, alias)
            self.assertIsNone(problem)

    def test_typos_are_rejected_not_guessed(self) -> None:
        canonical, problem = resolve_interface(
            "GigabitEthenet0/1", self.INVENTORY  # missing 'r'
        )
        self.assertIsNone(canonical)
        self.assertIn("does not match", problem)

    def test_unknown_suffix_is_rejected(self) -> None:
        canonical, problem = resolve_interface("Gi0/9", self.INVENTORY)
        self.assertIsNone(canonical)
        self.assertIn("does not match", problem)

    def test_ambiguous_alias_is_rejected_with_candidates(self) -> None:
        inventory = ("TenGigabitEthernet0/1", "Tunnel0/1")
        canonical, problem = resolve_interface("T0/1", inventory)
        self.assertIsNone(canonical)
        self.assertIn("ambiguous", problem)
        self.assertIn("TenGigabitEthernet0/1", problem)
        self.assertIn("Tunnel0/1", problem)

    def test_empty_inventory_is_a_clean_rejection(self) -> None:
        canonical, problem = resolve_interface("Gi0/1", ())
        self.assertIsNone(canonical)
        self.assertIn("no discovered interfaces", problem)


A2_DISTINCT_BRIEF = (
    "Interface                  IP-Address      OK? Method Status                Protocol\n"
    "FastEthernet0/5            10.0.0.2        YES manual up                    up\n"
)

A2_EMPTY_BRIEF = (
    "Interface                  IP-Address      OK? Method Status                Protocol\n"
)


class PredictValidationGuiTests(unittest.TestCase):
    """Device-aware interface selection with strict server validation."""

    def build_world(self, workdir: Path, *, a2_interfaces: str | None = None):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        run_discover(
            workdir, service,
            network_a(a2_interfaces=a2_interfaces), "Lab A", FIXED,
        )
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def test_dropdown_offers_each_devices_own_interfaces_with_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            page = client.get("/predict?scope=lab-a").data.decode("utf-8")
            # No interface is preloaded into the DOM; the async API serves
            # ONE device's interfaces with the same evidence context the
            # old dropdown carried.
            self.assertNotIn('data-device="A1"', page)
            self.assertNotIn('value="GigabitEthernet0/1"', page)
            results = client.get(
                "/api/device-interfaces?device=A1&scope=lab-a"
            ).get_json()["results"]
            byname = {item["value"]: item["detail"] for item in results}
            self.assertIn("GigabitEthernet0/1", byname)
            self.assertIn("up/up", byname["GigabitEthernet0/1"])
            self.assertIn("connected to A2", byname["GigabitEthernet0/1"])

    def test_dropdown_uses_the_latest_scoped_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.build_world(workdir)
            names = {
                item["value"] for item in client.get(
                    "/api/device-interfaces?device=A2&scope=lab-a"
                ).get_json()["results"]
            }
            self.assertNotIn("FastEthernet0/5", names)
            # A later discovery changes A2's inventory; the API follows.
            run_discover(
                workdir, service,
                network_a(a2_interfaces=A2_DISTINCT_BRIEF), "Lab A",
                FIXED + timedelta(hours=1),
            )
            names = {
                item["value"] for item in client.get(
                    "/api/device-interfaces?device=A2&scope=lab-a"
                ).get_json()["results"]
            }
            self.assertIn("FastEthernet0/5", names)

    def test_interface_of_another_device_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(
                workdir, a2_interfaces=A2_DISTINCT_BRIEF
            )
            client.get("/predict?scope=lab-a")
            response = client.post(
                "/predict/run",
                data={"device": "A1", "interface": "FastEthernet0/5"},
                follow_redirects=True,
            )
            self.assertIn(b"Interface not accepted for A1", response.data)
            scope = scope_dir(workdir, "lab-a")
            self.assertFalse((scope / "prediction_report.json").exists())

    def test_canonical_name_and_alias_both_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/predict?scope=lab-a")
            response = client.post(
                "/predict/run",
                data={"device": "A1", "interface": "Gi0/1"},  # CLI alias
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Risk:", response.data)
            report = json.loads(
                (scope_dir(workdir, "lab-a") / "prediction_report.json")
                .read_text("utf-8")
            )
            # The alias resolved to the canonical Atlas interface name.
            self.assertEqual(
                "GigabitEthernet0/1",
                report["change_request"]["target_object"],
            )

    def test_typo_and_unknown_interface_are_rejected_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/predict?scope=lab-a")
            for bad in ("GigabitEthenet0/1", "Gi0/9"):
                response = client.post(
                    "/predict/run",
                    data={"device": "A1", "interface": bad},
                    follow_redirects=True,
                )
                self.assertIn(b"Interface not accepted", response.data)
            self.assertFalse(
                (scope_dir(workdir, "lab-a") / "prediction_report.json").exists()
            )

    def test_unknown_device_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = self.build_world(Path(tmp))
            client.get("/predict?scope=lab-a")
            response = client.post(
                "/predict/run",
                data={"device": "GHOST", "interface": "Gi0/1"},
                follow_redirects=True,
            )
            self.assertIn(b"not in Lab A", response.data)

    def test_device_without_interfaces_gets_the_run_discovery_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir, a2_interfaces=A2_EMPTY_BRIEF)
            client.get("/predict?scope=lab-a")
            response = client.post(
                "/predict/run",
                data={"device": "A2", "interface": "Gi0/1"},
                follow_redirects=True,
            )
            self.assertIn(
                b"No discovered interfaces are available. Run discovery first.",
                response.data,
            )

    def test_scope_isolation_and_no_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            from founderos_atlas.web import create_app
            from tests.test_profile_isolation import network_b

            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
            add_profile(service, "Lab B", "10.0.1.1")
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B",
                FIXED + timedelta(hours=1),
            )
            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            page = client.get("/predict?scope=lab-b").data.decode("utf-8")
            self.assertNotIn(PASSWORD, page)
            self.assertTrue(client.get(
                "/api/device-interfaces?device=B1&scope=lab-b"
            ).get_json()["results"])
            # Lab A's devices do not resolve from Lab B's scope.
            self.assertEqual([], client.get(
                "/api/device-interfaces?device=A1&scope=lab-b"
            ).get_json()["results"])
            # A1's interface cannot be predicted from Lab B's scope.
            response = client.post(
                "/predict/run",
                data={"device": "A1", "interface": "GigabitEthernet0/1"},
                follow_redirects=True,
            )
            self.assertIn(b"not in Lab B", response.data)


if __name__ == "__main__":
    unittest.main()
