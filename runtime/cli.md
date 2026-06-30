# FounderOS CLI

> **Status:** Executable local interface

## Purpose

The CLI is a thin JSON interface over the existing FounderOS application and runtime services. It parses commands and renders results; it does not plan workflows, approve evidence, or mutate Project state directly.

## Commands

- `founderos new` creates one local Project.
- `founderos status` shows state, completed and pending artifacts, and next action.
- `founderos plan` renders the deterministic ExecutionPlan.
- `founderos founder-brief` validates and persists structured Founder Brief input without approving or completing it.
- `founderos approve` records human approval and requests the guarded Founder Setup transition.
- `founderos decisions` lists Decision records.
- `founderos events` lists the ordered Event stream.
- `founderos health` validates primary storage, backup, format, replay, digests, and lock state.
- `founderos recover` restores the last validated pre-write backup.

## Persistence Layout

```text
.founderos/
  project-state.json  # validated runtime record snapshot
  events.jsonl        # complete gap-free Event stream
  artifacts/
    art_*.json         # immutable structured Artifact content
  backup/              # preceding validated committed state
  .write.lock          # present only while a writer owns the store
```

Writes require an exclusive lock and an expected store revision, create a backup, then use temporary-file replacement per file. Loads reject unsupported formats, invalid schemas, malformed Events, sequence gaps, replay mismatch, missing content, and content digest mismatches.

The format migration registry upgrades older snapshots one version at a time. Missing version metadata is treated as v0; future formats fail closed.

## Boundaries

`cli.py` delegates to `FounderOSApplication`. The application composes `LocalProjectStore` with `FounderSetupService`, the Planner, repositories, Approval records, and the State Machine. Only runtime services create records or request transitions.

## Risks

- The store supports one Project per directory and one active writer.
- A crashed writer can leave a lock file requiring inspected manual removal; automatic stale-lock breaking is intentionally absent.
- Atomic replacement is per file, not across the whole directory. Recovery rolls back to the preceding committed backup.
- Only one rolling backup is retained, so recovery may discard the most recent save.
- There is no authentication, file encryption, or database.

## Next Step

Add structured, redacted runtime diagnostics and end-to-end audit consistency checks.
