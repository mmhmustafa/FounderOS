# FounderOS Milestone 8 Handoff

Milestone 8 — Runtime Service Boundary Hardening — is complete.

## Files Changed

- Added `src/founderos_runtime/lifecycle.py`.
- Added `tests/test_service_boundaries.py`.
- Added `runtime/service-boundaries.md`.
- Updated repositories, local persistence, Founder Setup, application facade, CLI, errors, and package exports.
- Updated README, CHANGELOG, AI governance, roadmap, sprint, decisions, and runtime documentation.

## Service Boundaries Added

- Repositories now expose validated public `import_records()` and defensive `export_records()` ports.
- Runtime composition exposes bulk record and ordered Event import/export boundaries.
- Local persistence no longer calls repository-private insertion methods.
- `ArtifactLifecycleService` owns Artifact creation and approval-reference attachment.
- `EvaluationLifecycleService` owns immutable Evaluation creation.
- `ApprovalLifecycleService` owns Approval requests and human decisions.
- Existing `WorkflowRunService` and `AgentRunService` remain the reusable run lifecycle boundaries.
- The State Machine remains the sole Project state-transition authority.

## Persisted Command Idempotency

Persistence format v2 stores completed command keys, operation names, and results.

The following mutation commands accept `--idempotency-key`:

- `founderos new`
- `founderos founder-brief`
- `founderos approve`

Repeating the same key and operation returns the persisted result without duplicating important records or Events. Reusing a key for another operation is rejected.

## Stale-Lock Policy

Lock inspection reports PID, creation timestamp, age, and best-effort owner liveness. Locks are never removed automatically. Guarded manual removal requires:

- The exact unchanged PID.
- Confirmation that the owner process is not alive.
- A caller-defined minimum lock age.

Live, recent, changed, or malformed locks fail closed.

## Failure-Injection Coverage

The local store exposes test-only failure checkpoints:

- After backup creation.
- After Artifact writes.
- After Event writes.
- Before state commit.
- After state commit.

Tests verify that injected failures release the writer lock and leave either a valid primary or validated recovery path.

## Tests Added

Eight service-boundary tests cover:

- Repository import/export round trips.
- Founder Setup lifecycle-service delegation.
- Restart-safe Project creation idempotency.
- Restart-safe Founder Brief and Approval idempotency.
- Cross-operation key rejection.
- Lock inspection and safe stale-lock removal.
- Recent dead-lock refusal.
- Every local-store write failure phase.

The complete test suite passes: **68 tests**.

## Remaining Risks

- Multi-file local writes are not transactionally atomic.
- Only one rolling backup is retained.
- Process liveness checks are best effort.
- Stale locks require explicit operator action.
- Command-result retention and pruning are not defined.
- Lifecycle record mutation and Event append do not have database-grade transactions.
- There is no database, Web UI, LLM integration, Discovery, or Validation implementation.

## Recommended Next Milestone

Milestone 9 — Runtime Observability and Audit Diagnostics: add structured and redacted diagnostics, command correlation, operation timing, runtime record inspection, and end-to-end audit consistency checks without external infrastructure.
