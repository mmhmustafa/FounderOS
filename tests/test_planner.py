"""Runtime Planner routing and non-mutation tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

from founderos_runtime import ExecutionContext, ExecutionContextBuilder, Planner, PlanningError
from founderos_runtime.planning_rules import PLANNING_RULES
from founderos_runtime.state_machine import KNOWN_STATES

from tests.helpers import RuntimeFixture


def context(state: str, completed_artifacts: tuple[str, ...] = ()) -> ExecutionContext:
    return ExecutionContext(
        project_id="prj_01JBY9M6H7Q5A3X2K8C4N0T1VW",
        current_state=state,
        completed_artifacts=tuple(sorted(completed_artifacts)),
        pending_artifacts=(),
        available_agents=(),
        available_workflows=(),
        decisions=(),
        risks=(),
        events=(),
        next_action="Plan the next action",
    )


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = RuntimeFixture()
        self.planner = Planner(self.fx.machine)

    def test_no_project_recommends_founder_setup(self) -> None:
        plan = self.planner.plan(context("NO_PROJECT"))
        self.assertEqual(plan.recommended_workflow, "Founder Setup Workflow")
        self.assertEqual(plan.next_state_candidate, "FOUNDER_SETUP")
        self.assertIsNone(plan.blocked_reason)

    def test_founder_setup_blocks_until_founder_brief_exists(self) -> None:
        plan = self.planner.plan(context("FOUNDER_SETUP"))
        self.assertEqual(plan.recommended_workflow, "Founder Setup Workflow")
        self.assertEqual(plan.missing_artifacts, ("founder_brief",))
        self.assertIn("founder_brief", plan.blocked_reason or "")

    def test_founder_setup_unblocks_with_approved_founder_brief(self) -> None:
        plan = self.planner.plan(context("FOUNDER_SETUP", ("founder_brief",)))
        self.assertEqual(plan.missing_artifacts, ())
        self.assertIsNone(plan.blocked_reason)
        self.assertEqual(plan.next_state_candidate, "FOUNDER_BRIEF_COMPLETE")

    def test_founder_brief_complete_recommends_discovery(self) -> None:
        plan = self.planner.plan(context("FOUNDER_BRIEF_COMPLETE", ("founder_brief",)))
        self.assertEqual(plan.recommended_workflow, "Discovery Workflow")
        self.assertEqual(plan.next_state_candidate, "DISCOVERY_RUNNING")
        self.assertIsNone(plan.blocked_reason)

    def test_discovery_running_blocks_without_opportunity_report(self) -> None:
        plan = self.planner.plan(context("DISCOVERY_RUNNING"))
        self.assertEqual(plan.recommended_workflow, "Discovery Workflow")
        self.assertEqual(plan.missing_artifacts, ("opportunity_report",))
        self.assertIsNotNone(plan.blocked_reason)

    def test_opportunity_selected_recommends_validation(self) -> None:
        plan = self.planner.plan(context("OPPORTUNITY_SELECTED", ("opportunity_report",)))
        self.assertEqual(plan.recommended_workflow, "Validation Workflow")
        self.assertEqual(plan.next_state_candidate, "VALIDATION_RUNNING")
        self.assertIsNone(plan.blocked_reason)

    def test_unknown_state_is_rejected(self) -> None:
        with self.assertRaisesRegex(PlanningError, "Unknown project state"):
            self.planner.plan(context("UNKNOWN_STATE"))

    def test_plan_contains_missing_artifacts_agents_transitions_and_gates(self) -> None:
        plan = self.planner.plan(context("FOUNDER_SETUP"))
        self.assertEqual(plan.required_artifacts, ("founder_brief",))
        self.assertEqual(plan.missing_artifacts, ("founder_brief",))
        self.assertIn("Founder Interview Agent", plan.recommended_agents)
        self.assertEqual(plan.allowed_transitions, ("FOUNDER_BRIEF_COMPLETE",))
        self.assertIn("approved_artifact:founder_brief", plan.quality_gate_requirements)
        self.assertIn("human_approval:approved_and_current", plan.quality_gate_requirements)
        self.assertEqual(plan.confidence_score, 1.0)

    def test_planner_does_not_mutate_project_or_repositories(self) -> None:
        builder = ExecutionContextBuilder(self.fx.repositories)
        before_project = deepcopy(self.fx.refresh_project())
        before_events = deepcopy(self.fx.repositories.events.for_project(before_project["id"]))
        before_transitions = deepcopy(self.fx.repositories.transitions.all())
        self.planner.plan(builder.build(before_project["id"]))
        self.assertEqual(self.fx.refresh_project(), before_project)
        self.assertEqual(self.fx.repositories.events.for_project(before_project["id"]), before_events)
        self.assertEqual(self.fx.repositories.transitions.all(), before_transitions)

    def test_planner_is_deterministic(self) -> None:
        execution_context = context("DISCOVERY_RUNNING", ("founder_brief",))
        first = self.planner.plan(execution_context)
        second = self.planner.plan(execution_context)
        self.assertEqual(first, second)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_execution_context_builder_collects_runtime_inventory(self) -> None:
        self.fx.create_agent_definition()
        self.fx.create_workflow_definition()
        built = ExecutionContextBuilder(self.fx.repositories).build(self.fx.project["id"])
        self.assertEqual(built.project_id, self.fx.project["id"])
        self.assertEqual(built.current_state, "NO_PROJECT")
        self.assertEqual(len(built.available_agents), 1)
        self.assertEqual(len(built.available_workflows), 1)
        self.assertEqual(tuple(event.sequence for event in built.events), (1,))

    def test_context_and_artifact_planner_ignore_unapproved_artifacts(self) -> None:
        self.fx.create_artifact("founder_brief", status="draft")
        built = ExecutionContextBuilder(self.fx.repositories).build(self.fx.project["id"])
        self.assertNotIn("founder_brief", built.completed_artifacts)
        plan = self.planner.plan(replace(built, current_state="FOUNDER_SETUP"))
        self.assertEqual(plan.missing_artifacts, ("founder_brief",))
        self.assertIsNotNone(plan.blocked_reason)

    def test_every_known_state_has_one_consistent_planning_rule(self) -> None:
        self.assertEqual(set(PLANNING_RULES), set(KNOWN_STATES))
        for state, rule in PLANNING_RULES.items():
            if rule.next_state is not None:
                self.assertIn(rule.next_state, self.fx.machine.allowed_transitions(state))


if __name__ == "__main__":
    unittest.main()
