"""Acceptance tests for the PR-034 Enterprise Intelligence Engine.

Deterministic, explainable health scoring; risk/priority/recommendation
engines; trend detection across discoveries; Morning Brief v2 and dashboard
integration — no AI, no randomness, every point accounted for.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.enterprise_intelligence import (
    IntelligenceEvidence,
    build_intelligence,
    prioritize,
    render_intelligence_json,
)
from founderos_atlas.history import DiscoveryRecord

from tests.test_atlas_transport import PASSWORD
from tests.test_profile_isolation import (
    A2_DOWN_BRIEF,
    FIXED,
    add_profile,
    make_service,
    network_a,
    run_discover,
    scope_dir,
)


def snap(devices: tuple[str, ...], edges: tuple[tuple[str, str], ...] = ()) -> dict:
    return {
        "device_count": len(devices),
        "devices": [
            {"device_id": name, "hostname": name} for name in devices
        ],
        "edges": [
            {"local_device_id": a, "remote_hostname": b} for a, b in edges
        ],
    }


def state(changes: list[dict], **overrides) -> dict:
    report = {
        "interfaces_down": sum(
            1 for c in changes if c.get("field") == "protocol" and c.get("event") == "failure"
        ),
        "active_issue_count": sum(
            1 for c in changes if c.get("event") in ("failure", "degradation")
        ),
        "recovery_count": sum(1 for c in changes if c.get("event") == "recovery"),
        "changes": changes,
    }
    report.update(overrides)
    return report


def interface_failure(hostname: str = "R1", interface: str = "Gi0/1") -> dict:
    return {
        "hostname": hostname,
        "interface": interface,
        "field": "protocol",
        "severity": "high",
        "event": "failure",
        "previous_value": "up",
        "current_value": "down",
    }


def make_record(record_id: str, *, failures: tuple[str, ...] = (), devices: int = 2):
    return DiscoveryRecord(
        record_id=record_id,
        started_at="2026-07-09T08:00:00+00:00",
        completed_at="2026-07-09T08:01:00+00:00",
        duration_seconds=60.0,
        device_count=devices,
        relationship_count=1,
        warning_count=0,
        failures=failures,
        configuration_status="not_requested",
        configured_device_count=0,
        quality_score=1.0,
        network_status="Healthy",
        snapshot_id="atlas-topology:" + "0" * 64,
    )


def evidence(**overrides) -> IntelligenceEvidence:
    defaults: dict = {
        "generated_at": "2026-07-10T08:00:00+00:00",
        "last_completed_at": "2026-07-10T08:00:00+00:00",
        "baseline_available": True,
        "snapshot": snap(("R1", "SW1")),
    }
    defaults.update(overrides)
    return IntelligenceEvidence(**defaults)


class HealthScoringTests(unittest.TestCase):
    def test_perfect_network_scores_100_with_stability_credit(self) -> None:
        health = build_intelligence(
            evidence(topology_report={"change_count": 0, "severity_counts": {}})
        ).health
        self.assertEqual(100, health.score)  # clamped: 100 + stability credit
        self.assertIn(
            "topology-stable", [factor.name for factor in health.factors]
        )

    def test_every_point_is_documented(self) -> None:
        intelligence = build_intelligence(
            evidence(
                state_report=state([interface_failure()]),
                failed_hosts=("10.0.0.9",),
                failed_details=(("10.0.0.9", "Connection to 10.0.0.9 timed out."),),
                topology_report={"change_count": 2, "severity_counts": {"high": 1}},
            )
        )
        health = intelligence.health
        raw = 100 + sum(factor.points for factor in health.factors)
        self.assertEqual(health.score, max(0, min(100, raw)))
        names = {factor.name for factor in health.factors}
        self.assertIn("interface-failures", names)
        self.assertIn("unreachable-devices", names)
        self.assertIn("high-severity-topology-changes", names)
        for factor in health.factors:
            self.assertTrue(factor.detail)  # every factor explains itself

    def test_deductions_are_capped(self) -> None:
        many = [interface_failure("R1", f"Gi0/{n}") for n in range(10)]
        health = build_intelligence(
            evidence(state_report=state(many))
        ).health
        interface_factor = next(
            factor for factor in health.factors if factor.name == "interface-failures"
        )
        self.assertEqual(-24, interface_factor.points)  # capped, not -80

    def test_authentication_failures_are_classified_separately(self) -> None:
        health = build_intelligence(
            evidence(
                failed_hosts=("10.0.0.8", "10.0.0.9"),
                failed_details=(
                    ("10.0.0.8", "Authentication failed for 10.0.0.8."),
                    ("10.0.0.9", "Connection to 10.0.0.9 timed out."),
                ),
            )
        ).health
        by_name = {factor.name: factor for factor in health.factors}
        self.assertEqual(-8, by_name["authentication-failures"].points)
        self.assertEqual(-6, by_name["unreachable-devices"].points)

    def test_recovery_earns_a_credit(self) -> None:
        health = build_intelligence(
            evidence(state_report=state([], recovery_count=1))
        ).health
        self.assertIn(
            "recovered-devices", [factor.name for factor in health.factors]
        )

    def test_confidence_reflects_evidence_quality(self) -> None:
        self.assertEqual(
            "high", build_intelligence(evidence()).health.confidence
        )
        self.assertEqual(
            "medium",
            build_intelligence(evidence(baseline_available=False)).health.confidence,
        )
        stale = evidence(
            generated_at="2026-07-12T08:00:00+00:00",
            last_completed_at="2026-07-10T08:00:00+00:00",
        )
        intelligence = build_intelligence(stale)
        self.assertEqual("low", intelligence.health.confidence)
        self.assertIn(
            "stale-discovery",
            [factor.name for factor in intelligence.health.factors],
        )

    def test_intelligence_is_deterministic(self) -> None:
        source = evidence(
            state_report=state([interface_failure()]),
            failed_hosts=("10.0.0.9",),
            failed_details=(("10.0.0.9", "timed out"),),
        )
        first = build_intelligence(source)
        second = build_intelligence(source)
        self.assertEqual(
            render_intelligence_json(first), render_intelligence_json(second)
        )


class RiskAndPriorityTests(unittest.TestCase):
    def test_interface_failure_finding_is_fully_classified(self) -> None:
        hub_snapshot = snap(
            ("R1", "SW1", "SW2", "SW3"),
            edges=(("R1", "SW1"), ("R1", "SW2"), ("R1", "SW3")),
        )
        intelligence = build_intelligence(
            evidence(snapshot=hub_snapshot, state_report=state([interface_failure("R1")]))
        )
        finding = next(
            f for f in intelligence.findings if f.category == "interface-failure"
        )
        self.assertEqual("high", finding.severity)
        self.assertEqual("high", finding.risk)  # 3 neighbors = high blast radius
        self.assertEqual("high", finding.confidence)
        self.assertEqual("immediate", finding.urgency)
        self.assertEqual(3, finding.blast_radius)

    def test_authentication_failure_is_immediate(self) -> None:
        intelligence = build_intelligence(
            evidence(
                failed_hosts=("10.0.0.8",),
                failed_details=(("10.0.0.8", "Authentication failed for 10.0.0.8."),),
            )
        )
        finding = next(
            f for f in intelligence.findings if f.category == "authentication-failure"
        )
        self.assertEqual("immediate", finding.urgency)
        self.assertEqual("high", finding.severity)

    def test_removed_device_risk_uses_previous_topology(self) -> None:
        previous = snap(
            ("R9", "SW1", "SW2", "SW3"),
            edges=(("R9", "SW1"), ("R9", "SW2"), ("R9", "SW3")),
        )
        intelligence = build_intelligence(
            evidence(
                previous_snapshot=previous,
                topology_report={
                    "change_count": 1,
                    "severity_counts": {"high": 1},
                    "removed_devices": ["R9"],
                },
            )
        )
        finding = next(
            f for f in intelligence.findings if f.category == "device-removed"
        )
        self.assertEqual("high", finding.risk)
        self.assertEqual(3, finding.blast_radius)

    def test_priorities_rank_immediate_above_scheduled(self) -> None:
        intelligence = build_intelligence(
            evidence(
                state_report=state([interface_failure("R1")]),
                config_report={
                    "change_count": 1,
                    "devices_changed": 1,
                    "severity_counts": {},
                    "reports": [
                        {"hostname": "SW1", "change_count": 1, "severity_counts": {}}
                    ],
                },
            )
        )
        self.assertEqual("interface-failure", intelligence.priorities[0].category)
        # Everything is present but ranked, never listed equally.
        self.assertGreater(len(intelligence.priorities), 1)

    def test_priority_queue_is_bounded_to_five_and_deterministic(self) -> None:
        many = [interface_failure("R1", f"Gi0/{n}") for n in range(7)]
        source = evidence(state_report=state(many))
        first = build_intelligence(source)
        second = build_intelligence(source)
        self.assertEqual(5, len(first.priorities))
        self.assertEqual(
            [f.finding_id for f in first.priorities],
            [f.finding_id for f in second.priorities],
        )
        self.assertEqual(prioritize(first.findings), first.priorities)


class RecommendationTests(unittest.TestCase):
    def test_interface_failure_with_config_change_points_at_the_change(self) -> None:
        intelligence = build_intelligence(
            evidence(
                snapshot=snap(("R1", "SW1"), edges=(("R1", "SW1"),)),
                state_report=state([interface_failure("R1")]),
                config_report={
                    "change_count": 2,
                    "devices_changed": 1,
                    "severity_counts": {},
                    "reports": [
                        {"hostname": "R1", "change_count": 2, "severity_counts": {}}
                    ],
                },
            )
        )
        recommendation = intelligence.recommendations[0]
        self.assertIn("configuration", recommendation.likely_cause.casefold())
        self.assertIn("compare", recommendation.next_step.casefold())
        self.assertIn("neighbor", recommendation.impact)
        self.assertEqual(
            recommendation.next_step, intelligence.suggested_investigation
        )

    def test_interface_failure_without_config_change_points_at_hardware(self) -> None:
        intelligence = build_intelligence(
            evidence(state_report=state([interface_failure("R1")]))
        )
        recommendation = intelligence.recommendations[0]
        self.assertIn("cable", recommendation.likely_cause.casefold())
        self.assertIn("physical link", recommendation.next_step.casefold())

    def test_authentication_failure_recommends_credential_fix(self) -> None:
        intelligence = build_intelligence(
            evidence(
                failed_hosts=("10.0.0.8",),
                failed_details=(("10.0.0.8", "Authentication failed for 10.0.0.8."),),
            )
        )
        recommendation = intelligence.recommendations[0]
        self.assertIn("credential", recommendation.next_step.casefold())


class TrendTests(unittest.TestCase):
    def previous(self, score: int, config_changes: int = 0) -> dict:
        return {
            "health": {"score": score, "factors": []},
            "basis": {"config_change_count": config_changes},
        }

    def test_health_trend_directions(self) -> None:
        improving = build_intelligence(
            evidence(previous_intelligence=self.previous(90))
        )
        self.assertEqual("improving", improving.trend)
        declining = build_intelligence(
            evidence(
                state_report=state(
                    [interface_failure("R1"), interface_failure("SW1", "Gi0/2")]
                ),
                previous_intelligence=self.previous(100),
            )
        )
        self.assertEqual("declining", declining.trend)
        stable = build_intelligence(
            evidence(previous_intelligence=self.previous(99))
        )
        self.assertEqual("stable", stable.trend)
        baseline = build_intelligence(evidence(baseline_available=False))
        self.assertEqual("baseline", baseline.trend)

    def test_configuration_churn_trend(self) -> None:
        intelligence = build_intelligence(
            evidence(
                config_report={
                    "change_count": 5,
                    "devices_changed": 1,
                    "severity_counts": {},
                    "reports": [
                        {"hostname": "R1", "change_count": 5, "severity_counts": {}}
                    ],
                },
                previous_intelligence=self.previous(100, config_changes=1),
            )
        )
        churn = next(s for s in intelligence.trends if s.name == "configuration-churn")
        self.assertEqual("declining", churn.direction)
        self.assertIn("rose from 1 to 5", churn.detail)

    def test_recurring_instability_is_a_trend_and_a_health_factor(self) -> None:
        records = (
            make_record("run-3", failures=("10.0.0.9",)),
            make_record("run-2", failures=("10.0.0.9",)),
            make_record("run-1"),
        )
        intelligence = build_intelligence(
            evidence(
                recent_records=records,
                failed_hosts=("10.0.0.9",),
                failed_details=(("10.0.0.9", "Connection to 10.0.0.9 timed out."),),
            )
        )
        instability = next(
            s for s in intelligence.trends if s.name == "link-instability"
        )
        self.assertEqual("declining", instability.direction)
        self.assertIn(
            "repeated-instability",
            [factor.name for factor in intelligence.health.factors],
        )
        finding = next(
            f for f in intelligence.findings if f.category == "discovery-failure"
        )
        self.assertTrue(finding.recurring)

    def test_historical_comparison_names_improvement_and_regression(self) -> None:
        previous = {
            "health": {
                "score": 92,
                "factors": [
                    {"name": "interface-failures", "points": -8, "detail": "1 down"}
                ],
            },
            "basis": {"config_change_count": 0},
        }
        intelligence = build_intelligence(
            evidence(
                failed_hosts=("10.0.0.9",),
                failed_details=(("10.0.0.9", "timed out"),),
                previous_intelligence=previous,
            )
        )
        self.assertIn("interface-failures", intelligence.biggest_improvement)
        self.assertIn("unreachable-devices", intelligence.biggest_regression)


class PipelineIntegrationTests(unittest.TestCase):
    """End to end: the pipeline produces and archives intelligence."""

    def run_lab(self, workdir: Path, service, network, start):
        return run_discover(workdir, service, network, "Lab A", start)

    def test_discovery_produces_explained_intelligence_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
            self.run_lab(workdir, service, network_a(), FIXED)
            code, out, err = self.run_lab(
                workdir, service,
                network_a(a2_interfaces=A2_DOWN_BRIEF),
                FIXED + timedelta(hours=1),
            )
            self.assertEqual(0, code, err)
            self.assertIn("Intelligence: health", out)
            scope = scope_dir(workdir, "lab-a")
            report = json.loads(
                (scope / "intelligence_report.json").read_text("utf-8")
            )
            self.assertLess(report["health"]["score"], 100)
            factor_names = {f["name"] for f in report["health"]["factors"]}
            self.assertIn("interface-failures", factor_names)
            self.assertTrue(report["priorities"])
            self.assertEqual(
                "interface-failure", report["priorities"][0]["category"]
            )
            self.assertTrue(report["recommendations"])
            # Morning Brief v2 carries the intelligence sections.
            brief = (scope / "morning_brief.md").read_text("utf-8")
            for section in (
                "## Enterprise Intelligence",
                "Enterprise Health",
                "### Top Risks",
                "### Top Recommendations",
                "### Changes Since Yesterday",
                "### Suggested Investigation",
            ):
                self.assertIn(section, brief)
            # Dashboard shows the calculated health.
            dashboard = (scope / "dashboard.html").read_text("utf-8")
            self.assertIn("Enterprise Health", dashboard)
            self.assertIn(f"{report['health']['score']}/100", dashboard)
            # Archived with the run so future trends can compare.
            from founderos_atlas.history import HistoryRepository

            repository = HistoryRepository(scope / "history")
            record = repository.load().records[0]
            record_dir = repository.record_directory(record.record_id)
            self.assertTrue((record_dir / "intelligence_report.json").is_file())
            self.assertTrue((record_dir / "intelligence_report.md").is_file())

    def test_recovery_turns_the_trend_around(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
            self.run_lab(workdir, service, network_a(), FIXED)
            self.run_lab(
                workdir, service,
                network_a(a2_interfaces=A2_DOWN_BRIEF),
                FIXED + timedelta(hours=1),
            )
            code, out, err = self.run_lab(
                workdir, service, network_a(), FIXED + timedelta(hours=2)
            )
            self.assertEqual(0, code, err)
            scope = scope_dir(workdir, "lab-a")
            report = json.loads(
                (scope / "intelligence_report.json").read_text("utf-8")
            )
            self.assertEqual("improving", report["trend"])
            self.assertIsNotNone(report["previous_score"])
            self.assertGreater(
                report["health"]["score"], report["previous_score"]
            )
            self.assertIn("interface-failures", report["biggest_improvement"])
            factor_names = {f["name"] for f in report["health"]["factors"]}
            self.assertIn("recovered-devices", factor_names)

    def test_no_secret_reaches_intelligence_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
            self.run_lab(workdir, service, network_a(), FIXED)
            scope = scope_dir(workdir, "lab-a")
            for name in ("intelligence_report.json", "intelligence_report.md"):
                self.assertNotIn(
                    PASSWORD, (scope / name).read_text("utf-8")
                )

    def test_web_dashboard_shows_enterprise_health(self) -> None:
        from founderos_atlas.web import create_app

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
            self.run_lab(workdir, service, network_a(), FIXED)
            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                # Isolate from the real operator workspace (and its
                # single-instance lock).
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            page = client.get("/?scope=lab-a").data
            self.assertIn(b"Enterprise Health", page)
            self.assertIn(b"Top Risks", page)
            self.assertIn(b"Top Recommendations", page)
            # All Networks: per-network health column.
            page = client.get("/?scope=all").data
            self.assertIn(b"Health", page)
            self.assertIn(b"/100", page)


if __name__ == "__main__":
    unittest.main()
