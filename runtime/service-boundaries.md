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

## Command Idempotency

CLI mutation commands may include an explicit idempotency key. Format v2 persists the key, operation name, and completed result. The same key and operation return the prior result; using the key for another operation fails. Commands without a key preserve prior behavior.

## Failure Boundaries

Local-store failure checkpoints exercise every multi-file write phase. A failed write releases its lock and must leave either a valid primary or a recoverable validated backup.

## Risks

- Artifact approval and its Event are not a database transaction; the in-memory boundary relies on runtime locking and local-store recovery.
- Command results are retained indefinitely in the local snapshot; retention policy is deferred.
- Process liveness checks are best effort and stale locks still require an explicit operator action.
- A database adapter will need equivalent import/export and transaction semantics.

## Next Step

Define local actor authorization capabilities at these service boundaries.
