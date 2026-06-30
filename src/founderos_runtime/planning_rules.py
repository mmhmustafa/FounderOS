"""Deterministic planner routing metadata layered over State Machine routes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanningRule:
    workflow: str | None
    next_state: str | None
    required_artifacts: tuple[str, ...]
    agent_roles: tuple[str, ...]


PLANNING_RULES: dict[str, PlanningRule] = {
    "NO_PROJECT": PlanningRule("Founder Setup Workflow", "FOUNDER_SETUP", (), ("Founder Interview Agent",)),
    "FOUNDER_SETUP": PlanningRule(
        "Founder Setup Workflow", "FOUNDER_BRIEF_COMPLETE", ("founder_brief",), ("Founder Interview Agent",)
    ),
    "FOUNDER_BRIEF_COMPLETE": PlanningRule(
        "Discovery Workflow",
        "DISCOVERY_RUNNING",
        ("founder_brief",),
        ("Market Research Agent", "Network Pain Agent", "Competitor Agent", "Opportunity Scoring Agent"),
    ),
    "DISCOVERY_RUNNING": PlanningRule(
        "Discovery Workflow",
        "OPPORTUNITY_SELECTED",
        ("opportunity_report",),
        ("Market Research Agent", "Network Pain Agent", "Competitor Agent", "Opportunity Scoring Agent"),
    ),
    "OPPORTUNITY_SELECTED": PlanningRule(
        "Validation Workflow",
        "VALIDATION_RUNNING",
        ("opportunity_report",),
        ("Customer Research Agent", "Validation Strategist"),
    ),
    "VALIDATION_RUNNING": PlanningRule(
        "Validation Workflow",
        "VALIDATION_PASSED",
        ("validation_report",),
        ("Customer Research Agent", "Validation Strategist"),
    ),
    "VALIDATION_PASSED": PlanningRule(
        "Product Design Workflow", "PRODUCT_DESIGN_RUNNING", ("validation_report",), ("Product Manager", "UX Researcher")
    ),
    "PRODUCT_DESIGN_RUNNING": PlanningRule(
        "Product Design Workflow", "PRD_COMPLETE", ("prd",), ("Product Manager", "UX Researcher")
    ),
    "PRD_COMPLETE": PlanningRule(
        "Engineering Workflow", "ARCHITECTURE_RUNNING", ("prd",), ("CTO Agent", "Lead Engineer")
    ),
    "ARCHITECTURE_RUNNING": PlanningRule(
        "Engineering Workflow",
        "ARCHITECTURE_COMPLETE",
        ("api_specification", "architecture", "database_design", "security_model"),
        ("CTO Agent", "Lead Engineer"),
    ),
    "ARCHITECTURE_COMPLETE": PlanningRule(
        "AI Design Workflow", "AI_DESIGN_RUNNING", ("architecture",), ("AI Architect",)
    ),
    "AI_DESIGN_RUNNING": PlanningRule(
        "AI Design Workflow", "AI_ARCHITECTURE_COMPLETE", ("ai_architecture", "evaluation_plan"), ("AI Architect",)
    ),
    "AI_ARCHITECTURE_COMPLETE": PlanningRule(
        "Development Planning Workflow",
        "DEVELOPMENT_PLANNING",
        ("ai_architecture",),
        ("Lead Engineer",),
    ),
    "DEVELOPMENT_PLANNING": PlanningRule(
        "Development Planning Workflow",
        "SPRINT_READY",
        ("implementation_backlog", "sprint_plan"),
        ("Lead Engineer",),
    ),
    "SPRINT_READY": PlanningRule("MVP Build Workflow", "MVP_BUILDING", ("sprint_plan",), ("Lead Engineer",)),
    "MVP_BUILDING": PlanningRule("MVP Build Workflow", "QA_RUNNING", (), ("Lead Engineer",)),
    "QA_RUNNING": PlanningRule("QA Workflow", "READY_FOR_BETA", (), ("QA Engineer",)),
    "READY_FOR_BETA": PlanningRule(
        "Launch Workflow",
        "LAUNCH_RUNNING",
        ("beta_launch_plan", "gtm_plan", "sales_playbook", "support_plan"),
        ("Growth Strategist", "Sales Strategist"),
    ),
    "LAUNCH_RUNNING": PlanningRule(
        "Launch Workflow", "CUSTOMERS_ACQUIRED", ("customer_evidence",), ("Growth Strategist", "Sales Strategist")
    ),
    "CUSTOMERS_ACQUIRED": PlanningRule("CEO Review Workflow", "CEO_REVIEW", (), ("CEO Review Agent",)),
    "CEO_REVIEW": PlanningRule("CEO Review Workflow", "SCALING", ("ceo_review",), ("CEO Review Agent",)),
    "SCALING": PlanningRule(None, None, (), ()),
}
