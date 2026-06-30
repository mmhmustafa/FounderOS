# Master Orchestrator

> **Status:** Specification complete; executable implementation not started
>
> **Role:** Single user-facing entry point and thin runtime facade
>
> **Depends on:** `architecture/FounderOS_Architecture_Specification_v1.0.md`, `runtime/state-machine.md`, and `runtime/contracts/`

## Purpose

The Master Orchestrator coordinates FounderOS runtime services. It does not perform specialist work, own domain knowledge, or mutate project state without validated runtime operations.

## Responsibilities

1. Accept a user command or continuation request.
2. Load the current project state through the Project State service.
3. Ask the Runtime Planner for a read-only ExecutionPlan.
4. Present required human approvals or missing inputs.
5. Delegate specialist work through the Agent Registry.
6. Submit produced artifacts to validation and quality gates.
7. Request state transitions through the State Machine.
8. Record decisions and return the updated project summary.

## Boundaries

The orchestrator must not:

- Contain specialist agent prompts or domain logic.
- Write project state directly.
- Bypass transition guards, quality gates, or human approvals.
- Treat generated output as an approved artifact.
- Invent missing evidence.
- Couple runtime behavior to a specific AI provider.

## Inputs

- User command or response
- Project identifier or resumable project state
- Authenticated runtime context when an application layer exists

## Outputs

- Current project status
- Valid next action or approval request
- References to artifacts, decisions, and workflow runs
- Explicit failure or recovery guidance

## Required Collaborators

- Project State
- Runtime Planner
- State Machine
- Workflow Engine
- Agent Registry
- Artifact Registry
- Decision Engine
- Quality Gate and Human Approval services
- Knowledge Base where a workflow explicitly requires it

Runtime Foundation collaborators and the Runtime Planner have implementations. `FounderSetupService` is the first narrow application-service consumer, and the CLI is its first user-facing adapter. A general orchestration facade, general workflow executor, and production persistence remain unimplemented.

## Coordination Sequence

```text
Receive command
→ Load project state and build ExecutionContext
→ Generate read-only ExecutionPlan
→ Collect missing input or approval
→ Invoke registered agent when required
→ Validate and register artifact
→ Record decision
→ Request guarded state transition
→ Return updated status and next action
```

## Failure Behavior

If a dependency fails, evidence is insufficient, validation fails, approval is denied, or a transition is invalid, the orchestrator must not advance state. It returns a structured failure and recovery action while preserving the last valid project state.

## Human Approval

Important decisions and state transitions require an explicit approval record. The executable runtime contracts will define which transitions require approval and who may grant it.

## Current Limitations

- No general-purpose executable orchestrator exists; the CLI exposes only Project inspection and Founder Setup.
- Runtime Foundation collaborators have in-memory implementations and a local application facade; production persistence is not implemented.
- The Runtime Planner is consumed by the Founder Setup vertical slice.
- Contract validation, concurrency revisions, basic retries, transition guards, recovery outcomes, and Events are implemented.
- Authentication, concrete authorization policy, storage technology, and observability remain undefined.

## Next Step

Harden runtime service and persistence import/export boundaries in Milestone 8.
