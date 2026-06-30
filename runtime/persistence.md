# Local Persistence Hardening

> **Status:** Milestone 7 implemented

## Purpose

Protect the local FounderOS CLI store from simultaneous writers, stale saves, corrupt files, unsupported formats, and recoverable partial writes without adding a database.

## Write Protocol

1. Create `.write.lock` exclusively; fail if it already exists.
2. Compare the caller's loaded store revision with the committed revision.
3. Validate and copy the committed primary into `backup/`.
4. Write Artifact content and Events through temporary-file replacement.
5. Write `project-state.json` last with an incremented store revision.
6. Remove obsolete Artifact files and release the lock.

The Project revision remains the domain aggregate concurrency token. The store revision independently protects the complete local persistence snapshot.

## Validation and Health

`founderos health` reports whether the primary is valid, whether a backup exists and validates, whether a writer lock is present, supported format and store revisions, detected issues, and whether recovery is recommended.

Primary validation includes JSON parsing, contract validation, Event sequence enforcement, deterministic Project replay, required file checks, and Artifact content digest verification.

## Recovery

`founderos recover` validates `backup/`, acquires the writer lock, replaces primary state, Events, and Artifact content, and validates the restored primary. Recovery is never automatic and can lose the latest save because the backup contains the preceding committed state.

## Format Migration

Snapshots migrate through a registry keyed by their source format version. Each migration must advance the version. Missing version metadata is treated as v0. Future versions and missing migration steps are rejected.

## Risks

- Lock ownership is recorded by process ID, but stale locks are not broken automatically.
- File replacement is atomic per file, not across the entire store.
- Only one rolling backup is retained.
- Repository hydration still uses internal insertion methods pending explicit persistence ports.
- No authentication, encryption, database, or multi-project index exists.

## Next Step

Introduce explicit repository import/export ports, persisted command idempotency, stale-lock recovery policy, and failure injection for every write phase.
