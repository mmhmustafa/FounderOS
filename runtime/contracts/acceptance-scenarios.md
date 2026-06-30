# Contract-Level Acceptance Scenarios

> **Status:** Specification implemented by `tests/test_acceptance_scenarios.py`

## Purpose

Provide technology-independent scenarios proving that an implementation conforms to the runtime contracts.

## AC-01 — Schema acceptance

**Given** a record satisfying a contract's required fields, formats, enums, and conditional requirements
**When** it is validated against that contract
**Then** validation succeeds without coercion or default insertion.

## AC-02 — Unknown and malformed data rejection

**Given** a record with an unknown property, wrong ID prefix, non-UTC timestamp, invalid SemVer, invalid status, or missing required field
**When** it is validated
**Then** validation fails before persistence and reports the failing contract path.

## AC-03 — Exact reference resolution

**Given** a reference containing kind, ID, and version or revision
**When** the target is resolved
**Then** kind/prefix, ownership scope, existence, and exact version/revision match
**And** no newer target is silently substituted.

## AC-04 — Founder Brief transition succeeds atomically

**Given** an active Project in `FOUNDER_SETUP` at revision `4`, a successful setup WorkflowRun, an approved Founder Brief, a passing Evaluation, and founder Approval
**When** `FOUNDER_SETUP → FOUNDER_BRIEF_COMPLETE` is requested with expected revision `4`
**Then** all guards pass
**And** the Transition is applied
**And** the Project moves to `FOUNDER_BRIEF_COMPLETE` at revision `5`
**And** exactly one `transition.applied` Event is appended
**And** all effects commit atomically.

## AC-05 — Missing approval preserves state

**Given** all evidence for AC-04 except an approved human Approval
**When** the transition is requested
**Then** it is rejected with `APPROVAL_MISSING`
**And** Project state and revision remain unchanged
**And** recovery requests the required approval.

## AC-06 — Failed evaluation requires new evidence

**Given** a required Evaluation with outcome `fail`
**When** a guarded transition is requested
**Then** it is rejected with `GUARD_FAILED`
**And** the failed Evaluation remains immutable
**And** recovery requires target rework and a new Evaluation.

## AC-07 — Stale concurrent mutation loses safely

**Given** a Project stored at revision `8`
**When** a transition requests expected revision `7`
**Then** it is rejected with `STALE_REVISION`
**And** no project mutation or duplicate effect occurs
**And** recovery requires reload and re-evaluation.

## AC-08 — Invalid route is rejected

**Given** a Project in `FOUNDER_SETUP`
**When** a direct transition to `VALIDATION_RUNNING` is requested
**Then** it is rejected with `INVALID_TRANSITION`
**And** the runtime returns only actions allowed from `FOUNDER_SETUP`.

## AC-09 — Retry creates history, not overwrite

**Given** a retryable failed AgentRun at attempt `1`
**When** policy permits another attempt
**Then** a new AgentRun is created with attempt `2` and the same correlation context
**And** the failed first run remains immutable
**And** no Project state transition occurs solely because a retry started.

## AC-10 — Retry exhaustion pauses progress

**Given** an AgentRun has reached the Workflow failure policy's maximum attempts
**When** the final attempt fails
**Then** the WorkflowRun becomes `failed`
**And** Project state is preserved
**And** a human recovery decision or a new WorkflowRun is required.

## AC-11 — Event replay is deterministic

**Given** a valid, gap-free Event stream for one Project
**When** it is replayed from sequence `1`
**Then** the derived state and revision equal the persisted Project snapshot
**And** a duplicate, gap, or out-of-order event fails integrity validation.

## AC-12 — Duplicate command is idempotent

**Given** a command whose correlation ID has already produced an applied transition
**When** the same command is received again
**Then** the prior result is returned or referenced
**And** no second transition, event, artifact, decision, or revision increment is created.

## AC-13 — Orchestrator cannot bypass boundaries

**Given** the Master Orchestrator requests a direct Project state write
**When** the request reaches the persistence boundary
**Then** it is rejected
**And** the orchestrator must submit a Transition through the State Machine.

## AC-14 — Knowledge is not sufficient evidence by itself

**Given** a Knowledge Base result with valid provenance
**When** a transition guard requires evidence
**Then** the result satisfies no guard until cited by an Artifact or Evaluation
**And** the cited content digest and source remain traceable.

## Milestone 3 Result

All scenarios above have executable positive, negative, concurrency, lifecycle, replay, idempotency, and transactional coverage in the Runtime Foundation test suite.
