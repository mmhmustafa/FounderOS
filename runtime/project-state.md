# Project State

> **Status:** Runtime Foundation implemented with a local CLI snapshot adapter; production persistence not started
>
> **Schema:** `runtime/contracts/project.schema.json`

## Purpose

Project State is the authoritative project aggregate and resume boundary. It identifies the current lifecycle state, active workflow run, approved/completed artifacts, decisions, risks, next action, revision, and last committed event sequence.

## Inputs

- Valid Project creation command
- Expected-revision update command
- References produced by authorized runtime services
- Applied Transition from the State Machine

## Outputs

- Persisted Project snapshot
- Exact revision or stale-revision rejection
- Project Event for each committed mutation

## Invariants

1. Project IDs are immutable `prj_` ULIDs.
2. Revision starts at `1` and increments once per committed mutation.
3. Only the State Machine may change `current_state`.
4. At most one state-owning WorkflowRun may be current in contract version `1.x`.
5. Completed artifact and decision references must resolve within the Project.
6. `last_event_sequence` equals the latest aggregate-mutating Event reflected by the Project snapshot; the Event repository owns the complete audit sequence.
7. Read models never override the Project snapshot.
8. Archived or completed Projects reject new workflow and transition mutations.

## Contract Operations

| Operation | Preconditions | Result |
|---|---|---|
| Create Project | Unique ID; valid founder/domain | Revision `1`, state `NO_PROJECT`, `project.created` Event |
| Load Project | Project exists and actor is authorized | Exact stored snapshot |
| Attach reference | Expected revision matches; reference valid and project-owned | Reference added, revision incremented, Event appended |
| Update risks/next action | Expected revision matches; authorized service | Snapshot updated and Event appended |
| Apply Transition | State Machine supplies applied Transition in one transaction | State/revision/event sequence updated atomically |
| Archive Project | No conflicting mutation; authorized human | Status `archived`; further mutations rejected |

## Mutation Boundary

The Master Orchestrator, Workflow Engine, registries, and agents cannot write Project storage directly. They submit commands to Project State or Transition requests to the State Machine.

## Dependencies

- `runtime/contracts/project.schema.json`
- `runtime/contracts/event.schema.json`
- `runtime/contracts/persistence-boundaries.md`
- `runtime/state-machine.md`

## Failure and Recovery

- Stale revision: reject and reload.
- Invalid/cross-project reference: reject without mutation.
- Persistence failure: expose no partial snapshot/event update.
- Derived snapshot mismatch during replay: report integrity failure and stop mutations pending recovery.

## Risks

- Snapshot frequency and event replay implementation are undecided.
- Multi-tenant authorization and deletion policy are deferred.

## Implementation

`src/founderos_runtime/project_state.py` and `repositories.py` implement Project creation, guarded detail updates, optimistic revisions, atomic aggregate/Event commits, defensive copies, and replay verification in memory.

## Local CLI Persistence

`LocalProjectStore` serializes validated runtime records to `.founderos/project-state.json`, writes the complete ordered Event stream to `.founderos/events.jsonl`, and stores Artifact content under `.founderos/artifacts/`. Every load validates schemas, Event ordering and replay, format compatibility, and content digests before commands run.

Writes require an exclusive lock and matching store revision. A validated pre-write backup supports explicit rollback recovery. The adapter is intentionally single-Project and single-writer; it does not claim database-grade transactions.

## Persistence Ports

Runtime repositories expose validated public import/export operations. The local adapter no longer calls private insertion methods.

## Next Step

Add structured audit diagnostics while preserving Project State as the authoritative aggregate.
