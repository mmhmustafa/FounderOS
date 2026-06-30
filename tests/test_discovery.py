"""Deterministic Discovery Workflow v1 acceptance tests."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import unittest

from founderos_runtime import (
    DiscoveryWorkflowService,
    FounderOSApplication,
    LocalProjectStore,
    score_candidates,
)
from founderos_runtime.cli import main


class DiscoveryWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / ".founderos"
        self.app = FounderOSApplication(self.root)
        self.app.new(name="Discovery Test", founder_id="founder-1", founder_name="Founder", domain="Testing")
        self.founder_brief = {
            "founder_profile": {
                "name": "Founder", "background": "Engineer", "domain_expertise": ["testing"],
                "technical_skills": ["Python"], "business_skills": [], "available_time_per_week": 15,
                "available_budget": {"amount": 2000, "currency": "USD"},
            },
            "startup_context": {
                "domain": "testing", "target_users": ["engineering teams"],
                "known_problem_area": "Slow test feedback", "constraints": ["local only"],
                "success_definition": "Select one opportunity",
            },
        }
        self.candidates = [
            {
                "problem": "Teams wait too long for test feedback", "target_user": "Engineering managers",
                "pain_score": 9, "frequency_score": 9, "budget_score": 7,
                "ai_advantage_score": 6, "mvp_feasibility_score": 8, "founder_fit_score": 9,
                "assumptions": ["Teams run tests daily"], "risks": ["Crowded market"],
            },
            {
                "problem": "Release notes are inconsistent", "target_user": "Product managers",
                "pain_score": 5, "frequency_score": 6, "budget_score": 4,
                "ai_advantage_score": 7, "mvp_feasibility_score": 9, "founder_fit_score": 6,
                "assumptions": [], "risks": ["Low willingness to pay"],
            },
        ]

    def complete_founder_setup(self) -> None:
        self.app.founder_brief(self.founder_brief, command_key="brief")
        self.app.approve(rationale="Accurate founder brief", command_key="approve-brief")

    def test_discovery_cannot_run_without_approved_founder_brief(self) -> None:
        with self.assertRaisesRegex(ValueError, "FOUNDER_BRIEF_COMPLETE"):
            self.app.discovery(self.candidates)

    def test_discovery_creates_report_runs_evaluation_and_pending_approval(self) -> None:
        self.complete_founder_setup()
        result = self.app.discovery(self.candidates, command_key="discovery")
        runtime = LocalProjectStore(self.root).load()
        artifact = runtime.repositories.artifacts.get(result["artifact_id"])
        self.assertEqual("opportunity_report", artifact["artifact_type"])
        self.assertEqual("under_review", artifact["status"])
        self.assertEqual("DISCOVERY_RUNNING", result["project_state"])
        self.assertTrue(runtime.repositories.evaluations.all())
        self.assertEqual("pending", runtime.repositories.approvals.get(result["approval_id"])["status"])
        self.assertTrue(any(item["status"] == "succeeded" for item in runtime.repositories.agent_runs.all()))

    def test_scoring_is_deterministic_and_ranked(self) -> None:
        first = score_candidates(self.candidates)
        second = score_candidates(list(reversed(self.candidates)))
        self.assertEqual(first, second)
        self.assertEqual(48, first[0]["total_score"])
        self.assertGreater(first[0]["total_score"], first[1]["total_score"])

    def test_invalid_candidate_data_is_rejected(self) -> None:
        invalid = [dict(self.candidates[0], pain_score=11)]
        with self.assertRaisesRegex(ValueError, "pain_score"):
            score_candidates(invalid)
        invalid_total = [dict(self.candidates[0], total_score=1)]
        with self.assertRaisesRegex(ValueError, "total_score"):
            score_candidates(invalid_total)

    def test_opportunity_transition_does_not_happen_without_approval(self) -> None:
        self.complete_founder_setup()
        self.app.discovery(self.candidates)
        status = self.app.status()
        self.assertEqual("DISCOVERY_RUNNING", status["state"])
        self.assertIn("opportunity_report", status["pending_artifacts"])
        self.assertFalse(any(
            item["to_state"] == "OPPORTUNITY_SELECTED" and item["status"] == "applied"
            for item in LocalProjectStore(self.root).load().repositories.transitions.all()
        ))

    def test_approval_selects_opportunity_and_records_decision(self) -> None:
        self.complete_founder_setup()
        self.app.discovery(self.candidates, command_key="discovery")
        result = self.app.approve_opportunity(rationale="Highest deterministic score", command_key="select")
        self.assertEqual("OPPORTUNITY_SELECTED", result["project_state"])
        self.assertEqual("applied", result["transition_status"])
        runtime = LocalProjectStore(self.root).load()
        self.assertEqual("approved", runtime.repositories.decisions.get(result["decision_id"])["status"])

    def test_planner_before_during_and_after_discovery(self) -> None:
        self.complete_founder_setup()
        before = self.app.plan()
        self.assertEqual("Discovery Workflow", before["recommended_workflow"])
        self.assertEqual("DISCOVERY_RUNNING", before["next_state_candidate"])
        self.app.discovery(self.candidates)
        during = self.app.plan()
        self.assertEqual(("opportunity_report",), during["missing_artifacts"])
        self.app.approve_opportunity(rationale="Select top candidate")
        after = self.app.plan()
        self.assertEqual("Validation Workflow", after["recommended_workflow"])
        self.assertEqual("VALIDATION_RUNNING", after["next_state_candidate"])

    def test_discovery_audit_trace_and_redaction(self) -> None:
        self.complete_founder_setup()
        discovery = self.app.discovery(self.candidates, command_key="discovery-trace")
        selected = self.app.approve_opportunity(rationale="Sensitive selection rationale", command_key="selection-trace")
        audit = self.app.audit()
        discovery_events = [item for item in audit["timeline"] if item["command_correlation_id"] == discovery["command_correlation_id"]]
        event_types = [item["event_type"] for item in discovery_events]
        for required in ("workflow.started", "agent.started", "artifact.created", "evaluation.completed", "approval.requested", "agent.completed"):
            self.assertIn(required, event_types)
        transition = next(item for item in audit["transitions"] if item["id"] == selected["transition_id"])
        self.assertEqual(discovery["artifact_id"], transition["artifact_refs"][0]["id"])
        opportunity = next(item for item in audit["artifacts"] if item["artifact_type"] == "opportunity_report")
        self.assertNotIn("content", opportunity)

    def test_replay_resume_returns_opportunity_selected(self) -> None:
        self.complete_founder_setup()
        self.app.discovery(self.candidates)
        self.app.approve_opportunity(rationale="Select top candidate")
        runtime = LocalProjectStore(self.root).load()
        resumed = DiscoveryWorkflowService(runtime.repositories, runtime.content).resume(
            runtime.repositories.projects.all()[0]["id"]
        )
        self.assertEqual("OPPORTUNITY_SELECTED", resumed["project"]["current_state"])
        self.assertEqual(resumed["project"]["revision"], resumed["replayed_state"]["revision"])

    def test_cli_discovery_and_approve_opportunity_commands(self) -> None:
        self.complete_founder_setup()
        input_path = Path(self.temporary.name) / "candidates.json"
        input_path.write_text(json.dumps({"candidates": self.candidates}), encoding="utf-8")
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                "--project-dir", str(self.root), "discovery", "--input", str(input_path),
                "--idempotency-key", "cli-discovery",
            ])
        self.assertEqual(0, code, stderr.getvalue())
        discovery = json.loads(stdout.getvalue())
        self.assertEqual("DISCOVERY_RUNNING", discovery["project_state"])
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                "--project-dir", str(self.root), "approve-opportunity",
                "--rationale", "Highest deterministic score", "--idempotency-key", "cli-select",
            ])
        self.assertEqual(0, code, stderr.getvalue())
        self.assertEqual("OPPORTUNITY_SELECTED", json.loads(stdout.getvalue())["project_state"])

    def test_discovery_command_is_restart_idempotent(self) -> None:
        self.complete_founder_setup()
        first = self.app.discovery(self.candidates, command_key="same-discovery")
        event_count = len(LocalProjectStore(self.root).load().repositories.events.all())
        second = FounderOSApplication(self.root).discovery(
            list(reversed(self.candidates)), command_key="same-discovery"
        )
        self.assertEqual(first, second)
        self.assertEqual(event_count, len(LocalProjectStore(self.root).load().repositories.events.all()))


if __name__ == "__main__":
    unittest.main()
