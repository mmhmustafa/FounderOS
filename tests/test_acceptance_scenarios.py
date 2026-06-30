"""Executable coverage of runtime/contracts/acceptance-scenarios.md."""

from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from founderos_runtime import (
    ConflictError,
    ContractValidationError,
    ReferenceIntegrityError,
    StateMutationError,
    TransitionCommand,
    replay_project_events,
)
from founderos_runtime.ids import reference, utc_now

from tests.helpers import HUMAN, RuntimeFixture


class ContractAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = RuntimeFixture()

    def test_ac01_schema_acceptance_without_coercion(self) -> None:
        original = deepcopy(self.fx.project)
        validated = self.fx.contracts.validate("project", original)
        self.assertEqual(validated, original)
        self.assertIsInstance(validated["revision"], int)

    def test_all_required_schemas_load_and_meta_validate(self) -> None:
        self.assertEqual(len(self.fx.contracts.schema_names), 14)

    def test_ac02_unknown_and_malformed_data_rejected(self) -> None:
        malformed = deepcopy(self.fx.project)
        malformed["unexpected"] = True
        with self.assertRaises(ContractValidationError):
            self.fx.contracts.validate("project", malformed)
        malformed = deepcopy(self.fx.project)
        malformed["updated_at"] = "2026-01-01T00:00:00+05:30"
        with self.assertRaises(ContractValidationError):
            self.fx.contracts.validate("project", malformed)

    def test_ac03_exact_reference_resolution(self) -> None:
        workflow = self.fx.create_workflow_definition()
        exact = reference("workflow", workflow, include_version=True)
        self.assertEqual(self.fx.repositories.resolve_reference(exact)["id"], workflow["id"])
        wrong_version = {**exact, "version": "2.0.0"}
        with self.assertRaises(ReferenceIntegrityError):
            self.fx.repositories.resolve_reference(wrong_version)
        wrong_kind = {"kind": "agent", "id": workflow["id"], "version": "1.0.0"}
        with self.assertRaises(ReferenceIntegrityError):
            self.fx.repositories.resolve_reference(wrong_kind)

    def _prepare_founder_brief_transition(self, *, evaluation_outcome: str = "pass") -> tuple:
        self.fx.move_to_founder_setup()
        workflow = self.fx.create_workflow_definition(
            entry_state="FOUNDER_SETUP", exit_states=["FOUNDER_BRIEF_COMPLETE"]
        )
        run = self.fx.create_workflow_run(workflow=workflow)
        run = self.fx.workflows.set_status(
            run["id"], "running", expected_revision=1, actor=HUMAN, correlation_id="setup-start"
        )
        run = self.fx.workflows.set_status(
            run["id"], "succeeded", expected_revision=2, actor=HUMAN, correlation_id="setup-complete"
        )
        artifact = self.fx.create_artifact("founder_brief")
        artifact_ref = reference("artifact", artifact, include_version=True)
        evaluation = self.fx.create_evaluation(artifact_ref, outcome=evaluation_outcome)
        approval = self.fx.create_approval(artifact_ref)
        return run, artifact, evaluation, approval

    def _founder_brief_command(self, run, artifact, evaluation, approvals, correlation_id="brief-transition"):
        return TransitionCommand(
            project_id=self.fx.project["id"],
            from_state="FOUNDER_SETUP",
            to_state="FOUNDER_BRIEF_COMPLETE",
            expected_project_revision=self.fx.project["revision"],
            trigger="approve_founder_brief",
            actor=HUMAN,
            correlation_id=correlation_id,
            workflow_run_ref=reference("workflow_run", run, include_revision=True),
            artifact_refs=(reference("artifact", artifact, include_version=True),),
            evaluation_refs=(reference("evaluation", evaluation),),
            approval_refs=tuple(reference("approval", approval, include_revision=True) for approval in approvals),
        )

    def test_ac04_founder_brief_transition_is_atomic(self) -> None:
        run, artifact, evaluation, approval = self._prepare_founder_brief_transition()
        before = self.fx.project
        outcome = self.fx.machine.transition(self._founder_brief_command(run, artifact, evaluation, [approval]))
        after = self.fx.refresh_project()
        self.assertEqual(outcome["status"], "applied")
        self.assertEqual(after["current_state"], "FOUNDER_BRIEF_COMPLETE")
        self.assertEqual(after["revision"], before["revision"] + 1)
        self.assertEqual(self.fx.repositories.events.for_project(after["id"])[-1]["event_type"], "transition.applied")

    def test_applied_transition_rolls_back_every_record_on_commit_failure(self) -> None:
        workflow_run = self.fx.create_workflow_run()
        command = TransitionCommand(
            project_id=self.fx.project["id"],
            from_state="NO_PROJECT",
            to_state="FOUNDER_SETUP",
            expected_project_revision=1,
            trigger="begin_setup",
            actor=HUMAN,
            correlation_id="atomic-failure",
            workflow_run_ref=reference("workflow_run", workflow_run, include_revision=True),
        )
        project_before = self.fx.refresh_project()
        event_count = len(self.fx.repositories.events.for_project(project_before["id"]))
        transition_count = len(self.fx.repositories.transitions.all())
        with patch.object(self.fx.repositories.projects, "_replace_validated", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                self.fx.machine.transition(command)
        self.assertEqual(self.fx.refresh_project(), project_before)
        self.assertEqual(len(self.fx.repositories.events.for_project(project_before["id"])), event_count)
        self.assertEqual(len(self.fx.repositories.transitions.all()), transition_count)

    def test_ac05_missing_approval_preserves_project(self) -> None:
        run, artifact, evaluation, _ = self._prepare_founder_brief_transition()
        before = deepcopy(self.fx.project)
        outcome = self.fx.machine.transition(self._founder_brief_command(run, artifact, evaluation, []))
        after = self.fx.refresh_project()
        self.assertEqual(outcome["rejection_code"], "APPROVAL_MISSING")
        self.assertEqual(after, before)

    def test_ac06_failed_evaluation_is_immutable_and_rejected(self) -> None:
        run, artifact, evaluation, approval = self._prepare_founder_brief_transition(evaluation_outcome="fail")
        outcome = self.fx.machine.transition(self._founder_brief_command(run, artifact, evaluation, [approval]))
        self.assertEqual(outcome["rejection_code"], "GUARD_FAILED")
        with self.assertRaises(ConflictError):
            self.fx.repositories.evaluations.replace(evaluation)

    def test_ac07_stale_revision_rejected(self) -> None:
        command = TransitionCommand(
            project_id=self.fx.project["id"],
            from_state="NO_PROJECT",
            to_state="FOUNDER_SETUP",
            expected_project_revision=99,
            trigger="stale_request",
            actor=HUMAN,
            correlation_id="stale",
        )
        outcome = self.fx.machine.transition(command)
        self.assertEqual(outcome["rejection_code"], "STALE_REVISION")
        self.assertEqual(self.fx.refresh_project()["revision"], 1)

    def test_ac08_invalid_route_rejected(self) -> None:
        command = TransitionCommand(
            project_id=self.fx.project["id"],
            from_state="NO_PROJECT",
            to_state="VALIDATION_RUNNING",
            expected_project_revision=1,
            trigger="skip_states",
            actor=HUMAN,
            correlation_id="invalid-route",
        )
        outcome = self.fx.machine.transition(command)
        self.assertEqual(outcome["rejection_code"], "INVALID_TRANSITION")

    def _active_agent_run(self, *, max_attempts: int = 2, attempt: int = 1):
        workflow = self.fx.create_workflow_definition(max_attempts=max_attempts)
        workflow_run = self.fx.create_workflow_run(workflow=workflow)
        workflow_run = self.fx.workflows.set_status(
            workflow_run["id"], "running", expected_revision=1, actor=HUMAN, correlation_id=f"workflow-{max_attempts}"
        )
        agent = self.fx.create_agent_definition()
        run = self.fx.agents.create(
            project_ref=self.fx.project_ref,
            workflow_run_ref=reference("workflow_run", workflow_run),
            agent_ref=reference("agent", agent, include_version=True),
            attempt=attempt,
        )
        run = self.fx.agents.set_status(
            run["id"], "running", expected_revision=1, actor=HUMAN, correlation_id=f"agent-start-{attempt}"
        )
        return workflow_run, run

    def test_ac09_retry_creates_new_agent_run(self) -> None:
        _, run = self._active_agent_run(max_attempts=2)
        failed = self.fx.agents.set_status(
            run["id"],
            "failed",
            expected_revision=2,
            actor=HUMAN,
            correlation_id="agent-fail",
            failure={"code": "TEMPORARY_FAILURE", "message": "Retry", "retryable": True, "recovery_action": "Retry"},
        )
        retry = self.fx.agents.retry(failed["id"])
        self.assertNotEqual(retry["id"], failed["id"])
        self.assertEqual(retry["attempt"], 2)
        self.assertEqual(self.fx.repositories.agent_runs.get(failed["id"])["status"], "failed")

    def test_ac10_retry_exhaustion_fails_workflow(self) -> None:
        workflow_run, run = self._active_agent_run(max_attempts=1)
        self.fx.agents.set_status(
            run["id"],
            "failed",
            expected_revision=2,
            actor=HUMAN,
            correlation_id="final-agent-fail",
            failure={"code": "FINAL_FAILURE", "message": "Exhausted", "retryable": True, "recovery_action": "Escalate"},
        )
        self.assertEqual(self.fx.repositories.workflow_runs.get(workflow_run["id"])["status"], "failed")
        self.assertEqual(self.fx.refresh_project()["current_state"], "NO_PROJECT")

    def test_ac11_event_replay_is_deterministic_and_gap_checked(self) -> None:
        self.fx.move_to_founder_setup()
        project = self.fx.refresh_project()
        events = self.fx.repositories.events.for_project(project["id"])
        replayed = replay_project_events(events)
        self.assertEqual(replayed["current_state"], project["current_state"])
        self.assertEqual(replayed["revision"], project["revision"])
        broken = deepcopy(events)
        broken[-1]["sequence"] += 1
        with self.assertRaises(ConflictError):
            replay_project_events(broken)

    def test_ac12_duplicate_transition_command_is_idempotent(self) -> None:
        workflow_run = self.fx.create_workflow_run()
        command = TransitionCommand(
            project_id=self.fx.project["id"],
            from_state="NO_PROJECT",
            to_state="FOUNDER_SETUP",
            expected_project_revision=1,
            trigger="begin_setup",
            actor=HUMAN,
            correlation_id="same-command",
            workflow_run_ref=reference("workflow_run", workflow_run, include_revision=True),
        )
        first = self.fx.machine.transition(command)
        event_count = len(self.fx.repositories.events.for_project(self.fx.project["id"]))
        second = self.fx.machine.transition(command)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(len(self.fx.repositories.events.for_project(self.fx.project["id"])), event_count)

    def test_ac13_direct_project_state_write_rejected(self) -> None:
        changed = deepcopy(self.fx.project)
        changed["current_state"] = "FOUNDER_SETUP"
        changed["revision"] = 2
        changed["updated_at"] = utc_now()
        with self.assertRaises(StateMutationError):
            self.fx.repositories.projects.replace(changed, expected_revision=1)

    def test_ac14_knowledge_is_not_a_resolvable_evidence_kind(self) -> None:
        with self.assertRaises(ReferenceIntegrityError):
            self.fx.repositories.resolve_reference({"kind": "knowledge", "id": "knw_01JBY9M6H7Q5A3X2K8C4N0T1VW"})


if __name__ == "__main__":
    unittest.main()
