# FounderOS Journey Runner

## Purpose

The Journey Runner is the first deterministic, end-to-end orchestration component over v0.3 definitions. Given a read-only `Workspace` and Workflow ID, it asks the Workspace Planner for one immutable `ExecutionPlan` and walks that plan exactly once in order.

Agent tasks use only `MockProvider`. Evaluation checkpoints use the deterministic `EvaluationRunner`. Generated Artifacts, Evaluation results, and logs exist only inside the returned immutable `JourneyResult`.

```python
from founderos_runtime.journey import JourneyRunner
from founderos_runtime.workspace import Workspace

workspace = Workspace.load("path/to/project")
result = JourneyRunner(workspace).run("wfl_...")
```

## Planner Versus Journey Runner

The Planner decides. It resolves definitions and produces a deterministic plan without doing work.

The Journey Runner performs the narrow in-memory journey described by that existing plan. It never replans during a run. It does not infer alternate steps, retry, branch, reorder, or modify the plan.

## Not the Production Runtime Executor

This runner is a deterministic platform harness, not the future production Runtime Executor. It has no durable Activities, authorization enforcement, persistence, leases, retries, compensation, human interaction, parallelism, Project state, Kernel repositories, or Event recording.

Approval, transition-request, and Activity-request steps are explicitly logged as skipped because executing them would cross those missing boundaries. A successful Journey result therefore means the in-scope deterministic steps completed; it does not mean a human approved anything or Project state changed.

## Execution Semantics

- The Planner is called once per run.
- Required Workflow Artifacts are represented as deterministic in-memory input references because the API accepts no Artifact payloads.
- `agent_task` steps call `MockProvider` with exact Workflow, step, Agent, input-reference, correlation, and idempotency metadata.
- Provider output is assigned to each declared output Artifact in memory.
- `evaluation` steps run after their Artifact dependencies and retain complete `EvaluationResult` values.
- Required evaluations currently enforce a critical non-null subject floor plus Evaluation Runner's built-in non-empty check.
- A failed critical finding stops the Journey immediately and returns a failed result.
- Local human-input and Artifact-creation declarations complete deterministically without I/O.
- Approval, transition, and Activity execution remain skipped and visible in the log.

## Relationships

- **Workspace:** supplies defensive validated Workflow and Agent definitions. It is never mutated.
- **Planner:** supplies the complete ordered plan. Journey Runner does not plan or replan.
- **Mock Provider:** the only accepted Provider implementation. No network or API keys are used.
- **Evaluation:** assesses in-memory Artifact values deterministically. No persisted runtime Evaluation record is created.
- **Persistence:** future execution must persist runs, Activities, results, and Events through authorized Kernel boundaries. PR-009 writes nothing.

## JourneyResult

`JourneyResult` contains Workflow ID, status, completed and skipped step IDs, Evaluation results, generated Artifacts, an ordered execution log, and deterministic metadata. Nested mappings are frozen and `to_dict()` returns a defensive serializable copy.

## Known Limitations

Rubric references are not loaded, required input Artifact content is unavailable, Provider failures currently raise a typed Journey plan/execution error, and the runner supports only sequential synchronous execution. Approval or transition completion cannot be claimed.

## Recommended PR-010

Add Plan Validation and Authorization Request derivation before expanding this harness toward executable side effects. Provider invocation beyond the in-process Mock Provider must additionally pass through RFC-0001 durable Activity boundaries. Do not add real Providers, Tools, persistence, or Kernel mutation in that PR.

