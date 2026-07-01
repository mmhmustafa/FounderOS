# Authorization Contract Set

> **Status:** Milestone 12C placeholder contracts; not loaded or enforced by the current runtime

This directory defines the future runtime-authorization boundary without changing current FounderOS behavior.

## Contracts

- `authorization-common.schema.json` — Actor, Action, Resource, Effect, Condition, and exact rule-reference types
- `authorization-request.schema.json` — one Actor/Action/Resource evaluation request against an exact Policy version
- `authorization-decision.schema.json` — immutable allow/deny result with stable reason and matched rules
- `policy-rule.schema.json` — immutable deterministic rule definition
- `authorization-policy.schema.json` — immutable rule set using default-deny and deny-overrides semantics

## Runtime boundary

The current `ContractRegistry` intentionally does not recurse into this directory. These schemas therefore do not expand current repositories, persistence formats, runtime records, test schema counts, or accepted Actor values.

Future implementation must explicitly adopt and version these contracts, map existing runtime Actors, define persistence/audit treatment, and add authorization acceptance tests.

See `runtime/authorization.md` and `architecture/decisions/ADR-001-authorization-policy-boundary.md` for semantic authority and decision flow.
