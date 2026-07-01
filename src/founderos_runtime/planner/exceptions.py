"""Typed Workspace Planner failures."""


class PlannerError(Exception):
    """Base exception for deterministic planning failures."""


class PlannerWorkflowNotFoundError(PlannerError):
    """The requested Workflow is absent from the Workspace."""


class PlannerAgentNotFoundError(PlannerError):
    """A Workflow step or definition references an unavailable Agent."""


class PlannerArtifactReferenceError(PlannerError):
    """An Artifact dependency is undeclared, unavailable, or ambiguous."""


class PlannerCircularDependencyError(PlannerError):
    """Workflow step Artifact dependencies contain a cycle."""


class PlannerInvalidWorkflowError(PlannerError):
    """A Workflow definition cannot produce a coherent ExecutionPlan."""
