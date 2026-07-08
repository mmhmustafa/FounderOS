"""Acceptance tests for the deterministic Atlas Morning Brief Journey."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import urllib.request

from jsonschema import Draft202012Validator

from founderos_atlas.demo import atlas_app_root, run_atlas_discovery_demo
from founderos_atlas.journeys import MorningBriefJourney, build_morning_brief
from founderos_atlas.topology import TopologyGraph, TopologySnapshot
from founderos_runtime.cli import main
from founderos_runtime.journey import JourneyStatus
from founderos_runtime.workspace import Workspace


class MorningBriefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.discovery, _, cls.current = run_atlas_discovery_demo()
        previous_graph = TopologyGraph()
        previous_graph.merge_discovery_result(cls.discovery)
        cls.previous = TopologySnapshot.from_graph(
            previous_graph,
            metadata={"source": "morning_brief_test_baseline"},
        )

    def test_current_snapshot_only(self) -> None:
        brief = build_morning_brief(self.current)
        self.assertEqual("Healthy", brief.overall_status)
        self.assertEqual((), brief.new_devices)
        self.assertEqual((), brief.removed_devices)
        self.assertIn("No comparison baseline", brief.summary)

    def test_snapshot_comparison_detects_changed_device(self) -> None:
        brief = build_morning_brief(self.current, self.previous)
        self.assertEqual(("access-sw-01",), brief.changed_devices)
        self.assertEqual("Attention Required", brief.overall_status)
        self.assertIn("1 changed devices", brief.summary)

    def test_recommendations_are_actionable(self) -> None:
        brief = build_morning_brief(self.current, self.previous)
        self.assertEqual(
            (
                "Confirm the new adjacency between access-sw-01 and router-01 "
                "is expected.",
                "Review access-sw-01 configuration and topology changes.",
            ),
            brief.recommendations,
        )

    def test_markdown_generation(self) -> None:
        markdown = build_morning_brief(self.current, self.previous).to_markdown()
        self.assertIn("# Good Morning", markdown)
        self.assertIn("## Network Status", markdown)
        self.assertIn("- Changed devices: 1", markdown)
        self.assertIn("## Recommendations", markdown)
        self.assertNotIn("mappingproxy", markdown)

    def test_workflow_manifest_loads_in_atlas_workspace(self) -> None:
        workspace = Workspace.load(atlas_app_root(), runtime_version="0.3.0")
        workflow = workspace.get_workflow("wfl_01ARZ3NDEKTSV4RRFFQ69G5FBY")
        self.assertEqual("utility", workflow["workflow_type"])
        self.assertEqual("artifact_creation", workflow["steps"][0]["type"])
        self.assertIsNone(workflow["transition_intent"])

    def test_journey_executes_through_founderos_runner(self) -> None:
        outcome = MorningBriefJourney().run(self.current, self.previous)
        self.assertIs(outcome.journey_result.status, JourneyStatus.SUCCEEDED)
        self.assertEqual(
            ("generate_morning_brief", "evaluate_morning_brief"),
            outcome.journey_result.completed_steps,
        )
        events = [item["event"] for item in outcome.journey_result.execution_log]
        self.assertEqual(["artifact_created", "evaluation_completed"], events)
        self.assertIn("morning_brief", outcome.journey_result.generated_artifacts)
        self.assertTrue(outcome.journey_result.metadata["validation"]["valid"])
        self.assertTrue(outcome.journey_result.metadata["authorization"]["allowed"])

    def test_evaluation_passes_with_full_quality_score(self) -> None:
        outcome = MorningBriefJourney().run(self.current, self.previous)
        self.assertTrue(outcome.evaluation.passed)
        self.assertEqual(1.0, outcome.evaluation.score)
        self.assertEqual(5, len(outcome.evaluation.findings))

    def test_artifact_matches_declared_schema(self) -> None:
        brief = MorningBriefJourney().run(self.current, self.previous).brief
        schema_path = atlas_app_root() / "manifests" / "schemas" / "morning-brief.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(brief.to_dict())

    def test_deterministic_output(self) -> None:
        first = MorningBriefJourney().run(self.current, self.previous)
        second = MorningBriefJourney().run(self.current, self.previous)
        self.assertEqual(first.brief, second.brief)
        self.assertEqual(first.markdown, second.markdown)
        self.assertEqual(first.evaluation, second.evaluation)
        self.assertEqual(first.journey_result.to_dict(), second.journey_result.to_dict())

    def test_cli_generates_markdown_artifact(self) -> None:
        destination = Path(__file__).resolve().parent / ".morning_brief_test.md"
        stdout, stderr = StringIO(), StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    ["atlas", "morning-brief"],
                    atlas_morning_brief_output=destination,
                )
            self.assertEqual(0, code, stderr.getvalue())
            self.assertTrue(destination.is_file())
            self.assertIn("Quality score: 1.00", stdout.getvalue())
            self.assertIn("Journey status: succeeded", stdout.getvalue())
            self.assertIn("# Good Morning", destination.read_text(encoding="utf-8"))
        finally:
            destination.unlink(missing_ok=True)

    def test_no_network_access(self) -> None:
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            outcome = MorningBriefJourney().run(self.current, self.previous)
        self.assertIs(outcome.journey_result.status, JourneyStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
