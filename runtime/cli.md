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

## Persistence Layout

```text
.founderos/
  project-state.json  # validated runtime record snapshot
  events.jsonl        # complete gap-free Event stream
  artifacts/
    art_*.json         # immutable structured Artifact content
```

Writes use temporary-file replacement per file. Loads reject unsupported formats, invalid schemas, malformed Events, sequence gaps, missing content, and content digest mismatches.

## Boundaries

`cli.py` delegates to `FounderOSApplication`. The application composes `LocalProjectStore` with `FounderSetupService`, the Planner, repositories, Approval records, and the State Machine. Only runtime services create records or request transitions.

## Risks

- The store supports one Project per directory and assumes one writer.
- Atomic replacement is per file, not across the whole directory.
- There is no authentication, file encryption, database, or format migration framework.

## Next Step

Add stable persistence ports, file locking, transaction recovery, and migration tests before broadening the CLI.
