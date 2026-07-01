# FounderOS RFC-0001 Handoff

RFC-0001 — Durable Activity and Side-Effect Contracts is complete with **Proposed** status.

## Outcome

FounderOS now has a documented contract boundary for every future operation performed outside the Kernel, including AI Providers, Tools, browsers, Git, shells, Python, Docker, MCP, cloud APIs, external filesystems, networks, notifications, and human-approval interaction.

No executor, scheduler, queue, worker, Provider, Tool, browser action, shell command, external API call, LLM call, or runtime Activity behavior was implemented.

The current FounderOS Kernel, repositories, persistence formats, Events, schemas, CLI, workflows, and tests remain behaviorally unchanged.

## Architectural rule

Every future external operation must:

1. begin as a durable ActivityRequest;
2. be authorized before scheduling;
3. be recorded by a future Kernel Activity service;
4. execute outside every Kernel mutation transaction;
5. return an immutable ActivityResult and external receipt;
6. be validated and recorded by the Kernel with an authoritative Event; and
7. be consumed later through normal authorized Kernel commands.

Executors may not mutate Project, WorkflowRun, Artifact, Decision, Evaluation, Approval, Transition, Activity, or Event storage directly.

## RFC document

```text
docs/rfcs/RFC-0001-durable-activity-and-side-effect-contracts.md
```

The RFC defines:

- Activity
- ActivityRequest
- ActivityResult
- ActivityRecord
- ActivityStatus
- ActivityType
- attempt and lease semantics
- RetryPolicy
- ActivityPolicy
- IdempotencyKey
- TimeoutPolicy
- Cancellation
- Compensation
- ActivityAuditRecord
- result consumption
- failure classification
- replay and reconciliation
- security invariants
- future acceptance scenarios

## Activity lifecycle

```text
requested
    |
    +-- authorization denied --> failed
    |
authorized
    |
scheduled
    |
executing
    |
    +-- succeeded
    +-- failed
    +-- cancelled
    +-- cancellation_requested --> succeeded | failed | cancelled
    |
recorded
    |
later Workflow command consumes the recorded result
```

`recorded` means the Kernel durably accepted the terminal result and Event. The ActivityResult preserves whether the external outcome succeeded, failed, or was cancelled.

## Activity categories

- AI
- Filesystem
- Network
- Git
- Browser
- Shell
- Python
- Docker
- Cloud
- Notification
- Human Approval interaction

These are reserved contract categories only. None is executable.

Human Approval interaction cannot approve itself or replace the Kernel Approval service and Approval record.

## Failure semantics

The RFC defines:

- retryable
- non-retryable
- compensatable
- timeout
- authorization denied
- validation failure
- external failure
- cancelled
- ambiguous outcome
- lease lost
- retry exhausted

Each failure records whether an external effect is known to have occurred, known not to have occurred, or is unknown.

Unknown and ambiguous write outcomes fail closed.

## Idempotency and replay

FounderOS does not claim exactly-once external execution.

It targets effectively-once behavior through:

- durable intent;
- stable Project/Activity/operation idempotency scope;
- canonical request fingerprint;
- one logical Activity identity across all attempts;
- bounded retries;
- external idempotency tokens when supported;
- immutable result/receipt digests;
- duplicate-result conflict checks; and
- explicit reconciliation for uncertain outcomes.

Event and Workflow replay reconstruct Activity state and reuse recorded results. Replay never invokes an ActivityExecutor.

## Retry model

- Maximum attempts include the first attempt.
- Attempts are immutable history under one logical Activity.
- Retry requires both a declared retryable failure and effect-safe replay.
- Input, target, policy, or fingerprint changes require a new request and key.
- Non-idempotent, security-sensitive, or ambiguous writes are never blindly retried.
- Retry exhaustion records a terminal failure and preserves every attempt.

## Timeout and cancellation

Timeouts are explicit for queue, execution, and total duration.

A timeout requests cancellation but does not prove the external system stopped. Ambiguous writes require reconciliation.

Cancellation before execution prevents executor invocation. Cancellation during execution is cooperative. A successful effect cannot be erased by cancellation.

## Compensation

Compensation is always a separate linked Activity with:

- fresh authorization;
- any required human Approval;
- its own idempotency key;
- its own attempts and result;
- its own Events; and
- an explicit reference to the original Activity and receipt.

Compensation never rewrites or deletes original history and does not imply perfect reversal.

## Placeholder interfaces

RFC-0001 specifies semantic interfaces for:

- ActivityRegistry
- ActivityExecutor
- ActivityService
- ActivityPolicyEvaluator
- ActivityAuditReader

No Python interfaces or runtime classes were added.

## Contracts added

Under `runtime/contracts/activity/`:

- `activity-common.schema.json`
- `retry-policy.schema.json`
- `activity-policy.schema.json`
- `activity-request.schema.json`
- `activity-result.schema.json`
- `activity-record.schema.json`
- `activity-audit-record.schema.json`
- `README.md`

These Draft 2020-12 contracts are intentionally outside the active recursive scope of `ContractRegistry`.

## Observability

The RFC reserves authoritative Activity Events including:

- `activity.requested`
- `activity.authorized`
- `activity.authorization_denied`
- `activity.scheduled`
- `activity.started`
- `activity.cancellation_requested`
- `activity.succeeded`
- `activity.failed`
- `activity.cancelled`
- `activity.retry_scheduled`
- `activity.result_recorded`
- `activity.result_rejected`
- `activity.compensation_requested`
- `activity.reconciliation_required`

No current Event is emitted. Future ActivityAuditRecords must resolve to authoritative Events and preserve command-to-result correlation.

## ADR

Added:

```text
architecture/decisions/ADR-002-isolate-side-effects-from-kernel.md
```

ADR-002 records why external execution must remain outside Kernel transactions and why Workflows, Agents, Providers, Tools, and workers cannot become alternate mutation/Event authorities.

## Architecture decisions proposed

- D-059 — External operations begin as durable ActivityRequests and execute outside Kernel transactions.
- D-060 — Retries preserve one logical Activity and idempotency identity.
- D-061 — FounderOS targets effectively-once rather than exactly-once behavior.
- D-062 — Ambiguous writes require reconciliation; compensation is a separate Activity.
- D-063 — Executors return results while a future Kernel Activity service owns records and Events.
- D-064 — Event and Workflow replay never invokes executors.

These decisions remain proposed with RFC-0001 rather than falsely marked as implemented.

## Files changed

- Added `docs/rfcs/RFC-0001-durable-activity-and-side-effect-contracts.md`.
- Added `architecture/decisions/ADR-002-isolate-side-effects-from-kernel.md`.
- Added `runtime/contracts/activity/` and seven schemas.
- Updated `runtime/contracts/README.md`.
- Updated `runtime/service-boundaries.md`.
- Updated `runtime/workflow-engine.md`.
- Updated `runtime/observability.md`.
- Updated `architecture/FounderOS_v0.2_Blueprint.md`.
- Updated `.ai/BUILD_ROADMAP.md`.
- Updated `.ai/CURRENT_SPRINT.md`.
- Updated `.ai/PROJECT_CONTEXT.md`.
- Updated `.ai/DECISIONS.md`.
- Updated `README.md`.
- Updated `CHANGELOG.md`.
- Added `RFC_0001_HANDOFF.md`.

## Verification

- All 12 authorization and Activity placeholder schemas passed Draft 2020-12 meta-validation.
- Six representative Activity policy/request/result/record/audit records validated.
- Active runtime schema count remains unchanged at 15.
- Existing complete suite passed: 86 tests and 5 subtests.
- No source or test file changed.
- No runtime behavior changed.
- No external side effect was executed.

## Remaining risks

- RFC-0001 remains Proposed and requires acceptance before implementation.
- Authorization and Activity contracts are not enforced.
- No Activity repository, Kernel service, persistence, queue, scheduler, worker, lease, outbox/inbox, or reconciliation UI exists.
- Exactly where AuthorizationDecision reuse expires across retries remains open.
- Result-content retention and Artifact-content integration remain unresolved.
- External systems without idempotency or queryable receipts will require manual recovery.
- The future implementation roadmap must place authorization and Activity enforcement before executable Provider or Tool work.

## Recommended next milestone

Proceed with **Milestone 12E — Minimal First-Party App Package Contract** only after accepting RFC-0001 and confirming the future authorization/Activity enforcement gate.

Milestone 12E must remain contract-only: no App registry runtime, Provider, Tool, Validation behavior, or external execution.
