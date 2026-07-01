# RFC-0001: Durable Activity and Side-Effect Contracts

> **Status:** Proposed  
> **Milestone:** 12D  
> **Scope:** Architecture, contracts, interfaces, lifecycle, and documentation only  
> **Runtime status:** Not implemented or loaded by the current runtime

## Purpose

FounderOS must represent every operation performed outside the Kernel as a durable Activity before integrating AI Providers, Tools, browsers, GitHub, Docker, MCP, shells, cloud APIs, notifications, or other external systems.

The Kernel remains the sole authority for FounderOS runtime mutation. It records Activity intent, authorization evidence, scheduling state, results, retry decisions, failure facts, and authoritative Events. It never performs the external operation inside a Kernel transaction.

An ActivityExecutor performs the external operation outside the Kernel, then submits a structured result or failure back through the Activity boundary. Workflow coordination consumes only a result already validated and recorded by the Kernel.

## Goals

- Isolate nondeterministic and external side effects from Kernel transactions.
- Make intent, authorization, attempts, outcomes, and recovery auditable.
- Prevent duplicate effects when commands, workers, or result submissions are replayed.
- Define bounded retry, timeout, cancellation, compensation, and reconciliation semantics.
- Preserve Kernel, State Machine, Approval, authorization, Event, and audit authority.
- Support future local workers and distributed executors without requiring either now.

## Non-goals

RFC-0001 does not implement:

- Activity execution, queues, workers, leases, schedulers, or repositories;
- AI or LLM Provider adapters;
- Tool execution or Tool registry behavior;
- browser, shell, Python, Git, Docker, MCP, cloud, network, or filesystem operations;
- notification delivery;
- human Approval UI;
- authorization enforcement;
- database outbox/inbox infrastructure; or
- application, CLI, or Web behavior.

## Architectural Boundary

```text
Workflow coordination / application command
                    |
                    v
       Authorization boundary (future enforcement)
                    |
                    v
Kernel Activity service records immutable request + Event
                    |
                    v
       Scheduler/Executor boundary (outside Kernel)
                    |
                    v
        External system performs or rejects effect
                    |
                    v
Executor submits immutable result / failure / receipt
                    |
                    v
Kernel validates and records outcome + Event
                    |
                    v
Workflow consumes recorded result and requests later Kernel mutations
```

The external operation never occurs while a Project, Activity, Event, or other Kernel transaction is open. An executor cannot write repositories, append Events, approve output, or mutate `Project.current_state`.

## Core Concepts

### Activity

A logical, durable unit of work that may observe or affect a system outside the Kernel. One Activity is identified by one immutable ActivityRequest and one idempotency identity. Retries are attempts of the same Activity, not new logical Activities.

### ActivityRequest

Immutable intent describing:

- exact Project and requesting Actor context;
- Activity category and operation;
- normalized target descriptor;
- immutable input reference and digest rather than large/raw content;
- idempotency key;
- ActivityPolicy and exact contract versions;
- correlation and causation;
- optional compensation linkage; and
- request timestamp.

Creating a request records intent only. It does not authorize, schedule, or execute the operation.

### ActivityResult

Immutable submitted outcome for one exact Activity attempt. It records outcome, timing, output references/digests, external receipt, cost/usage metadata where applicable, and structured failure information. It cannot mutate Project state or become an approved Artifact by itself.

### ActivityStatus

The mutable ActivityRecord lifecycle state:

- `requested`
- `authorized`
- `scheduled`
- `executing`
- `cancellation_requested`
- `succeeded`
- `failed`
- `cancelled`
- `recorded`

`recorded` means the Kernel durably accepted a terminal ActivityResult and its authoritative Event. The result retains the terminal outcome (`succeeded`, `failed`, or `cancelled`), so moving the record to `recorded` does not erase what happened.

Kernel consumption is not another Activity status. A WorkflowRun or application command references the recorded result in a subsequent authorized Kernel command.

### ActivityType

A stable category describing the external execution family:

- `ai`
- `filesystem`
- `network`
- `git`
- `browser`
- `shell`
- `python`
- `docker`
- `cloud`
- `notification`
- `human_approval`

The category is routing and policy metadata, not an executor implementation. `human_approval` may represent future delivery/wait interaction only; the authoritative Approval and decision remain Kernel Approval records.

### ActivityRecord

The mutable Kernel-owned coordination record for one logical Activity. It references the immutable request, exact policy, authorization evidence, current status/revision, attempt count, active lease metadata, terminal result, timestamps, and correlation.

### Attempt

One bounded execution try for an Activity. Attempt numbers start at `1` and increase monotonically. Attempts preserve history and never overwrite prior failures. A retry reuses the Activity ID and idempotency key.

### RetryPolicy

Immutable policy defining maximum attempts, retryable failure classes, backoff calculation, maximum delay, and whether external ambiguity prohibits automatic retry.

### IdempotencyKey

A caller-supplied stable identifier for one logical intent within an explicit scope. The same scope/key with the same canonical request fingerprint returns the existing Activity. Reusing it with different intent is a conflict.

### TimeoutPolicy

Bounded queue, execution, and total Activity durations. A timeout requests cancellation and records a `timeout` failure; it does not prove an external system stopped. If external completion is uncertain, the Activity requires reconciliation.

### Cancellation

A durable request to stop future or ongoing work. Cancellation is cooperative once execution begins. It cannot erase a successful external effect. Terminal outcome races are resolved by the first valid Kernel-recorded terminal result, while late submissions remain auditable and cannot replace it.

### Compensation

A separate, explicitly authorized Activity intended to mitigate a prior successful side effect. It references `compensates_activity_id`, has its own idempotency key, attempts, result, authorization, and Events. Compensation never deletes or rewrites the original history and is not assumed to restore the world perfectly.

### ActivityPolicy

Immutable execution constraints combining effect classification, RetryPolicy, TimeoutPolicy, cancellation support, authorization/Approval requirements, compensation declaration, and budget limits.

### ActivityAuditRecord

Immutable Activity-specific audit fact linked to an authoritative FounderOS Event. It contains lifecycle transition, attempt, Actor, correlation, timestamps, sanitized metadata, and the Event reference. It cannot independently mutate status or authorize execution.

## Effect Classification

ActivityPolicy declares one effect class:

| Effect class | Meaning | Automatic retry default |
|---|---|---|
| `none` | Pure external computation with no durable external mutation | Allowed for declared retryable failures |
| `read_only` | Reads external state without intended mutation | Allowed for declared retryable failures |
| `idempotent_write` | External write supports a stable idempotency token or equivalent | Allowed only with the same external idempotency key |
| `reversible_write` | Write has an explicit compensation operation | Retry only when outcome is known not to have occurred |
| `non_idempotent_write` | Duplicate execution may create duplicate/unsafe effects | No blind automatic retry |
| `security_sensitive` | Operation affects credentials, access, security, or production trust | Explicit policy and human Approval; no implicit retry |

An operation may be both externally idempotent and security-sensitive; in that case the stricter security policy wins. The initial schema uses one primary effect class and separate Approval/compensation flags; future composition may extend it.

## Contract Inventory

Placeholder Draft 2020-12 schemas live under `runtime/contracts/activity/`:

- `activity-common.schema.json`
- `retry-policy.schema.json`
- `activity-policy.schema.json`
- `activity-request.schema.json`
- `activity-result.schema.json`
- `activity-record.schema.json`
- `activity-audit-record.schema.json`

The active `ContractRegistry` does not recurse into this directory. These contracts do not change current schema counts, repositories, persistence, Events, or runtime behavior.

## Placeholder Interfaces

These are semantic interfaces only:

```text
interface ActivityRegistry:
    resolve(activity_type, operation, contract_version) -> ActivityExecutorDescriptor

interface ActivityExecutor:
    execute(request, attempt_context) -> ActivityResult
    request_cancel(activity_id, attempt) -> CancellationAcknowledgement

interface ActivityService:
    request(ActivityRequest) -> ActivityRecord
    record_authorization(activity_id, AuthorizationDecisionRef) -> ActivityRecord
    schedule(activity_id) -> ActivityRecord
    claim(activity_id, lease_request) -> ActivityRecord
    submit_result(ActivityResult, lease_token) -> ActivityRecord
    request_cancellation(activity_id, reason) -> ActivityRecord
    schedule_retry(activity_id, retry_decision) -> ActivityRecord

interface ActivityPolicyEvaluator:
    classify_failure(ActivityResult, ActivityPolicy) -> RetryDecision

interface ActivityAuditReader:
    list(activity_id) -> ordered ActivityAuditRecord[]
```

Interface authority:

- ActivityRegistry is read-only and maps contracts to executor descriptors; it does not execute.
- ActivityExecutor performs only the external operation and returns a result.
- ActivityService is a future Kernel service and sole owner of ActivityRecord mutations and Activity Events.
- ActivityPolicyEvaluator is deterministic and performs no I/O.
- Executors never call Project State, State Machine, Artifact, Approval, Decision, Evaluation, or Event repositories directly.

## Lifecycle

### Primary lifecycle

```text
requested
    |
    +-- authorization denied ----------> failed
    |
    v
authorized
    |
    v
scheduled
    |
    +-- cancellation before claim -----> cancelled
    |
    v
executing
    |
    +-- success ------------------------> succeeded
    +-- terminal/retry-exhausted ------> failed
    +-- cooperative cancellation ------> cancelled
    +-- cancellation requested --------> cancellation_requested
                                               |
                                               +--> succeeded | failed | cancelled

succeeded | failed | cancelled
    |
    v
recorded
    |
    v
Kernel-validated result becomes available to a later Workflow command
```

### Transition rules

1. `requested -> authorized` requires an allowed exact AuthorizationDecision for the Activity Resource and Action.
2. Authorization denial records a failed result classified `authorization_denied`; no executor is selected.
3. `authorized -> scheduled` requires structurally valid input/policy and any required current Approval.
4. `scheduled -> executing` requires a single valid lease and increments attempt exactly once.
5. Executor completion proposes, but does not commit, a terminal outcome.
6. The Kernel validates the lease, attempt, result schema, and terminal-state race before accepting it.
7. Terminal outcome plus result and authoritative Event are committed atomically before status becomes `recorded`.
8. `recorded` Activities never execute again. Replay returns the recorded result.
9. Retries occur only before a terminal result is recorded and only within RetryPolicy.
10. Compensation is a new linked Activity, never a backward status transition.

## Failure Semantics

Every failure has a stable class, retry disposition, phase, safe diagnostic, and whether external outcome is known.

| Failure class | Default retry | Meaning and recovery |
|---|---|---|
| `retryable` | Policy bounded | Transient failure known to have produced no external effect, or safely idempotent replay |
| `non_retryable` | Never | Invalid operation, unsupported capability, permanent external rejection, or exhausted policy |
| `compensatable` | Separate Activity | Original side effect succeeded but mitigation is available and explicitly authorized |
| `timeout` | Conditional | Deadline expired; retry only if outcome is known absent or external idempotency makes replay safe |
| `authorization_denied` | Never automatically | Policy denied; no executor call; obtain valid authority rather than retrying unchanged |
| `validation_failure` | Never unchanged | Request/result violates contract; correct input or adapter and submit a new logical command as appropriate |
| `external_failure` | Classification required | External system failed; adapter must say transient/permanent and outcome known/unknown |
| `cancelled` | Never automatically | Cancellation was accepted before effect or executor confirmed cancellation |
| `ambiguous_outcome` | Never blindly | External effect may have occurred but no reliable receipt/result was recorded; reconcile first |
| `lease_lost` | Conditional | Worker no longer owns attempt; late result cannot commit without reconciliation |

Failure diagnostics must exclude secrets, raw prompts, sensitive content, credentials, and uncontrolled external payloads.

## Retry Model

- `max_attempts` includes the first attempt.
- Each attempt has its own start/end time, lease, failure/result, and audit facts.
- Backoff is deterministic from policy and attempt number; jitter is disabled in the contract model unless its seed/value is explicitly persisted.
- A retry never changes the ActivityRequest, target, input digest, policy, or idempotency key.
- Input changes require a new ActivityRequest and new idempotency key.
- Retry eligibility requires both a retryable failure class and effect safety.
- `non_idempotent_write`, `security_sensitive`, and ambiguous outcomes default to human reconciliation rather than automatic retry.
- Exhaustion records `failed` with `retry_exhausted` and preserves every attempt.

## Idempotency and Replay

### Logical identity

The idempotency scope is at minimum:

```text
project_id + activity_type + operation + idempotency_key
```

The ActivityRequest also stores a canonical request fingerprint derived from normalized target, immutable input digest, ActivityPolicy reference/version, and contract version.

### Rules

1. Same scope/key and same fingerprint returns the existing ActivityRecord/result.
2. Same scope/key and different fingerprint is `IDEMPOTENCY_CONFLICT`.
3. A retry uses the same Activity ID, request, key, and external idempotency token.
4. An executor must pass the stable key to an external system when supported.
5. A duplicate result submission for the same attempt and identical result digest returns the recorded outcome.
6. A duplicate submission with different content is a conflict and cannot overwrite history.
7. Event replay reconstructs ActivityRecord state but never re-executes the side effect.
8. Replaying a Workflow consumes the recorded ActivityResult reference rather than creating a duplicate request.
9. If external execution succeeded but receipt persistence is uncertain, mark `ambiguous_outcome`; reconcile before retry.

Exactly-once external execution is not claimed. FounderOS targets effectively-once behavior through durable intent, stable idempotency, bounded attempts, receipts, and reconciliation.

## Leases and Concurrency

A future scheduler may grant one attempt lease containing owner ID, opaque token digest, acquired time, and expiry. Only the valid lease holder may submit progress or a result for that attempt.

- Lease expiry does not prove the external operation stopped.
- A replacement worker cannot execute an unsafe write until prior outcome is reconciled.
- Late results are recorded as audit facts but cannot overwrite a committed terminal result.
- Optimistic ActivityRecord revision prevents concurrent lifecycle updates.
- Lease tokens are secrets and are never persisted in plaintext Events or diagnostics; only a digest/reference is stored.

No lease implementation or worker exists in RFC-0001.

## Timeout Semantics

ActivityPolicy may set:

- maximum queue duration;
- maximum execution duration; and
- maximum total duration.

A deadline is an explicit UTC timestamp derived and persisted when scheduled/claimed. Timeout processing requests cancellation and records a timeout fact. It does not assume remote termination. For idempotent reads/writes, RetryPolicy may permit another attempt. For ambiguous or non-idempotent writes, timeout requires reconciliation.

## Cancellation Semantics

- Cancellation before execution transitions `scheduled -> cancelled` without executor invocation.
- During execution, cancellation transitions to `cancellation_requested` and invokes cooperative executor cancellation if supported.
- Cancellation is not success and does not imply rollback.
- If success races with cancellation, the first valid Kernel-committed terminal result wins.
- A cancellation request and its outcome are separately auditable.
- A successful external side effect discovered after cancellation is an ambiguous/late result requiring policy-based reconciliation or compensation.

## Compensation Semantics

- Compensation is never automatic solely because an Activity failed or was cancelled.
- ActivityPolicy declares whether compensation is supported and the required operation.
- A compensation request references the original Activity and external receipt.
- Compensation requires fresh authorization and any required human Approval.
- The compensation Activity has its own status, attempts, idempotency, result, and Events.
- Original and compensation histories are immutable and both remain visible.
- Compensation success means the declared mitigation completed; it does not erase the original effect or guarantee full business reversal.

## Authorization and Approval

Activity authorization uses the Milestone 12C boundary:

- request creation may record untrusted intent;
- no Activity is scheduled until an exact allow decision is recorded;
- authorization is re-evaluated when material context, target revision, Policy version, or Approval requirements change;
- future Tool/Provider execution requires an Action and Resource specific to the exact operation;
- an allow does not replace required human Approval; and
- an Approval does not bypass authorization, validation, effect safety, or idempotency.

Human Approval as an Activity category cannot approve itself. The actual Approval record remains owned by the Kernel Approval service.

## Result Consumption

A recorded successful result is untrusted external data until consumed through a later Kernel command.

- Output content is stored by immutable reference and digest.
- Result schema validation proves shape, not truth or quality.
- AI or Tool output must become an Artifact through the Artifact lifecycle before it can be evaluated or approved.
- Workflow coordination references the ActivityResult and requests the next authorized Kernel operation.
- The result cannot directly update Project state or append an Event.
- The State Machine continues to require exact Artifact, Evaluation, Decision, and Approval evidence.

## Observability and Audit

Every accepted lifecycle transition must append an authoritative Activity Event through the future Kernel Activity service.

Reserved Event types:

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

Audit correlation spans:

```text
command -> WorkflowRun -> ActivityRequest -> attempt -> executor/receipt
        -> ActivityResult -> Artifact/Evaluation/Approval/Decision/Transition
```

Metrics and traces may later report queue time, execution time, retries, timeout, external latency, cost, token usage, and failure class. They are operational projections, not mutation authority.

Redaction rules exclude secrets, lease tokens, raw credentials, raw prompts where sensitive, full external payloads, and content protected by Resource authorization.

## Activity Categories

| Category | Examples | Special constraints |
|---|---|---|
| `ai` | Structured model generation | Provider authorization, budgets, prompt/output digest, no direct Artifact approval |
| `filesystem` | Read/write a declared path | Workspace scope, traversal prevention, effect classification |
| `network` | HTTP/API request | Destination allowlist, secret scope, timeout, response limits |
| `git` | Inspect or change repository | Repository/ref scope, write Approval, idempotent operation design |
| `browser` | Navigation or browser action | Origin policy, session isolation, prompt-injection defenses |
| `shell` | Execute a command | Sandbox, command policy, resource/time limits, explicit effect class |
| `python` | Execute bounded Python workload | Isolated environment, dependencies, CPU/memory/time limits |
| `docker` | Container operation | Image trust, mounts, network, resource and privilege policy |
| `cloud` | Cloud control/data-plane operation | Account/environment scope, strong Approval and receipts |
| `notification` | Email/chat/task notification | Recipient scope, privacy, duplicate-delivery prevention |
| `human_approval` | Notify/wait for a decision | Does not replace Kernel Approval record or decide automatically |

These categories reserve contracts only. RFC-0001 implements none of them.

## Security Invariants

1. External work never executes in a Kernel mutation transaction.
2. Executors receive least-privilege scoped inputs and secret references, never unrestricted repository access.
3. Raw secrets and lease tokens never appear in Events, audit records, diagnostics, or result payloads.
4. Authorization and required Approval precede scheduling.
5. Unknown failure, ambiguous outcome, lost lease, invalid result, or missing receipt fails closed.
6. Non-idempotent writes are never blindly retried.
7. Executors cannot mutate Kernel records or Project state.
8. Output is untrusted until validated and passed through normal Artifact/Evaluation/Approval boundaries.
9. Compensation is explicit, authorized, linked, and auditable.
10. Replay reconstructs state and reuses results; it never invokes an executor.

## Future Acceptance Scenarios

1. Duplicate request with same key/fingerprint returns the original Activity.
2. Same key with different fingerprint is rejected.
3. Authorization denial produces no executor call.
4. Cancellation before claim produces no external effect.
5. Retryable read failure creates a new attempt under the same Activity.
6. Non-idempotent ambiguous write is not retried and requires reconciliation.
7. Duplicate identical result submission is idempotent.
8. Conflicting result submission cannot overwrite the first accepted result.
9. Lease-lost executor cannot commit a result without reconciliation.
10. Timeout does not imply remote termination.
11. Compensation creates a new authorized Activity linked to the original.
12. Event replay reconstructs the same ActivityRecord without execution.
13. Recorded AI/Tool output cannot change Project state directly.
14. Every lifecycle transition resolves to an authoritative Event and ordered audit fact.

## Open Questions

- Should ActivityRequest and ActivityResult become first-class persisted supporting records or immutable payloads owned by ActivityRecord?
- Which lifecycle transitions must commit atomically with Project/WorkflowRun references?
- How should result content storage and retention interact with Artifact content storage?
- What exact outbox/inbox model will a future durable adapter use?
- How are executor descriptors and contract versions published without creating a Tool runtime prematurely?
- Which operations require re-authorization on retry versus reuse of an unexpired exact decision?
- What policy governs retention and redaction of external receipts?
- How should manual reconciliation be represented before an operator UI exists?

## Consequences

### Positive

- Provider and Tool integrations gain one consistent safety and recovery boundary.
- Kernel transactions remain deterministic and isolated from external latency.
- Retries, cancellation, compensation, and replay become explicit rather than adapter-specific.
- Audit can explain intent, authorization, attempts, external receipt, outcome, and downstream consumption.
- Future worker or cloud architecture can evolve without changing Workflow/Kernel authority.

### Costs

- Activity persistence, leasing, outbox/inbox, and reconciliation will require significant future implementation.
- Effect classification and idempotency must be correct per operation; generic retry defaults are unsafe.
- External systems without idempotency or queryable receipts require manual recovery paths.
- Result and Event retention may increase storage and privacy obligations.

## Decision Request

Accept RFC-0001 as the required contract boundary for all future external execution. No Provider, Tool, browser, shell, Python, Docker, MCP, cloud, notification, or external filesystem integration may bypass it.

## Next Step

If RFC-0001 is accepted, proceed to the minimal first-party App package contract only after confirming where authorization enforcement and Activity contract adoption occur in the implementation roadmap. Do not implement an executor as part of RFC acceptance.
