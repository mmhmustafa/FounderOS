# FounderOS Milestone 4 — Complete Handoff

## Outcome

Milestone 4 — Runtime Planner Engine is complete.

The package includes the full current working-tree implementation, including the uncommitted Milestone 3 Runtime Foundation on which the Planner depends.

## Files added for Milestone 4

- `src/founderos_runtime/execution_context.py`
- `src/founderos_runtime/planner.py`
- `src/founderos_runtime/planning_rules.py`
- `tests/test_planner.py`
- `runtime/planner.md`

## Files updated for Milestone 4

- `src/founderos_runtime/__init__.py`
- `src/founderos_runtime/state_machine.py`
- `README.md`
- `CHANGELOG.md`
- `.ai/PROJECT_CONTEXT.md`
- `.ai/BUILD_ROADMAP.md`
- `.ai/CURRENT_SPRINT.md`
- `.ai/DECISIONS.md`
- `runtime/master-orchestrator.md`
- `runtime/workflow-engine.md`
- `architecture/FounderOS_Architecture_Specification_v1.0.md`

## Planner design

### ExecutionContext

An immutable read model containing:

- Project ID
- Current state
- Approved completed artifact types
- Pending artifact types
- Available active Agent definitions
- Available active Workflow definitions
- Decision summaries
- Risks
- Ordered Event summaries
- Current next action

`ExecutionContextBuilder` builds this context using defensive repository reads.

### ExecutionPlan

An immutable planning result containing:

- Current state
- Recommended workflow
- Required artifacts
- Missing artifacts
- Recommended agent roles
- State Machine-allowed transitions
- Blocking reason
- Quality-gate requirements
- Next-state candidate
- Deterministic confidence score

### ArtifactPlanner

- Compares state-specific requirements with approved Project artifacts.
- Ignores draft, rejected, deprecated, missing, and cross-project artifacts.
- Returns required and missing artifact types.

### WorkflowSelector

- Selects the canonical workflow for the current state.
- Verifies the next-state candidate is allowed by the authoritative State Machine.
- Returns a clear blocked reason when approved prerequisite artifacts are missing.
- Does not create a WorkflowRun.

### AgentRouter

- Maps workflows to explicit, stable agent-role tuples.
- Is deterministic.
- Does not invoke agents, tools, models, or LLMs.

### Planner

- Combines ExecutionContext, ArtifactPlanner, WorkflowSelector, AgentRouter, and State Machine route requirements.
- Produces one complete ExecutionPlan.
- Never creates Projects, Runs, Events, Transitions, Artifacts, Decisions, Evaluations, or Approvals.
- Never changes Project state.

## Routing coverage

- 22 known lifecycle states
- 22 authoritative State Machine routes
- One planning rule per known state
- State Machine remains authoritative for allowed transitions and guard requirements
- Planner metadata remains authoritative only for workflow names, required planning artifacts, and agent-role recommendations

## Tests added

Thirteen planner tests cover:

- `NO_PROJECT` recommends Founder Setup Workflow
- `FOUNDER_SETUP` blocks without an approved Founder Brief
- Founder Setup unblocks with an approved Founder Brief
- `FOUNDER_BRIEF_COMPLETE` recommends Discovery Workflow
- `DISCOVERY_RUNNING` blocks without Opportunity Report
- `OPPORTUNITY_SELECTED` recommends Validation Workflow
- Unknown state rejection
- Missing artifacts, recommended agents, transitions, and quality gates in ExecutionPlan
- Planner non-mutation of Project, Event, and Transition repositories
- Deterministic repeated planning
- ExecutionContext runtime inventory construction
- Draft artifacts excluded from completed evidence
- Every known state has one State Machine-consistent planning rule

## Verification

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe -m pip check
```

Results:

- **32 tests passed**
- **No broken requirements found**
- **22 planner rules, 22 known states, and 22 State Machine routes verified**
- **No whitespace errors detected**

## What works now

- Contracts load and validate through JSON Schema Draft 2020-12.
- Projects and runtime records can be held in validated in-memory repositories.
- Project revisions, ordered Events, guarded transitions, replay, and run lifecycles work.
- ExecutionContext can be built from repository state.
- ExecutionPlan can be generated deterministically for every known state.
- Missing approved artifacts block progress with explicit reasons.
- Workflows and agent roles are recommended without execution.
- Allowed transitions and quality gates come from the State Machine.
- Unknown states are rejected.
- Planning is proven not to mutate repositories.

## Remaining limitations

- Workflow and agent-role mappings are static code metadata.
- Available Agent and Workflow definitions are reported but not yet mandatory for a recommendation.
- Planning does not execute workflows or create runs.
- Confidence score `1.0` means deterministic rule confidence, not market/evidence confidence.
- Recovery branches are listed as allowed transitions, but the Planner chooses one primary route.
- Persistence remains in memory.
- Idempotency indexes remain process-local.
- Authentication, authorization, observability, and Knowledge Base implementation remain absent.
- No CLI, web UI, LLM integration, Discovery generation, Validation generation, or Product generation exists.

## Important decisions

- The Runtime Planner is deterministic and read-only.
- Planning and execution are separate boundaries.
- Planner recommendations never imply approval or a valid transition.
- State Machine routes and guard requirements remain authoritative.
- Workflow and agent-role mappings are explicit static metadata for Milestone 4.

## Recommended next milestone

Proceed with **Milestone 5 — First Executable Founder Brief Vertical Slice**:

- Create or resume a Project
- Consume the Planner recommendation
- Execute only Founder Setup
- Produce and persist a Founder Brief
- Require human review and Approval
- Apply the guarded transition to `FOUNDER_BRIEF_COMPLETE`
- Verify durable resume and deterministic replay

Do not implement Discovery, Validation, Product, general-purpose CLI, web UI, or LLM integration during Milestone 5.

## Git status

Milestones 3 and 4 remain present but uncommitted because repository-write approval was unavailable. This ZIP contains the complete working-tree output, not merely the last committed snapshot.

## Previously displayed handoff text

> Milestone 4 is complete.
>
> Files added:
>
> - `execution_context.py`
> - `planner.py`
> - `planning_rules.py`
> - `test_planner.py`
> - `runtime/planner.md`
>
> Planner design:
>
> - Immutable `ExecutionContext` and `ExecutionPlan`
> - Deterministic `ArtifactPlanner`, `WorkflowSelector`, and `AgentRouter`
> - Reuses authoritative State Machine routes and guard requirements
> - Covers all 22 states
> - Never mutates runtime state
>
> Testing:
>
> - 13 planner tests added
> - Full suite: **32/32 passing**
> - Dependencies: healthy
> - No CLI, UI, LLM calls, or lifecycle content generation added
>
> What works:
>
> - Recommends Founder Setup, Discovery, Validation, and later workflows
> - Identifies missing approved artifacts
> - Returns clear blocking reasons
> - Recommends agent roles
> - Exposes allowed transitions and quality gates
> - Rejects unknown states
> - Produces deterministic plans
>
> Remaining limitations:
>
> - Workflow and agent mappings are static.
> - Planning does not execute workflows.
> - Available definitions are informational rather than mandatory.
> - Persistence remains in-memory.
> - Confidence is deterministic routing confidence, not evidence confidence.
>
> Recommended next milestone: **Milestone 5 — First Executable Founder Brief Vertical Slice**.
>
> Milestones 3 and 4 remain safely present but uncommitted because repository-write approval was unavailable.
