"""End-to-end acceptance tests for the first Founder Setup slice."""

from __future__ import annotations

import unittest

from founderos_runtime import (
    ApprovalRequiredError,
    ContractRegistry,
    FounderSetupService,
    InMemoryContentStore,
    RuntimeRepositories,
)

HUMAN = {"type": "human", "id": "founder-1", "display_name": "Founder"}


class FounderSetupVerticalSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repositories = RuntimeRepositories(ContractRegistry())
        self.content = InMemoryContentStore(self.repositories.lock)
        self.service = FounderSetupService(self.repositories, self.content)
        self.project = self.service.create_project(
            name="FounderOS Test", founder_id="founder-1", founder_name="Founder", domain="B2B SaaS",
            actor=HUMAN, correlation_id="create-project")
        self.profile = {
            "name": "Founder", "background": "Software engineer building B2B products",
            "domain_expertise": ["developer tools"], "technical_skills": ["Python"], "business_skills": ["customer interviews"],
            "available_time_per_week": 20, "available_budget": {"amount": 5000, "currency": "USD"},
        }
        self.context = {
            "domain": "developer tools", "target_users": ["technical founders"],
            "known_problem_area": "Product validation is fragmented", "constraints": ["bootstrapped"],
            "success_definition": "Validate one painful repeatable problem",
        }

    def prepare(self):
        session = self.service.start(self.project["id"], actor=HUMAN, correlation_id="start")
        preparation = self.service.produce_founder_brief(
            session, founder_profile=self.profile, startup_context=self.context,
            assumptions=["Founders value one workflow"], risks=["Insufficient interviews"],
            open_questions=["Which segment first?"], correlation_id="produce")
        return session, preparation

    def test_create_and_plan_founder_setup(self) -> None:
        plan = self.service.plan(self.project["id"])
        self.assertEqual("NO_PROJECT", plan.current_state)
        self.assertEqual("Founder Setup Workflow", plan.recommended_workflow)

    def test_produces_persists_and_evaluates_structured_brief(self) -> None:
        session, preparation = self.prepare()
        self.assertEqual("FOUNDER_SETUP", self.repositories.projects.get(self.project["id"])["current_state"])
        artifact = self.repositories.artifacts.get(preparation.artifact_id)
        self.assertEqual("under_review", artifact["status"])
        self.assertEqual(preparation.content, self.content.get(artifact["content_uri"]))
        self.assertEqual("pass", self.repositories.evaluations.get(preparation.evaluation_id)["outcome"])
        self.assertEqual("pending", self.repositories.approvals.get(preparation.approval_id)["status"])
        self.assertEqual("succeeded", self.repositories.agent_runs.get(preparation.agent_run_id)["status"])
        self.assertEqual("running", self.repositories.workflow_runs.get(session.workflow_run_id)["status"])

    def test_transition_is_blocked_without_human_approval(self) -> None:
        _, preparation = self.prepare()
        with self.assertRaises(ApprovalRequiredError):
            self.service.complete(preparation, actor=HUMAN, correlation_id="complete")
        self.assertEqual("FOUNDER_SETUP", self.repositories.projects.get(self.project["id"])["current_state"])

    def test_approval_completion_and_resume_replay(self) -> None:
        _, preparation = self.prepare()
        self.service.approve_founder_brief(preparation, actor=HUMAN, rationale="Accurate", correlation_id="approve")
        completed = self.service.complete(preparation, actor=HUMAN, correlation_id="complete")
        self.assertEqual("applied", completed.transition["status"])
        self.assertEqual("FOUNDER_BRIEF_COMPLETE", completed.project["current_state"])
        resumed_service = FounderSetupService(self.repositories, self.content)
        resumed = resumed_service.resume(self.project["id"])
        self.assertEqual("FOUNDER_BRIEF_COMPLETE", resumed["replayed_state"]["current_state"])
        self.assertEqual(resumed["project"]["revision"], resumed["replayed_state"]["revision"])
        self.assertEqual(preparation.content, resumed["founder_briefs"][0]["content"])
        self.assertEqual("Discovery Workflow", resumed["plan"].recommended_workflow)

    def test_duplicate_completion_is_idempotent(self) -> None:
        _, preparation = self.prepare()
        self.service.approve_founder_brief(preparation, actor=HUMAN, rationale="Accurate", correlation_id="approve")
        first = self.service.complete(preparation, actor=HUMAN, correlation_id="same-completion")
        event_count = len(self.repositories.events.for_project(self.project["id"]))
        second = self.service.complete(preparation, actor=HUMAN, correlation_id="same-completion")
        self.assertEqual(first.transition["id"], second.transition["id"])
        self.assertEqual(event_count, len(self.repositories.events.for_project(self.project["id"])))

    def test_stale_transition_is_rejected_and_events_remain_ordered(self) -> None:
        _, preparation = self.prepare()
        self.service.approve_founder_brief(preparation, actor=HUMAN, rationale="Accurate", correlation_id="approve")
        result = self.service.complete(preparation, actor=HUMAN, correlation_id="stale", expected_project_revision=1)
        self.assertEqual("rejected", result.transition["status"])
        self.assertEqual("STALE_REVISION", result.transition["rejection_code"])
        events = self.repositories.events.for_project(self.project["id"])
        self.assertEqual(list(range(1, len(events) + 1)), [event["sequence"] for event in events])


if __name__ == "__main__":
    unittest.main()
