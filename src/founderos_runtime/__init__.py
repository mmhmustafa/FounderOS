"""FounderOS contract-enforcing runtime foundation."""

from .contracts import ContractRegistry
from .errors import (
    ApprovalRequiredError,
    ConflictError,
    ContractValidationError,
    DuplicateRecordError,
    PersistenceError,
    PersistenceLockError,
    RecordNotFoundError,
    ReferenceIntegrityError,
    RecoveryError,
    RuntimeFoundationError,
    StateMutationError,
    VerticalSliceError,
)
from .content import InMemoryContentStore
from .founder_setup import FounderBriefPreparation, FounderSetupCompletion, FounderSetupService, FounderSetupSession
from .ids import new_id, utc_now
from .execution_context import ExecutionContext, ExecutionContextBuilder
from .planner import AgentRouter, ArtifactPlanner, ExecutionPlan, Planner, PlanningError, WorkflowSelector
from .project_state import ProjectStateService, replay_project_events
from .repositories import RuntimeRepositories
from .runs import AgentRunService, WorkflowRunService
from .state_machine import StateMachine, TransitionCommand
from .application import FounderOSApplication
from .local_store import LocalProjectStore, LocalRuntime, PersistenceHealth
from .lifecycle import ApprovalLifecycleService, ArtifactLifecycleService, DecisionLifecycleService, EvaluationLifecycleService
from .diagnostics import REDACTED, RuntimeDiagnostics, command_correlation, redact
from .discovery import DiscoveryCompletion, DiscoveryPreparation, DiscoveryWorkflowService, score_candidates

__all__ = [
    "ApprovalRequiredError",
    "AgentRunService",
    "AgentRouter",
    "ArtifactPlanner",
    "ArtifactLifecycleService",
    "ApprovalLifecycleService",
    "FounderBriefPreparation",
    "FounderSetupCompletion",
    "FounderSetupService",
    "FounderSetupSession",
    "FounderOSApplication",
    "InMemoryContentStore",
    "LocalProjectStore",
    "LocalRuntime",
    "PersistenceHealth",
    "ConflictError",
    "ContractRegistry",
    "ContractValidationError",
    "DuplicateRecordError",
    "DiscoveryCompletion",
    "DiscoveryPreparation",
    "DiscoveryWorkflowService",
    "ExecutionContext",
    "ExecutionContextBuilder",
    "ExecutionPlan",
    "EvaluationLifecycleService",
    "DecisionLifecycleService",
    "ProjectStateService",
    "Planner",
    "PlanningError",
    "PersistenceError",
    "PersistenceLockError",
    "RecordNotFoundError",
    "ReferenceIntegrityError",
    "RecoveryError",
    "RuntimeFoundationError",
    "RuntimeDiagnostics",
    "RuntimeRepositories",
    "StateMachine",
    "StateMutationError",
    "TransitionCommand",
    "VerticalSliceError",
    "WorkflowRunService",
    "WorkflowSelector",
    "REDACTED",
    "command_correlation",
    "new_id",
    "replay_project_events",
    "redact",
    "score_candidates",
    "utc_now",
]
