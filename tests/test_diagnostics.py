"""Runtime observability, correlation, audit, and redaction tests."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from founderos_runtime import FounderOSApplication, LocalProjectStore, REDACTED
from founderos_runtime.cli import main


class RuntimeDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / ".founderos"
        self.content = {
            "founder_profile": {
                "name": "Founder", "background": "Sensitive founder history",
                "domain_expertise": ["testing"], "technical_skills": ["Python"],
                "business_skills": [], "available_time_per_week": 10,
                "available_budget": {"amount": 1000, "currency": "USD"},
            },
            "startup_context": {
                "domain": "testing", "target_users": ["teams"],
                "known_problem_area": "Sensitive customer pain", "constraints": ["private"],
                "success_definition": "Validated need",
            },
            "open_questions": ["Sensitive question"],
        }
        app = FounderOSApplication(self.root)
        self.new_result = app.new(
            name="Diagnostics", founder_id="founder-1", founder_name="Founder", domain="Testing",
            command_key="new-command",
        )
        self.brief_result = app.founder_brief(self.content, command_key="brief-command")
        self.approve_result = app.approve(rationale="Sensitive approval rationale", command_key="approve-command")

    def invoke(self, *args: str) -> tuple[int, object, str]:
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--project-dir", str(self.root), *args])
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, stderr.getvalue()

    def test_command_correlation_spans_application_records_and_events(self) -> None:
        audit = FounderOSApplication(self.root).audit()
        correlations = {item["command_correlation_id"] for item in audit["timeline"]}
        self.assertIn(self.new_result["command_correlation_id"], correlations)
        self.assertIn(self.brief_result["command_correlation_id"], correlations)
        self.assertIn(self.approve_result["command_correlation_id"], correlations)
        approve_events = [
            item for item in audit["timeline"]
            if item["command_correlation_id"] == self.approve_result["command_correlation_id"]
        ]
        self.assertIn("approval.decided", [item["event_type"] for item in approve_events])
        self.assertIn("transition.applied", [item["event_type"] for item in approve_events])
        runtime = LocalProjectStore(self.root).load()
        self.assertEqual(self.new_result["command_correlation_id"], runtime.repositories.projects.all()[0]["metadata"]["correlation_id"])
        self.assertTrue(all(item.get("metadata", {}).get("correlation_id") for item in runtime.repositories.workflow_runs.all()))
        self.assertTrue(all(item.get("metadata", {}).get("correlation_id") for item in runtime.repositories.agent_runs.all()))

    def test_audit_timeline_and_command_summaries_are_ordered(self) -> None:
        audit = FounderOSApplication(self.root).audit()
        sequences = [item["sequence"] for item in audit["timeline"]]
        self.assertEqual(list(range(1, len(sequences) + 1)), sequences)
        first_sequences = [item["first_sequence"] for item in audit["commands"]]
        self.assertEqual(sorted(first_sequences), first_sequences)
        self.assertTrue(all(item["duration_ms"] >= 0 for item in audit["commands"]))

    def test_approval_transition_and_artifact_are_traceable(self) -> None:
        audit = FounderOSApplication(self.root).audit()
        transition = next(item for item in audit["transitions"] if item["to_state"] == "FOUNDER_BRIEF_COMPLETE")
        self.assertEqual(self.approve_result["transition_id"], transition["id"])
        self.assertIn(self.approve_result["approval_id"], [item["id"] for item in transition["approval_refs"]])
        self.assertIn(self.brief_result["artifact_id"], [item["id"] for item in transition["artifact_refs"]])

    def test_sensitive_content_is_redacted_by_default_and_explicitly_available(self) -> None:
        redacted = FounderOSApplication(self.root).audit()
        self.assertNotIn("content", redacted["artifacts"][0])
        self.assertEqual(REDACTED, redacted["approvals"][0]["rationale"])
        explicit = FounderOSApplication(self.root).audit(include_sensitive=True)
        self.assertEqual(self.content["founder_profile"], explicit["artifacts"][0]["content"]["founder_profile"])
        self.assertEqual("Sensitive approval rationale", explicit["approvals"][0]["rationale"])

    def test_recovery_preserves_auditable_consistent_state(self) -> None:
        store = LocalProjectStore(self.root)
        store.events_path.write_text("corrupt\n", encoding="utf-8")
        store.recover()
        audit = FounderOSApplication(self.root).audit()
        self.assertTrue(all(audit["consistency"].values()))
        self.assertEqual(list(range(1, len(audit["timeline"]) + 1)), [item["sequence"] for item in audit["timeline"]])

    def test_audit_runs_and_transitions_commands_do_not_mutate(self) -> None:
        store = LocalProjectStore(self.root)
        before_state = store.state_path.read_bytes()
        before_events = store.events_path.read_bytes()
        for command in ("audit", "runs", "transitions"):
            code, output, error = self.invoke(command)
            self.assertEqual(0, code, error)
            self.assertIsNotNone(output)
        self.assertEqual(before_state, store.state_path.read_bytes())
        self.assertEqual(before_events, store.events_path.read_bytes())

    def test_diagnostic_sections_cover_runtime_and_persistence(self) -> None:
        audit = FounderOSApplication(self.root).audit()
        self.assertEqual("FOUNDER_BRIEF_COMPLETE", audit["project"]["current_state"])
        self.assertTrue(audit["runs"]["workflow_runs"])
        self.assertTrue(audit["runs"]["agent_runs"])
        self.assertTrue(audit["approvals"])
        self.assertTrue(audit["evaluations"])
        self.assertTrue(audit["transitions"])
        self.assertTrue(audit["persistence"]["primary_valid"])


if __name__ == "__main__":
    unittest.main()
