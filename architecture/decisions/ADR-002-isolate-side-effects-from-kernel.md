# ADR-002: Isolate External Side Effects from the FounderOS Kernel

> **Status:** Proposed with RFC-0001  
> **Date:** 2026-07-01  
> **Milestone:** 12D — Durable Activity and Side-Effect Contracts

## Context

FounderOS will eventually call AI Providers, Tools, browsers, Git systems, shells, Docker, MCP servers, cloud APIs, notifications, and other external systems. These operations are nondeterministic, slow, failure-prone, and may create effects that cannot participate in the Kernel's transaction.

Executing them inside Project or runtime mutation transactions would hold locks across unbounded work, mix external failure with domain consistency, and make replay capable of repeating side effects. Letting Workflows or executors write repositories directly would create competing mutation and Event authorities.

## Decision

1. Every external operation is represented by a durable ActivityRequest before execution.
2. The future Kernel Activity service is the sole owner of ActivityRecord mutation and authoritative Activity Events.
3. Activity execution occurs outside all Kernel mutation transactions through an ActivityExecutor boundary.
4. Executors return immutable ActivityResults and receipts; they never mutate Project, WorkflowRun, Artifact, Approval, Decision, Evaluation, Transition, or Event storage.
5. One logical Activity retains one idempotency identity across attempts.
6. Retry requires both a declared retryable failure and effect-safe replay.
7. Ambiguous non-idempotent effects are reconciled, not blindly retried.
8. Compensation is a new linked, authorized Activity and never rewrites history.
9. Event replay reconstructs Activity state and reuses recorded results; it never invokes an executor.
10. External output remains untrusted until consumed through existing Kernel validation, Artifact, Evaluation, Approval, and State Machine boundaries.

## Boundary Diagram

```text
Kernel transaction                         Outside Kernel transaction
------------------                         --------------------------
Authorize intent
Record ActivityRequest + Event
Commit
             --------------------------->  Claim bounded attempt
                                             Execute external operation
                                             Produce result/receipt
             <---------------------------  Submit ActivityResult
Validate lease/result
Record outcome + Event
Commit
Workflow consumes recorded result
```

## Consequences

### Positive

- Kernel consistency no longer depends on external latency or availability.
- Side effects are not repeated by Event or Workflow replay.
- Attempts, receipts, failures, cancellation, and recovery are auditable.
- Provider and Tool adapters share one execution safety model.
- Future local workers, queues, and distributed executors can evolve behind contracts.

### Costs

- Durable Activity persistence and scheduling are required before real integrations.
- Exactly-once external execution cannot be promised; effectively-once behavior requires idempotency and reconciliation.
- Operations must declare effect safety, timeout, retry, cancellation, and compensation behavior.
- Ambiguous external writes may require manual intervention.

## Rejected Alternatives

### Execute external work inside a Kernel transaction

Rejected because an external system cannot join the transaction, and unbounded latency would compromise consistency and availability.

### Let Workflows call Providers or Tools directly

Rejected because Workflows would bypass authorization, Activity history, bounded retries, receipts, and authoritative Event ownership.

### Retry every transient-looking failure

Rejected because a timeout or connection loss may occur after the external effect succeeded. Blind retry can duplicate destructive actions.

### Treat Event replay as Activity replay

Rejected because deterministic Event replay reconstructs facts; it must never repeat nondeterministic external operations.

### Mutate the original Activity to represent compensation

Rejected because compensation is a new effect with its own authorization, attempts, risks, and possible failure. Historical truth must remain immutable.
