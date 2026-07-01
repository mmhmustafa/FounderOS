# Durable Activity Contract Set

> **Status:** RFC-0001 proposed placeholder contracts; not loaded or enforced by the current runtime

## Contracts

- `activity-common.schema.json` — identifiers, categories, statuses, effect/failure classes, target/content references, and shared policy references
- `retry-policy.schema.json` — bounded attempts and deterministic backoff
- `activity-policy.schema.json` — effect, timeout, cancellation, compensation, Approval, and budget constraints
- `activity-request.schema.json` — immutable logical Activity intent and idempotency identity
- `activity-result.schema.json` — immutable attempt outcome, receipt, usage, and failure
- `activity-record.schema.json` — mutable Kernel-owned lifecycle coordination record
- `activity-audit-record.schema.json` — immutable Activity fact linked to an authoritative Event

## Runtime boundary

The current `ContractRegistry` intentionally does not recurse into this directory. No Activity schema is registered, persisted, emitted, or executed. Existing runtime records and schema counts remain unchanged.

See `docs/rfcs/RFC-0001-durable-activity-and-side-effect-contracts.md` and `architecture/decisions/ADR-002-isolate-side-effects-from-kernel.md`.
