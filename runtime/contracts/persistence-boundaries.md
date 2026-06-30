# Persistence and State-Mutation Boundaries

> **Status:** Contract specification

## Purpose

Define authoritative stores, mutation ownership, concurrency rules, and transaction boundaries without choosing a database or implementing repositories.

## Persistence Categories

| Category | Records | Mutability |
|---|---|---|
| Versioned definitions | Agent, Workflow, State | Immutable per version; publish a new version to change |
| Versioned project content | Artifact, Decision | Prior versions immutable; mutable review/status metadata uses revisions |
| Mutable project aggregate | Project | Optimistic-concurrency updates only |
| Execution records | WorkflowRun, AgentRun, Approval | Status transitions with monotonically increasing revision where defined |
| Immutable outcomes | Transition, Evaluation | Final outcome never overwritten |
| Audit stream | Event | Append-only and ordered per project |

## Mutation Owners

| Operation | Sole mutation boundary |
|---|---|
| Create/load/update Project | Project State repository/service |
| Start/update WorkflowRun | Workflow Engine |
| Start/finalize AgentRun | Agent Registry/runner boundary |
| Create/version Artifact | Artifact Registry |
| Propose/finalize Decision | Decision Engine |
| Create Evaluation | Quality Gate service |
| Request/decide Approval | Human Approval service |
| Apply state transition | State Machine transaction boundary |
| Append Event | Event store through the owning service transaction |

The Master Orchestrator coordinates these boundaries but owns none of their storage.

## Project Aggregate Boundary

Project is the consistency boundary for current state and active workflow ownership. A state-changing request must include `expected_project_revision`. Only the State Machine may change `Project.current_state`.

Registries may add references to artifacts or decisions through Project State operations, but they must not change current state or infer a transition.

## Transaction Rules

1. Validate schema and references before opening a mutation transaction.
2. Recheck authorization, expected revision, and state within the transaction.
3. Persist the domain record and corresponding Event atomically when they share the Project boundary.
4. Increment each mutated record revision once.
5. Commit or expose no effects.
6. Return persisted records, not caller-provided projections.

Cross-system AI/tool calls never execute inside the state mutation transaction. Their results are first persisted as AgentRun/Artifact records, then evaluated in a separate transition request.

## Event Contract

- Events are append-only.
- Each project owns an independent sequence beginning at `1`.
- `sequence` is unique and gap-free within a committed project stream.
- `occurred_at` captures domain time; `recorded_at` captures persistence time.
- `correlation_id` groups one user/runtime command.
- `causation_event_ref` links derived effects.
- Event payloads are factual snapshots or references, never the sole storage of large artifact content.
- `Project.last_event_sequence` is the latest aggregate-mutating Event incorporated into that snapshot. Non-mutating audit Events remain ordered in the Event repository without incrementing Project revision.

## Artifact Content Boundary

Artifact metadata is stored separately from content. `content_uri` identifies immutable content and `content_digest` verifies it. Changing content requires a new Artifact version and digest; an in-place content overwrite is forbidden.

## Definition Registry Boundary

Agent, Workflow, and State definitions are globally readable, version-addressable records. A run pins the exact definition version used. Deprecation prevents new runs but does not invalidate historical references.

## Knowledge Boundary

Knowledge entries are supporting source material, not a sixth core object. The Knowledge Base stores source URI, provenance, retrieval metadata, content digest, scope, and freshness. A workflow must convert relied-upon knowledge into evidence references on an Artifact or Evaluation before it can satisfy a transition guard.

## Read Models

Dashboards and search indexes are derived, disposable read models. They never become authoritative for approvals, state, decisions, artifact status, or event order.

## Backup and Retention Requirements

- Authoritative records and artifact content must be recoverable together.
- Event history, approvals, decisions, and applied transitions are audit records and must not be hard-deleted by ordinary application operations.
- Retention and privacy policy remain future decisions; implementations must not assume indefinite retention without approval.

## Risks

- A concrete database transaction model remains undecided.
- Event schema evolution and snapshot policy need implementation design.
- Multi-tenant authorization and deletion policy are outside Milestone 2.

## Runtime Implementation

Milestone 3 implements these boundaries using thread-safe in-memory repositories and rollback snapshots. Durable adapters remain future work.

## Next Step

Implement a durable persistence adapter for the first vertical slice without changing service ownership.
