"""Acceptance tests for the PR-035 evidence-based Root Cause Analysis engine.

Deterministic reasoning: timeline ordering, correlation of related (and only
related) evidence, banded confidence that never reaches 100%, competing
hypotheses with contradicting evidence, historical replay, and integration
with incidents, the dashboard, and the Morning Brief.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.root_cause import (
    analyze,
    analyze_record,
    render_root_cause_json,
    root_cause_brief_section,
    root_cause_incident_section,
)
from founderos_atlas.root_cause.confidence import band, calculate

from tests.test_atlas_transport import PASSWORD
from tests.test_config_collection import RUNNING_CONFIG
from tests.test_enterprise_intelligence import interface_failure, snap, state
from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_profile_isolation import (
    A2_DOWN_BRIEF,
    FIXED,
    add_profile,
    make_service,
    run_discover,
    scope_dir,
)
from tests.test_unified_pipeline import full_outputs


NOW = "2026-07-10T08:00:00+00:00"


def config_report(hostname: str = "R1", *, lines: tuple[str, ...] = ()) -> dict:
    return {
        "change_count": 1,
        "devices_changed": 1,
        "severity_counts": {"high": 0, "medium": 1, "low": 0},
        "reports": [
            {
                "hostname": hostname,
                "change_count": 1,
                "severity_counts": {"medium": 1},
                "changes": [
                    {
                        "category": "interfaces",
                        "severity": "medium",
                        "summary": f"Interface configuration changed on {hostname}",
                        "added_lines": list(lines),
                        "removed_lines": [],
                    }
                ],
            }
        ],
    }


class ConfidenceTests(unittest.TestCase):
    def test_confidence_is_documented_arithmetic(self) -> None:
        self.assertAlmostEqual(
            0.6 + 0.08 * 2 + 0.15, calculate(0.6, supporting=2, interface_match=True)
        )

    def test_confidence_never_reaches_100_percent(self) -> None:
        self.assertEqual(0.95, calculate(0.9, supporting=3, interface_match=True))

    def test_contradictions_lower_confidence(self) -> None:
        clean = calculate(0.55, supporting=1)
        contradicted = calculate(0.55, supporting=1, contradicting=2)
        self.assertLess(contradicted, clean)

    def test_bands(self) -> None:
        self.assertEqual("very-high", band(0.93))
        self.assertEqual("high", band(0.80))
        self.assertEqual("medium", band(0.55))
        self.assertEqual("low", band(0.30))


class TimelineAndCorrelationTests(unittest.TestCase):
    def test_timeline_orders_by_time_then_causal_rank(self) -> None:
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report("R1", lines=("interface GigabitEthernet0/1", " shutdown")),
            topology_report={"removed_devices": ["SW9"], "change_count": 1},
        )
        categories = [event.category for event in report.timeline]
        # configuration precedes interface precedes protocol precedes topology.
        self.assertLess(
            categories.index("configuration"), categories.index("protocol")
        )
        self.assertLess(categories.index("protocol"), categories.index("topology"))

    def test_related_evidence_is_correlated(self) -> None:
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report(
                "R1", lines=("interface GigabitEthernet0/1", " shutdown")
            ),
        )
        analysis = report.analyses[0]
        self.assertEqual("configuration-change", analysis.primary.kind)
        self.assertIn("config:R1:0", analysis.primary.supporting)
        # The reasoning chain walks configuration -> interface effect.
        self.assertIn("config:R1:0", analysis.reasoning[0])
        self.assertTrue(any("Gi0/1" in line for line in analysis.reasoning))

    def test_unrelated_evidence_is_not_correlated(self) -> None:
        # Config change on SW7; failure on R1: different devices, no link.
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report("SW7"),
        )
        analysis = report.analyses[0]
        self.assertNotEqual("configuration-change", analysis.primary.kind)
        self.assertNotIn("config:SW7:0", analysis.primary.supporting)

    def test_downstream_removal_correlates_only_via_real_adjacency(self) -> None:
        previous = snap(("R1", "SW9"), edges=(("R1", "SW9"),))
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            topology_report={"removed_devices": ["SW9", "FAR7"], "change_count": 2},
            previous_snapshot=previous,
        )
        by_subject = {a.subject: a for a in report.analyses}
        self.assertEqual(
            "upstream-isolation", by_subject["SW9"].primary.kind
        )  # was adjacent to the failing device
        self.assertNotEqual(
            "upstream-isolation", by_subject["FAR7"].primary.kind
        )  # never adjacent: not blamed on R1


class HypothesisTests(unittest.TestCase):
    def test_multiple_hypotheses_are_generated_and_ranked(self) -> None:
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report(
                "R1", lines=("interface GigabitEthernet0/1", " shutdown")
            ),
        )
        analysis = report.analyses[0]
        kinds = [analysis.primary.kind] + [h.kind for h in analysis.alternatives]
        self.assertIn("configuration-change", kinds)
        self.assertIn("physical-failure", kinds)
        self.assertEqual("configuration-change", kinds[0])
        confidences = [analysis.primary.confidence] + [
            h.confidence for h in analysis.alternatives
        ]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_conflicting_evidence_is_recorded_against_the_loser(self) -> None:
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report(
                "R1", lines=("interface GigabitEthernet0/1", " shutdown")
            ),
        )
        physical = next(
            h
            for h in report.analyses[0].alternatives
            if h.kind == "physical-failure"
        )
        # The configuration change contradicts the hardware explanation.
        self.assertIn("config:R1:0", physical.contradicting)
        self.assertLess(physical.confidence, report.analyses[0].primary.confidence)

    def test_no_config_evidence_makes_physical_the_primary(self) -> None:
        report = analyze(
            generated_at=NOW, state_report=state([interface_failure("R1")])
        )
        self.assertEqual("physical-failure", report.analyses[0].primary.kind)

    def test_admin_down_without_config_suggests_deliberate_action(self) -> None:
        changes = [
            {
                "hostname": "R1",
                "interface": "Gi0/1",
                "field": "status",
                "severity": "medium",
                "event": "degradation",
                "previous_value": "up",
                "current_value": "administratively_down",
            }
        ]
        report = analyze(generated_at=NOW, state_report=state(changes))
        kinds = {report.analyses[0].primary.kind} | {
            h.kind for h in report.analyses[0].alternatives
        }
        self.assertIn("deliberate-shutdown", kinds)

    def test_authentication_failures_get_a_credential_hypothesis(self) -> None:
        report = analyze(
            generated_at=NOW,
            failed_details=(
                ("10.0.0.9", "Authentication failed for 10.0.0.9."),
            ),
        )
        primary = report.analyses[0].primary
        self.assertEqual("authentication-issue", primary.kind)
        self.assertEqual("high", primary.band)
        self.assertIn("credential", primary.next_step.casefold())

    def test_lonely_removed_device_keeps_maintenance_as_alternative(self) -> None:
        report = analyze(
            generated_at=NOW,
            topology_report={"removed_devices": ["SW9"], "change_count": 1},
        )
        analysis = report.analyses[0]
        self.assertEqual("device-down", analysis.primary.kind)
        self.assertIn(
            "expected-maintenance", [h.kind for h in analysis.alternatives]
        )

    def test_same_evidence_same_explanation_byte_for_byte(self) -> None:
        kwargs = dict(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report(
                "R1", lines=("interface GigabitEthernet0/1", " shutdown")
            ),
            topology_report={"removed_devices": ["SW9"], "change_count": 1},
        )
        self.assertEqual(
            render_root_cause_json(analyze(**kwargs)),
            render_root_cause_json(analyze(**kwargs)),
        )

    def test_every_conclusion_references_evidence(self) -> None:
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report(
                "R1", lines=("interface GigabitEthernet0/1", " shutdown")
            ),
        )
        for analysis in report.analyses:
            self.assertTrue(analysis.primary.supporting)
            self.assertTrue(analysis.evidence_ids)
            self.assertTrue(
                any("[" in line and "]" in line for line in analysis.reasoning)
            )


class PipelineIntegrationTests(unittest.TestCase):
    """The config-shutdown scenario, end to end through the real pipeline."""

    def shut_config(self, hostname: str) -> str:
        return RUNNING_CONFIG.replace("R1", hostname).replace(
            "!\r\nend",
            "!\r\ninterface GigabitEthernet0/1\r\n shutdown\r\n!\r\nend",
        )

    def network(self, *, shut: bool) -> ScriptedNetwork:
        a2 = full_outputs(
            "A2", "10.0.0.2", (("A1", "10.0.0.1"),),
            running_config=self.shut_config("A2") if shut else None,
            interfaces_brief=A2_DOWN_BRIEF if shut else None,
        )
        return ScriptedNetwork(
            {
                "10.0.0.1": full_outputs("A1", "10.0.0.1", (("A2", "10.0.0.2"),)),
                "10.0.0.2": a2,
            }
        )

    def build_world(self, workdir: Path):
        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1", collect_configuration=True)
        run_discover(workdir, service, self.network(shut=False), "Lab A", FIXED)
        code, out, err = run_discover(
            workdir, service, self.network(shut=True), "Lab A",
            FIXED + timedelta(hours=1),
        )
        return service, code, out, err

    def test_pipeline_explains_the_config_caused_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, code, out, err = self.build_world(workdir)
            self.assertEqual(0, code, err)
            self.assertIn("Root cause:", out)
            scope = scope_dir(workdir, "lab-a")
            report = json.loads(
                (scope / "root_cause_report.json").read_text("utf-8")
            )
            most = report["most_important"]
            self.assertEqual("configuration-change", most["primary"]["kind"])
            self.assertIn(most["primary"]["band"], ("high", "very-high"))
            self.assertLess(most["primary"]["confidence_percent"], 100)
            self.assertIn("A2", most["primary"]["statement"])
            self.assertTrue(most["primary"]["supporting"])
            self.assertTrue(most["reasoning"])
            # Timeline leads with the configuration change.
            self.assertEqual(
                "configuration", report["timeline"][0]["category"]
            )
            # Morning Brief carries the most important root cause.
            brief = (scope / "morning_brief.md").read_text("utf-8")
            self.assertIn("### Most Important Root Cause", brief)
            self.assertIn("configuration change", brief.casefold())
            # Dashboard leads with the explanation, not the raw alarm.
            dashboard = (scope / "dashboard.html").read_text("utf-8")
            self.assertIn("Most Likely Root Cause", dashboard)
            # Archived for historical replay.
            from founderos_atlas.history import HistoryRepository

            repository = HistoryRepository(scope / "history")
            record = repository.load().records[0]
            record_dir = repository.record_directory(record.record_id)
            self.assertTrue((record_dir / "root_cause_report.json").is_file())
            self.assertNotIn(
                PASSWORD, (scope / "root_cause_report.json").read_text("utf-8")
            )

    def test_historical_replay_reproduces_the_stored_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, code, _, err = self.build_world(workdir)
            self.assertEqual(0, code, err)
            scope = scope_dir(workdir, "lab-a")
            from founderos_atlas.history import HistoryRepository

            record = HistoryRepository(scope / "history").load().records[0]
            replayed = analyze_record(scope / "history", record.record_id)
            stored = (scope / "root_cause_report.json").read_text("utf-8")
            # "What happened yesterday?" — the stored evidence reproduces
            # the stored explanation, byte for byte.
            self.assertEqual(stored, render_root_cause_json(replayed))

    def test_investigations_carry_the_root_cause_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, code, _, err = self.build_world(workdir)
            self.assertEqual(0, code, err)
            from founderos_atlas.web import create_app

            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            client.get("/incidents?scope=lab-a")
            response = client.post(
                "/incidents/run",
                data={"title": "Users behind A2 offline", "description": "x"},
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            markdown = (
                scope_dir(workdir, "lab-a") / "incident_report.md"
            ).read_text("utf-8")
            self.assertIn("## Root Cause Analysis", markdown)
            self.assertIn("Likely cause", markdown)
            self.assertIn("Recommended next step", markdown)
            # The incidents page shows the analysis card.
            page = client.get("/incidents?scope=lab-a").data
            self.assertIn(b"Root Cause Analysis", page)
            self.assertIn(b"Likely cause", page)
            # The dashboard shows the most likely root cause card.
            page = client.get("/?scope=lab-a").data
            self.assertIn(b"Most Likely Root Cause", page)

    def test_brief_and_incident_sections_render_from_reports(self) -> None:
        report = analyze(
            generated_at=NOW,
            state_report=state([interface_failure("R1")]),
            config_report=config_report(
                "R1", lines=("interface GigabitEthernet0/1", " shutdown")
            ),
        )
        brief_section = root_cause_brief_section(report)
        self.assertIn("### Most Important Root Cause", brief_section)
        self.assertIn("Confidence:", brief_section)
        incident_section = root_cause_incident_section(report.to_dict())
        self.assertIn("## Root Cause Analysis", incident_section)
        self.assertIn("Supporting Evidence", incident_section)
        # An empty report renders nothing rather than noise.
        empty = analyze(generated_at=NOW)
        self.assertEqual("", root_cause_brief_section(empty))
        self.assertEqual("", root_cause_incident_section(empty.to_dict()))


if __name__ == "__main__":
    unittest.main()
