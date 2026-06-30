# FounderOS Milestone 7 Handoff

Milestone 7 — Persistence Hardening — is complete.

## Files Changed

- Hardened `src/founderos_runtime/local_store.py`.
- Updated `src/founderos_runtime/application.py`, `cli.py`, `errors.py`, and package exports.
- Added `tests/test_persistence_hardening.py`.
- Expanded `tests/test_cli.py`.
- Added `runtime/persistence.md`.
- Updated README, CHANGELOG, architecture status, AI governance, roadmap, sprint, decisions, and runtime documentation.

## Persistence Improvements

- Exclusive `.write.lock` files provide fail-fast single-writer protection.
- Monotonic `store_revision` values reject stale read-modify-write attempts.
- Every replacement after the initial save creates a validated pre-write backup.
- `founderos health` validates primary storage, backup validity, writer-lock state, format support, schemas, ordered Events, deterministic Project replay, and Artifact content digests.
- `founderos recover` restores and revalidates the last backup.
- An explicit migration registry upgrades older persistence formats one version at a time.
- Missing format metadata is treated as v0 and migrated to v1.
- Unsupported future formats fail closed.

## Tests Added

Persistence tests cover:

- Active writer-lock rejection.
- Stale-write rejection.
- Backup creation before writes.
- Corrupted `project-state.json` detection and recovery.
- Corrupted `events.jsonl` detection and recovery.
- Missing state and Event file recovery.
- Event replay mismatch detection.
- v0-to-v1 migration.
- Future-format rejection.
- Persistence health during an active lock.
- CLI health and recovery commands.

The complete test suite passes: **60 tests**.

## What Works Now

- Local writes permit only one active writer.
- Sequential stale writers cannot overwrite newer state.
- The preceding validated committed state is retained as a backup.
- Corruption and replay divergence are detected before runtime use.
- Operators can inspect persistence health and explicitly recover.
- Migration behavior is structured and testable.
- Existing Founder Setup and State Machine behavior remains unchanged.

## Remaining Risks

- Only one rolling backup is retained.
- Recovery can lose the most recent write because the backup represents the preceding committed state.
- A crashed process can leave a stale lock requiring inspected manual removal.
- File replacement is atomic per file, not transactionally atomic across the directory.
- Persistence hydration still uses repository-internal insertion methods.
- There is no database, authentication, encryption, Web UI, Discovery, or Validation implementation.

## Recommended Next Milestone

Milestone 8 — Runtime Service Boundary Hardening: introduce explicit repository import/export ports, extract reusable Artifact/Evaluation/Approval lifecycle services, persist command idempotency keys, define safe stale-lock recovery, and add write-phase failure-injection tests.
