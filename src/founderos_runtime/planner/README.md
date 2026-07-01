# FounderOS Workspace Planner

## Purpose

The Planner is a deterministic, read-only decision layer over one validated Workspace. Given an exact Workflow ID, it resolves definitions and produces an immutable `ExecutionPlan` describing Agents, Artifact dependencies, ordered steps, Evaluation checkpoints, Approval gates, and transition intent.

```python
from founderos_runtime.planner import Planner
from founderos_runtime.workspace import Workspace

workspace = Workspace.load("path/to/project")
plan = Planner(workspace).plan("wfl_...")
```

## What the Planner Is Not

The Planner is not a runtime executor. It does not create WorkflowRuns or AgentRuns, invoke Providers or Tools, run Evaluation rules, request Approval, create Artifacts, append Events, persist data, authorize actors, call the State Machine, or mutate Project/Workspace state.

Planning describes intended coordination. It grants no authority and proves that no work has occurred.

## Compatibility with the Existing Lifecycle Planner

FounderOS already had a state-oriented v0.1 Planner used by Founder Setup, Discovery, and the CLI. PR-008 moved that implementation intact to `founderos_runtime.lifecycle_planner` and preserves its root-package exports (`founderos_runtime.Planner`, `ExecutionPlan`, and related helpers).

The new manifest/Workspace API lives at `founderos_runtime.planner`. Root aliases `WorkspacePlanner` and `WorkspaceExecutionPlan` make the distinction explicit. No existing lifecycle behavior changed.

## ExecutionPlan

An ExecutionPlan contains:

- exact Workflow ID and version metadata;
- ordered immutable `ExecutionStep` objects;
- exact required Agent ID/version references;
- required and produced Artifact declarations;
- Evaluation declarations;
- Approval declarations;
- non-authoritative transition request; and
- deterministic Planner metadata and step order.

`ExecutionStep` contains step ID/type/description, exact required Agent, Artifact inputs/outputs, and Evaluation/Approval flags. Query data is frozen; `to_dict()` returns a defensive serializable copy.

## Dependency and Checkpoint Planning

Artifact producers create dependencies for steps that consume their outputs. Required Workflow Artifacts are external roots. Each declared produced Artifact must have exactly one producer. Undeclared inputs, missing producers, and duplicate producers fail explicitly.

Topological ordering uses original manifest position and step ID as deterministic tie breakers. Cycles fail with `PlannerCircularDependencyError`.

Declared Evaluation or Approval requirements without a matching explicit step receive a synthetic `evaluation.<id>` or `approval.<id>` checkpoint. Existing explicit checkpoints are reused. Transition-request steps depend on Evaluation and Approval checkpoints, but only the State Machine may eventually apply transition intent.

## Relationships

- **Workspace:** the sole definition source. Planner reads defensive copies and performs no Workspace mutation.
- **Provider:** Planner may describe future Agent work but never invokes MockProvider or a real Provider.
- **Evaluation:** Evaluation declarations become checkpoints/flags; Planner does not run EvaluationRunner.
- **Approval:** Approval declarations become gates; Planner neither requests nor decides Approval.
- **Runtime Executor:** a future executor may consume an authorized plan, but must revalidate current definitions, runtime state, policy, evidence, and idempotency. PR-008 implements no executor.
- **Kernel:** Planner has no repositories, Events, persistence, or state-mutation authority.

## Determinism

Exact Workspace content and Workflow ID produce the same immutable plan. Agent and Artifact collections are sorted by ID. Steps use deterministic topological order. Checkpoints are inserted by sorted declaration ID. No time, randomness, Provider output, global registry, network state, or runtime state enters planning.

## Errors

- `PlannerWorkflowNotFoundError`
- `PlannerAgentNotFoundError`
- `PlannerArtifactReferenceError`
- `PlannerCircularDependencyError`
- `PlannerInvalidWorkflowError`

## Known Limitations and Recommended PR-009

Dependencies derive from Artifact flow and checkpoint type only; Workflow manifests do not yet expose explicit `depends_on`. Plans do not include retries, Activity policies, authorization requests, budgets, persisted run IDs, or current Project state. Synthetic checkpoints cover Artifact-subject requirements only.

PR-009 should define a read-only Plan Validation/Authorization Request foundation—or another explicitly approved narrow gate—before any executor is introduced. It must not execute steps, Providers, Tools, Approvals, or transitions.
