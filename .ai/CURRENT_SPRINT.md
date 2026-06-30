# CURRENT_SPRINT

Sprint: Persistence Hardening (Milestone 7)

## Goal
Harden the completed local CLI store without changing runtime contracts or adding lifecycle modules.

## Tasks
- Replace private in-memory hydration dependencies with stable storage ports
- Add cross-process locking and conflict behavior
- Define atomic recovery across snapshot, Event, and Artifact files
- Add format migration, corruption, and backup recovery tests

## Definition of Done
The CLI store has explicit concurrency, transaction recovery, migration, and corruption semantics with executable tests.

## Out of Scope
Authentication
Discovery Runtime
Validation Runtime
Product Runtime
Web UI
Discovery commands
LLM/AI provider integration
