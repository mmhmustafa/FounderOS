"""CLI acceptance tests using isolated local project directories."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from founderos_runtime import FounderOSApplication, LocalProjectStore
from founderos_runtime.cli import main


class FounderOSCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / ".founderos"
        self.input_path = Path(self.temporary.name) / "founder-brief.json"
        self.input = {
            "founder_profile": {
                "name": "Founder", "background": "Software engineer building B2B products",
                "domain_expertise": ["developer tools"], "technical_skills": ["Python"],
                "business_skills": ["customer interviews"], "available_time_per_week": 20,
                "available_budget": {"amount": 5000, "currency": "USD"},
            },
            "startup_context": {
                "domain": "developer tools", "target_users": ["technical founders"],
                "known_problem_area": "Product validation is fragmented", "constraints": ["bootstrapped"],
                "success_definition": "Validate one painful repeatable problem",
            },
            "assumptions": ["Founders value one workflow"], "risks": ["Insufficient interviews"],
            "open_questions": ["Which segment first?"],
        }
        self.input_path.write_text(json.dumps(self.input), encoding="utf-8")

    def invoke(self, *arguments: str) -> tuple[int, object, str]:
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--project-dir", str(self.root), *arguments])
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else None
        return code, output, stderr.getvalue()

    def create_project(self) -> dict:
        code, output, error = self.invoke(
            "new", "--name", "CLI Project", "--founder-name", "Founder",
            "--founder-id", "founder-1", "--domain", "B2B SaaS")
        self.assertEqual(0, code, error)
        return output

    def create_brief(self) -> dict:
        self.create_project()
        code, output, error = self.invoke("founder-brief", "--input", str(self.input_path))
        self.assertEqual(0, code, error)
        return output

    def test_new_creates_local_project_state(self) -> None:
        output = self.create_project()
        self.assertEqual("NO_PROJECT", output["state"])
        self.assertTrue((self.root / "project-state.json").is_file())
        self.assertTrue((self.root / "events.jsonl").is_file())

    def test_status_shows_current_state_and_next_action(self) -> None:
        self.create_project()
        code, output, error = self.invoke("status")
        self.assertEqual(0, code, error)
        self.assertEqual("NO_PROJECT", output["state"])
        self.assertEqual([], output["completed_artifacts"])
        self.assertEqual("Begin founder setup", output["next_action"])

    def test_plan_recommends_founder_setup(self) -> None:
        self.create_project()
        code, output, error = self.invoke("plan")
        self.assertEqual(0, code, error)
        self.assertEqual("Founder Setup Workflow", output["recommended_workflow"])
        self.assertEqual("FOUNDER_SETUP", output["next_state_candidate"])

    def test_founder_brief_persists_artifact_without_transitioning(self) -> None:
        output = self.create_brief()
        self.assertEqual("under_review", output["artifact_status"])
        self.assertEqual("FOUNDER_SETUP", output["project_state"])
        self.assertTrue((self.root / "artifacts" / f"{output['artifact_id']}.json").is_file())

    def test_approve_applies_guarded_transition(self) -> None:
        self.create_brief()
        code, output, error = self.invoke("approve", "--rationale", "The brief is accurate")
        self.assertEqual(0, code, error)
        self.assertEqual("approved", output["approval_status"])
        self.assertEqual("applied", output["transition_status"])
        self.assertEqual("FOUNDER_BRIEF_COMPLETE", output["project_state"])

    def test_approve_rejects_progress_without_required_evidence(self) -> None:
        self.create_project()
        code, output, error = self.invoke("approve", "--rationale", "Skip the brief")
        self.assertEqual(1, code)
        self.assertIsNone(output)
        self.assertIn("No pending Founder Brief approval", error)
        self.assertEqual("NO_PROJECT", FounderOSApplication(self.root).status()["state"])

    def test_events_are_ordered_across_separate_cli_invocations(self) -> None:
        self.create_brief()
        self.invoke("approve", "--rationale", "The brief is accurate")
        code, output, error = self.invoke("events")
        self.assertEqual(0, code, error)
        self.assertEqual(list(range(1, len(output) + 1)), [event["sequence"] for event in output])

    def test_cli_uses_runtime_transition_records_and_replay(self) -> None:
        self.create_brief()
        self.invoke("approve", "--rationale", "The brief is accurate")
        runtime = LocalProjectStore(self.root).load()
        project = runtime.repositories.projects.all()[0]
        transitions = runtime.repositories.transitions.all()
        self.assertEqual(2, len([item for item in transitions if item["status"] == "applied"]))
        resumed = FounderOSApplication(self.root).status()
        self.assertEqual(project["current_state"], resumed["state"])
        self.assertEqual("FOUNDER_BRIEF_COMPLETE", project["current_state"])

    def test_decisions_lists_runtime_records(self) -> None:
        self.create_project()
        code, output, error = self.invoke("decisions")
        self.assertEqual(0, code, error)
        self.assertEqual([], output)

    def test_health_command_reports_valid_local_store(self) -> None:
        self.create_project()
        code, output, error = self.invoke("health")
        self.assertEqual(0, code, error)
        self.assertEqual("healthy", output["status"])
        self.assertTrue(output["primary_valid"])

    def test_recover_command_restores_valid_backup(self) -> None:
        self.create_project()
        store = LocalProjectStore(self.root)
        store.save(store.load())
        store.events_path.write_text("corrupt\n", encoding="utf-8")
        code, health, error = self.invoke("health")
        self.assertEqual(0, code, error)
        self.assertEqual("recoverable", health["status"])
        code, recovered, error = self.invoke("recover")
        self.assertEqual(0, code, error)
        self.assertEqual("healthy", recovered["status"])


if __name__ == "__main__":
    unittest.main()
