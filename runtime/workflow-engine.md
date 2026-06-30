# Workflow Engine

> **Status:** Basic in-memory lifecycle implemented; Founder Setup is explicitly coordinated, but no general step executor exists
>
> **Schemas:** `runtime/contracts/workflow.schema.json` and `runtime/contracts/workflow-run.schema.json`

## Purpose

The Workflow Engine executes version-pinned Workflow definitions as durable WorkflowRuns. It coordinates steps and records progress; it does not approve outputs or mutate Project state.

The Runtime Planner selects and recommends workflows before execution. A recommendation never creates a WorkflowRun; an authorized application service must explicitly request one.

## Inputs

- Active Project reference and current state
- Exact active Workflow definition version
- Required input artifact references
- Authorized start/resume/cancel command with correlation ID

## Outputs

- WorkflowRun and ordered status Events
- AgentRun, Evaluation, Approval, Artifact, and Decision requests
- Transition request after successful completion

## Definition Rules

1. Published Workflow versions are immutable.
2. A WorkflowRun pins one exact Workflow version.
3. Step IDs are unique within a Workflow and sequence numbers are deterministic.
4. The entry state must equal the Project state at start.
5. Requested exit state must be declared by the Workflow and allowed by the State Machine.
6. Failure policy defines bounded attempts and terminal behavior.

## Run State Transitions

```text
queued -> running
running -> waiting_for_input | waiting_for_approval | succeeded | failed | cancelled
waiting_for_input -> running | failed | cancelled
waiting_for_approval -> running | failed | cancelled
```

Terminal statuses are `succeeded`, `failed`, and `cancelled`. Terminal WorkflowRuns never resume; recovery starts a new linked run.

## Execution Boundaries

- `invoke_agent` creates an AgentRun through the Agent Registry.
- `evaluate` creates a new immutable Evaluation.
- `request_approval` creates an Approval; the engine waits for a human decision.
- `record_decision` delegates to the Decision Engine.
- `request_transition` delegates to the State Machine only after workflow success.
- External model/tool calls occur outside Project mutation transactions.

## Idempotency

The same start command correlation ID returns the existing WorkflowRun. A completed step is not repeated unless a new run or retry attempt is explicitly created.

## Dependencies

- Definition and runtime schemas in `runtime/contracts/`
- Agent, Artifact, Decision, Evaluation, and Approval boundaries
- State Machine and Project State

## Failure and Recovery

Transient failures create new attempts within policy limits. Input/evidence failures wait for corrected input. Approval failures wait or pause. Exhausted retries mark the run failed and require a human recovery decision or new WorkflowRun.

## Risks

- Parallel branches and multiple state-owning workflows are deferred.
- Scheduling, queues, and worker leases are implementation decisions.

## Implementation

`src/founderos_runtime/runs.py` implements validated WorkflowRun creation and lifecycle transitions with revisions and ordered lifecycle Events. It does not execute Workflow steps.

## Executable Slice

`FounderSetupService` coordinates the five Founder Setup steps directly through existing services. This is deliberately not a general workflow interpreter.

## Next Step

Add correlated run diagnostics without expanding workflow execution.
