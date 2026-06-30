# FounderOS Milestone 6 Handoff

Milestone 6 — FounderOS CLI — is complete.

## Files Changed

- Added `src/founderos_runtime/cli.py`.
- Added `src/founderos_runtime/application.py`.
- Added `src/founderos_runtime/local_store.py`.
- Added `tests/test_cli.py`.
- Added `runtime/cli.md`.
- Added the `founderos` console entry point to `pyproject.toml`.
- Updated runtime exports, `.gitignore`, README, CHANGELOG, architecture status, AI governance, roadmap, sprint, decisions, and runtime documentation.

## CLI Commands Added

- `founderos new`
- `founderos status`
- `founderos plan`
- `founderos founder-brief`
- `founderos approve`
- `founderos decisions`
- `founderos events`

The CLI uses Python's standard-library `argparse` and emits JSON. It delegates planning and mutations to the existing application and runtime services.

## Persistence Approach

Each project directory contains:

```text
.founderos/
  project-state.json
  events.jsonl
  artifacts/
    art_*.json
```

Runtime records are validated while loading. Events must remain gap-free and ordered, the Project must match deterministic Event replay, and Artifact content must match its recorded SHA-256 digest. Writes use temporary-file replacement per file.

## Tests Added

Nine CLI acceptance tests cover:

- Project creation and local state files.
- Status output.
- Founder Setup planning.
- Founder Brief creation and persistence.
- Prevention of premature transition.
- Human approval and guarded completion.
- Ordered Events across separate CLI invocations.
- Runtime Transition records and replay.
- Decision listing.

The full test suite passes: **47 tests**.

## What Works Now

- The package installs an executable `founderos` command.
- A user can create and inspect one local Project.
- The Planner can be invoked from the CLI.
- Structured Founder Brief input can be validated and persisted.
- Founder Brief approval applies the transition through the existing State Machine guards.
- Decisions and ordered Events can be inspected.
- State reloads safely between CLI invocations.

## Remaining Limitations

- Each project directory supports one Project.
- The file store assumes one writer and has no cross-process lock.
- Atomic replacement is per file, not transactional across the directory.
- Persistence format migration, backup recovery, and corruption repair are not implemented.
- Authentication and production authorization policy are not implemented.
- There is no Web UI, AI provider integration, general workflow interpreter, Discovery, Validation, or Product implementation.

## Recommended Next Milestone

Milestone 7 — Persistence Hardening: introduce stable storage ports, file locking, transactional recovery, format migration, and corruption/backup recovery tests before expanding the CLI or lifecycle modules.
