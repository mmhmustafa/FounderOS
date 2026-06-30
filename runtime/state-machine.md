# FounderOS State Machine

> **Status:** In-memory Runtime Foundation implemented
>
> **Derived from:** `architecture/FounderOS_Architecture_Specification_v1.0.md`
>
> **Machine contracts:** `runtime/contracts/state.schema.json` and `runtime/contracts/transition.schema.json`

## Purpose

The State Machine is the sole authority allowed to change `Project.current_state`. It evaluates transition requests against structural validation, typed references, allowed routes, evidence, evaluations, decisions, approvals, authorization, and optimistic concurrency.

## State Catalogue

```text
NO_PROJECT
FOUNDER_SETUP
FOUNDER_BRIEF_COMPLETE
DISCOVERY_RUNNING
OPPORTUNITY_SELECTED
VALIDATION_RUNNING
VALIDATION_PASSED
PRODUCT_DESIGN_RUNNING
PRD_COMPLETE
ARCHITECTURE_RUNNING
ARCHITECTURE_COMPLETE
AI_DESIGN_RUNNING
AI_ARCHITECTURE_COMPLETE
DEVELOPMENT_PLANNING
SPRINT_READY
MVP_BUILDING
QA_RUNNING
READY_FOR_BETA
LAUNCH_RUNNING
CUSTOMERS_ACQUIRED
CEO_REVIEW
SCALING
```

State codes are stable names. Persisted State definitions use immutable `sta_` IDs and Semantic Versions.

## Allowed Routes

The primary route follows the catalogue order. The only recovery route in contract version `1.x` is:

```text
VALIDATION_RUNNING -> DISCOVERY_RUNNING
```

No state may be skipped. Full evidence and approval requirements for every route are authoritative in `runtime/contracts/transition-and-recovery.md`.

## Universal Guards

Every request must prove:

1. The project is active.
2. The expected Project revision matches storage.
3. The recorded current state matches `from_state`.
4. The requested route is allowed.
5. The governing WorkflowRun succeeded when required.
6. Required artifacts exist at exact versions and are approved.
7. Required evaluations passed.
8. Required decisions are recorded.
9. Required human approvals are approved and current.

Authorization, schema validation, and reference integrity are prerequisites rather than bypassable guards.

## Failure Behavior

A failed guard rejects the Transition and preserves Project state and revision. The rejection records a stable code and recovery action. The runtime must never partially apply a transition or infer approval from an artifact, decision, confidence score, or agent output.

## Recovery

Recovery corrects the failed prerequisite and submits a new transition request. It never edits historical Evaluations, Approvals, Transitions, AgentRuns, or Events. Retries create new attempts; stale requests reload the authoritative Project revision.

## Atomic Mutation

An applied transition atomically persists the Transition, appends its Event, changes Project state, increments Project revision exactly once, and updates the next action. Any persistence failure exposes none of these effects.

## Inputs

- Valid Transition request
- Authoritative Project record
- Exact referenced definitions and runtime evidence
- Authorized actor context

## Outputs

- Applied or rejected Transition
- Updated Project only when applied
- Ordered Event
- Explicit rejection code and recovery action when rejected

## Dependencies

- `runtime/contracts/README.md`
- `runtime/contracts/transition-and-recovery.md`
- `runtime/contracts/persistence-boundaries.md`

## Risks

- The concrete authorization policy is not yet defined.
- Contract version `1.x` permits one state-owning workflow at a time.
- Full lifecycle artifacts remain planned and are not implemented by this specification.

## Implementation

`src/founderos_runtime/state_machine.py` implements all 22 allowed routes, ordered guards, applied/rejected Transition records, exact evidence resolution, optimistic concurrency, human Approval checks, Event append, idempotency, and rollback.

## Next Step

Exercise the `FOUNDER_SETUP -> FOUNDER_BRIEF_COMPLETE` path through the first vertical-slice application service.
