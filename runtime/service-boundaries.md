# Runtime Service Boundaries

> **Status:** Milestone 8 implemented

## Persistence Ports

Repositories expose `export_records()` and validated `import_records()` operations. Runtime composition exposes bulk record and ordered Event ports. Local persistence does not access private insertion methods.

## Lifecycle Ownership

- `ArtifactLifecycleService` owns Artifact creation and approval evidence attachment.
- `EvaluationLifecycleService` owns immutable Evaluation creation.
- `ApprovalLifecycleService` owns Approval requests and human decisions.
- `WorkflowRunService` owns WorkflowRun creation and status transitions.
- `AgentRunService` owns AgentRun creation, status transitions, and retries.
- `StateMachine` remains the sole Project state-transition authority.

Founder Setup coordinates these services but does not duplicate their mutation logic.

## Authorization Boundary

Milestone 12C defines, but does not implement, a deterministic authorization gate in `runtime/authorization.md`. Every protected mutation must eventually be authorized immediately before the owning service boundary. An allow decision permits the request to reach that service; the service retains contract, reference, revision, Approval, Event, and transaction authority.

Application/CLI checks alone are insufficient because internal Workflow, Agent, and future background callers could bypass them. The owning mutation service must enforce authorization when the contracts are adopted in a later implementation milestone.

## Command Idempotency

CLI mutation commands may include an explicit idempotency key. Format v2 persists the key, operation name, and completed result. The same key and operation return the prior result; using the key for another operation fails. Commands without a key preserve prior behavior.

## Failure Boundaries

Local-store failure checkpoints exercise every multi-file write phase. A failed write releases its lock and must leave either a valid primary or a recoverable validated backup.

## Future Activity Boundary

RFC-0001 requires every external side effect to begin as a Kernel-recorded ActivityRequest. Execution occurs outside Kernel transactions through an ActivityExecutor, which returns an immutable ActivityResult and receipt. A future Kernel Activity service alone may mutate ActivityRecord state and append authoritative Activity Events.

Workflows, Agents, Providers, Tools, and executors cannot write repositories or Events directly. Event replay reuses recorded results and never invokes an executor. These are placeholder contracts only; no current service implements them.

## Risks

- Artifact approval and its Event are not a database transaction; the in-memory boundary relies on runtime locking and local-store recovery.
- Command results are retained indefinitely in the local snapshot; retention policy is deferred.
- Process liveness checks are best effort and stale locks still require an explicit operator action.
- A database adapter will need equivalent import/export and transaction semantics.

## Next Step

Define the minimal first-party App package contract without adding an App registry runtime.
