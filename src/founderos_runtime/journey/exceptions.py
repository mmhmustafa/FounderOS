"""Typed deterministic Journey Runner failures."""


class JourneyError(Exception):
    """Base exception for Journey construction or execution failures."""


class JourneyWorkflowNotFoundError(JourneyError):
    """The requested Workflow is unavailable to the Planner."""


class JourneyEmptyPlanError(JourneyError):
    """The Planner returned no executable or inspectable steps."""


class JourneyInvalidPlanError(JourneyError):
    """The ExecutionPlan contains unsupported or inconsistent data."""

