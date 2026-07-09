"""Acceptance tests for PR-027 incident investigation."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from founderos_atlas.dashboard import build_dashboard_summary
from founderos_atlas.incidents import (
    IncidentArtifacts,
    IncidentInvestigator,
    NO_CONFIG_CHANGE_EVIDENCE,
    NO_TOPOLOGY_CHANGE_EVIDENCE,
    render_incident_report_json,
    render_incident_report_markdown,
)
from founderos_runtime.cli import main

from tests.test_change_intelligence import device_entry, edge_entry, snapshot_dict
from tests.test_dashboard import summary_kwargs


def sample_snapshot() -> dict:
    r1 = device_entry("R1", "10.0.0.1")
    r1["metadata"] = {"identity": {"aliases": ["R1.atlas.local"]}}
    return snapshot_dict(
        [r1, device_entry("SW1", "10.0.0.2")],
        [edge_entry("cisco-ios:r1", "SW1")],
        snapshot_id="atlas-topology:incident-test",
    )


def sample_change_report() -> dict:
    return {
        "change_count": 1,
        "severity_counts": {"high": 0, "medium": 1, "low": 0, "info": 0},
        "changes": [
            {
                "category": "neighbor",
                "severity": "medium",
                "description": "R1 lost neighbor SW1",
                "recommendation": "Verify physical connectivity or CDP between R1 and SW1.",
                "subject": "R1",
            }
        ],
    }


def sample_config_report() -> dict:
    return {
        "hostname": "SW1",
        "change_count": 1,
        "severity_counts": {"high": 1, "medium": 0, "low": 0},
        "changes": [
            {
                "hostname": "SW1",
                "category": "interfaces",
                "severity": "high",
                "summary": "SW1: interface GigabitEthernet0/0 changed (1 added, 1 removed line(s))",
            }
        ],
    }


class IncidentInvestigatorTests(unittest.TestCase):
    def investigate(self, description="R1 lost connectivity to SW1", **artifact_kwargs):
        artifacts = IncidentArtifacts(**artifact_kwargs)
        return IncidentInvestigator().investigate(
            "Connectivity incident",
            description,
            artifacts,
            generated_at="2026-07-09T23:41:18+00:00",
        )

    def test_topology_only_is_honest_about_missing_change_evidence(self) -> None:
        report = self.investigate(snapshot=sample_snapshot())
        self.assertEqual(("R1", "SW1"), report.affected_devices)
        self.assertIn(NO_TOPOLOGY_CHANGE_EVIDENCE, report.limitations)
        self.assertIn(NO_CONFIG_CHANGE_EVIDENCE, report.limitations)
        self.assertEqual("medium", report.confidence)
        statements = [item.statement for item in report.evidence]
        self.assertIn(NO_TOPOLOGY_CHANGE_EVIDENCE, statements)
        self.assertIn(NO_CONFIG_CHANGE_EVIDENCE, statements)
        self.assertTrue(
            any("R1 is connected to SW1" in line for line in report.topology_context)
        )

    def test_config_change_report_feeds_evidence_and_confidence(self) -> None:
        report = self.investigate(
            snapshot=sample_snapshot(),
            change_report=sample_change_report(),
            config_change_report=sample_config_report(),
        )
        self.assertEqual("high", report.confidence)
        self.assertTrue(
            any("R1 lost neighbor SW1" in item for item in report.possible_related_changes)
        )
        self.assertTrue(
            any("configuration" in item for item in report.possible_related_changes)
        )
        self.assertTrue(
            any("Latest configuration change report for SW1" in line
                for line in report.configuration_context)
        )
        self.assertNotIn(NO_CONFIG_CHANGE_EVIDENCE, report.limitations)

    def test_missing_all_artifacts_is_low_confidence_and_honest(self) -> None:
        report = self.investigate()
        self.assertEqual((), report.affected_devices)
        self.assertEqual("low", report.confidence)
        self.assertIn(NO_TOPOLOGY_CHANGE_EVIDENCE, report.limitations)
        self.assertIn(NO_CONFIG_CHANGE_EVIDENCE, report.limitations)
        self.assertTrue(
            any("No topology snapshot is available" in line for line in report.limitations)
        )
        self.assertEqual((), report.topology_context)

    def test_affected_device_detection_by_hostname_and_alias(self) -> None:
        report = self.investigate(
            description="Users behind sw1 report slowness", snapshot=sample_snapshot()
        )
        self.assertEqual(("SW1",), report.affected_devices)
        alias_report = self.investigate(
            description="R1.atlas.local is flapping", snapshot=sample_snapshot()
        )
        self.assertEqual(("R1",), alias_report.affected_devices)

    def test_affected_device_detection_by_ip(self) -> None:
        report = self.investigate(
            description="Host 10.0.0.2 is unreachable from the WAN",
            snapshot=sample_snapshot(),
        )
        self.assertEqual(("SW1",), report.affected_devices)

    def test_keyword_driven_steps_match_spec_example(self) -> None:
        report = self.investigate(
            description="VLAN 10 cannot access internet", snapshot=sample_snapshot()
        )
        steps = " | ".join(report.investigation_steps)
        self.assertIn("Verify VLAN 10 exists", steps)
        self.assertIn("trunk links", steps)
        self.assertIn("default gateway", steps)
        self.assertIn("Review recent configuration changes", steps)

    def test_deterministic_recommendations_and_incident_id(self) -> None:
        first = self.investigate(snapshot=sample_snapshot())
        second = self.investigate(snapshot=sample_snapshot())
        self.assertEqual(first, second)
        self.assertEqual(first.incident_id, second.incident_id)
        self.assertTrue(first.incident_id.startswith("INC-"))
        self.assertEqual(first.recommendations, second.recommendations)

    def test_facts_are_never_invented(self) -> None:
        # Without a change report, no change statements may appear anywhere.
        report = self.investigate(snapshot=sample_snapshot())
        self.assertEqual((), report.possible_related_changes)
        change_sources = {item.source for item in report.evidence}
        self.assertNotIn("change_report", change_sources)
        self.assertNotIn("config_change_report", change_sources)


class IncidentReportRenderingTests(unittest.TestCase):
    def build_report(self):
        return IncidentInvestigator().investigate(
            "VLAN 10 outage",
            "VLAN 10 cannot access internet",
            IncidentArtifacts(snapshot=sample_snapshot()),
            generated_at="2026-07-09T23:41:18+00:00",
        )

    def test_json_generation(self) -> None:
        data = json.loads(render_incident_report_json(self.build_report()))
        for field in (
            "incident_id", "title", "description", "generated_at",
            "affected_devices", "possible_related_changes", "topology_context",
            "configuration_context", "investigation_steps", "evidence",
            "confidence", "recommendations", "limitations",
        ):
            self.assertIn(field, data)
        self.assertEqual("VLAN 10 outage", data["title"])
        self.assertEqual("medium", data["confidence"])
        self.assertTrue(all("statement" in item and "source" in item for item in data["evidence"]))

    def test_markdown_generation(self) -> None:
        markdown = render_incident_report_markdown(self.build_report())
        for heading in (
            "# Atlas Incident Investigation", "## Affected Devices",
            "## Topology Context", "## Possible Related Changes",
            "## Configuration Context", "## Evidence", "## Investigation Steps",
            "## Recommendations", "## Limitations",
        ):
            self.assertIn(heading, markdown)
        self.assertIn("Confidence: Medium", markdown)
        self.assertIn(NO_TOPOLOGY_CHANGE_EVIDENCE, markdown)
        self.assertIn(NO_CONFIG_CHANGE_EVIDENCE, markdown)

    def test_no_ai_dependency(self) -> None:
        package_root = (
            Path(__file__).resolve().parents[1]
            / "src" / "founderos_atlas" / "incidents"
        )
        forbidden = ("openai", "anthropic", "langchain", "llm", "transformers")
        for source_file in package_root.glob("*.py"):
            content = source_file.read_text(encoding="utf-8").casefold()
            for term in forbidden:
                self.assertNotIn(term, content, f"{source_file.name} references {term}")

    def test_no_network_access(self) -> None:
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            report = self.build_report()
        self.assertEqual("medium", report.confidence)


class InvestigateCliTests(unittest.TestCase):
    def invoke(self, workdir: Path, answers: tuple[str, str]):
        replies = iter(answers)
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                ["atlas", "investigate"],
                atlas_input_reader=lambda prompt: next(replies, ""),
                atlas_clock=lambda: datetime(2026, 7, 9, 23, 41, 18, tzinfo=timezone.utc),
                atlas_snapshot_output=workdir / "topology_snapshot.json",
                atlas_compare_json_output=workdir / "change_report.json",
                atlas_config_diff_json_output=workdir / "config_change_report.json",
                atlas_morning_brief_output=workdir / "morning_brief.md",
                atlas_config_output_dir=workdir / "configs",
                atlas_history_root=workdir / ".atlas" / "history",
                atlas_incident_json_output=workdir / "incident_report.json",
                atlas_incident_markdown_output=workdir / "incident_report.md",
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_flow_generates_reports_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "topology_snapshot.json").write_text(
                json.dumps(sample_snapshot()), encoding="utf-8"
            )
            code, output, error = self.invoke(
                workdir, ("VLAN 10 outage", "VLAN 10 cannot access internet via R1")
            )
            self.assertEqual(0, code, error)
            self.assertIn("Atlas Incident Investigation", output)
            self.assertIn("Incident: VLAN 10 outage", output)
            self.assertIn("- R1", output)
            self.assertIn("Confidence: Medium", output)
            self.assertIn(NO_TOPOLOGY_CHANGE_EVIDENCE, output)
            self.assertIn("Recommended Next Steps:", output)
            self.assertIn("Verify VLAN 10 exists", output)
            data = json.loads(
                (workdir / "incident_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual("VLAN 10 outage", data["title"])
            self.assertEqual("2026-07-09T23:41:18+00:00", data["generated_at"])
            self.assertIn(
                "# Atlas Incident Investigation",
                (workdir / "incident_report.md").read_text(encoding="utf-8"),
            )

    def test_cli_requires_a_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, output, error = self.invoke(Path(tmp), ("", ""))
            self.assertEqual(1, code)
            self.assertIn("incident title is required", error)

    def test_help_lists_investigate(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("founderos atlas investigate", stdout.getvalue())


class DashboardIncidentTests(unittest.TestCase):
    def test_dashboard_shows_recent_investigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            report = IncidentInvestigator().investigate(
                "VLAN 10 outage",
                "VLAN 10 cannot access internet",
                IncidentArtifacts(snapshot=sample_snapshot()),
                generated_at="2026-07-09T23:41:18+00:00",
            )
            (workdir / "incident_report.json").write_text(
                render_incident_report_json(report), encoding="utf-8"
            )
            (workdir / "incident_report.md").write_text(
                render_incident_report_markdown(report), encoding="utf-8"
            )
            summary = build_dashboard_summary(**summary_kwargs(workdir))
        self.assertEqual(
            (
                "Title: VLAN 10 outage",
                "Generated: 09-Jul-2026 23:41",
                "Confidence: Medium",
            ),
            summary.incident_investigation,
        )
        availability = {action.label: action.available for action in summary.actions}
        self.assertTrue(availability["Open Incident Report"])

    def test_dashboard_without_investigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_dashboard_summary(**summary_kwargs(Path(tmp)))
        self.assertEqual((), summary.incident_investigation)
        availability = {action.label: action.available for action in summary.actions}
        self.assertFalse(availability["Open Incident Report"])


if __name__ == "__main__":
    unittest.main()
