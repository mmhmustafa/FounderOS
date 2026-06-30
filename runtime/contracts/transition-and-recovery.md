# Transition Guards and Recovery Semantics

> **Status:** Contract specification

## Purpose

Define how FounderOS evaluates, applies, rejects, and recovers from state-transition requests.

## Transition Command and Outcome

A transition command must identify the project, current and target states, triggering action, actor, expected project revision, and relevant approvals. After validation and guard evaluation, the immutable applied or rejected outcome validates against `transition.schema.json` and includes every guard result.

## Guard Evaluation Order

Guards are evaluated in this order and stop at the first failure:

1. `project_active` — project status is `active`.
2. `project_revision_matches` — expected revision equals the stored revision.
3. `state_matches` — stored state equals `from_state`.
4. `transition_allowed` — the state contract permits `from_state` to `to_state`.
5. `workflow_succeeded` — the governing workflow run succeeded when the transition requires one.
6. `artifact_status` — required artifacts exist at exact versions and are approved.
7. `evaluation_passed` — required evaluations completed with `pass`; confidence-based gates require at least `0.70`.
8. `decision_recorded` — required decisions exist and have the required status.
9. `approval_granted` — every required human approval is current and approved.

Structural, referential, and authorization validation occurs before guard evaluation.

## Allowed Transitions

| From | To | Minimum exit evidence | Human approval |
|---|---|---|---|
| `NO_PROJECT` | `FOUNDER_SETUP` | Project created and founder-setup workflow queued | Not required |
| `FOUNDER_SETUP` | `FOUNDER_BRIEF_COMPLETE` | Approved Founder Brief and successful setup workflow | Required |
| `FOUNDER_BRIEF_COMPLETE` | `DISCOVERY_RUNNING` | Active Discovery workflow run | Required to begin lifecycle module |
| `DISCOVERY_RUNNING` | `OPPORTUNITY_SELECTED` | Approved Opportunity Report and approved opportunity decision | Required |
| `OPPORTUNITY_SELECTED` | `VALIDATION_RUNNING` | Active Validation workflow run | Required |
| `VALIDATION_RUNNING` | `VALIDATION_PASSED` | Approved Validation Report and passing evidence evaluation | Required |
| `VALIDATION_RUNNING` | `DISCOVERY_RUNNING` | Approved no-go/pivot decision with rationale | Required |
| `VALIDATION_PASSED` | `PRODUCT_DESIGN_RUNNING` | Active Product Design workflow run | Required |
| `PRODUCT_DESIGN_RUNNING` | `PRD_COMPLETE` | Approved PRD and MVP-scope decision | Required |
| `PRD_COMPLETE` | `ARCHITECTURE_RUNNING` | Active Engineering workflow run | Required |
| `ARCHITECTURE_RUNNING` | `ARCHITECTURE_COMPLETE` | Approved architecture, database, API, and security artifacts | Required |
| `ARCHITECTURE_COMPLETE` | `AI_DESIGN_RUNNING` | Active AI Design workflow run | Required |
| `AI_DESIGN_RUNNING` | `AI_ARCHITECTURE_COMPLETE` | Approved AI architecture and evaluation plan | Required |
| `AI_ARCHITECTURE_COMPLETE` | `DEVELOPMENT_PLANNING` | Active Development Planning workflow run | Required |
| `DEVELOPMENT_PLANNING` | `SPRINT_READY` | Approved sprint plan and implementation backlog | Required |
| `SPRINT_READY` | `MVP_BUILDING` | Build authorization approval | Required |
| `MVP_BUILDING` | `QA_RUNNING` | MVP scope complete and QA workflow active | Required |
| `QA_RUNNING` | `READY_FOR_BETA` | Passing test, security, AI-evaluation, and deployment-readiness evaluations | Required |
| `READY_FOR_BETA` | `LAUNCH_RUNNING` | Approved beta launch, GTM, sales, and support plans | Required |
| `LAUNCH_RUNNING` | `CUSTOMERS_ACQUIRED` | Recorded customer evidence and acquisition decision | Required |
| `CUSTOMERS_ACQUIRED` | `CEO_REVIEW` | Active CEO Review workflow run | Required |
| `CEO_REVIEW` | `SCALING` | Approved CEO Review and scaling decision | Required |

No other transition is valid in contract version `1.x`.

## Atomic Apply Contract

An applied transition must atomically:

1. Persist the immutable Transition as `applied`.
2. Append `transition.applied` as the next project Event sequence.
3. Update the Project's `current_state`.
4. Increment Project `revision` exactly once.
5. Update `last_event_sequence`, `updated_at`, and `next_action`.

If any write fails, none of these effects may become visible.

## Rejection Contract

A rejected transition:

- Never changes Project `current_state` or `revision`.
- Persists the Transition as `rejected` with a stable rejection code.
- Appends `transition.rejected` when event persistence is available.
- Returns one actionable recovery instruction.
- Does not silently retry authorization, approval, evidence, or semantic failures.

## Recovery Matrix

| Failure | State behavior | Workflow behavior | Required recovery |
|---|---|---|---|
| Invalid transition pair | Preserve | Pause request | Re-resolve allowed action from current state |
| Stale project revision | Preserve | Preserve | Reload project and resubmit against latest revision |
| Missing/invalid artifact | Preserve | `waiting_for_input` | Produce, correct, review, and approve artifact |
| Evaluation failed | Preserve | `waiting_for_input` | Rework target and create a new evaluation; never overwrite result |
| Approval pending | Preserve | `waiting_for_approval` | Await authorized human decision |
| Approval rejected | Preserve | Pause | Rework subject or record an explicit alternative decision |
| Agent/dependency transient failure | Preserve | Retry within configured attempt limit | Append failure event and retry as a new AgentRun attempt |
| Retry limit exhausted | Preserve | `failed` | Request human recovery decision or start a new WorkflowRun |
| Persistence failure | Preserve last committed state | Unknown until reloaded | Reload authoritative state; use correlation ID to prevent duplicate effects |
| Authorization failure | Preserve | Pause | Obtain authorized actor; never auto-escalate privileges |

## Idempotency and Replay

- Repeating a command with the same correlation ID must not create duplicate applied effects.
- Events are replayed strictly by project sequence.
- Duplicate or skipped sequence numbers are integrity errors.
- Replaying events must produce the same Project state and revision.
- Recovery creates new records linked by correlation/causation; historical records remain immutable.

## Risks

- Full authorization policy is deferred.
- Compensation for external side effects requires tool-specific contracts in a later milestone.
- Concurrent workflows beyond one state-owning workflow per project require future design.

## Runtime Implementation

`src/founderos_runtime/state_machine.py` enforces the allowed routes, ordered guards, applied/rejected outcomes, optimistic revision checks, human Approval evidence, idempotent correlations, and rollback behavior.

## Next Step

Use the State Machine in the first Founder Brief vertical slice.
