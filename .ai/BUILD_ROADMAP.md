# BUILD_ROADMAP

## Milestone 1 - Repository Reconciliation

- [x] Repository scaffold
- [x] Official `.ai/` governance location
- [x] Architecture Specification v1.0-alpha
- [x] Initial state catalogue
- [x] Thin Master Orchestrator specification
- [x] Honest status labels for planned placeholders

## Milestone 2 - Executable Runtime Contracts

- [x] Define canonical identifiers and versioning
- [x] Define machine-valid core-object schemas
- [x] Define Project, workflow-run, agent-run, transition, evaluation, approval, and event records
- [x] Define state-transition guards and recovery behavior
- [x] Define persistence and state-mutation boundaries
- [x] Define contract-level acceptance scenarios
- [x] Replace runtime placeholders with contract-level component specifications

## Milestone 3 - Runtime Foundation

- [x] Minimal Python package and dependency baseline
- [x] Contract loading and JSON Schema validation
- [x] In-memory repositories for required runtime records
- [x] Project State with optimistic revisions
- [x] Guarded State Machine transitions
- [x] Ordered Event append and Project replay
- [x] Basic WorkflowRun and AgentRun lifecycles
- [x] Automated contract acceptance scenarios

## Milestone 4 - Runtime Planner Engine

- [x] Immutable ExecutionContext
- [x] Immutable ExecutionPlan
- [x] State-aware WorkflowSelector
- [x] Approved-artifact gap analysis
- [x] Deterministic AgentRouter
- [x] State Machine route and quality-gate integration
- [x] Explicit blocking reasons and unknown-state rejection
- [x] Non-mutation and determinism tests

## Milestone 5 - First Executable Vertical Slice

- [x] Create or resume a project in the active runtime
- [x] Produce, validate, persist, and approve a structured Founder Brief
- [x] Persist run, evaluation, approval, event, artifact, and transition records in memory
- [x] Verify deterministic replay/resume behavior and idempotent completion

## Milestone 6 - FounderOS CLI

- [x] Add thin standard-library command parsing
- [x] Add `new`, `status`, `plan`, `founder-brief`, `approve`, `decisions`, and `events`
- [x] Persist one local Project as JSON, JSONL Events, and Artifact JSON files
- [x] Reload and validate runtime records across CLI invocations
- [x] Preserve Planner, Approval, and State Machine boundaries
- [x] Add CLI acceptance coverage

## Milestone 7 - Persistence Hardening (Next)

- [ ] Define stable storage ports independent of in-memory repository internals
- [ ] Add transactional recovery or one atomic durable adapter
- [ ] Add file locking and concurrent-process conflict handling
- [ ] Persist command idempotency indexes across restarts
- [ ] Add corruption, partial-write, migration, and backup recovery tests

## Deferred Runtime Hardening

- Database-grade persistence adapters
- Knowledge Entry schema and executable Knowledge Base
- Authentication and authorization
- Observability and cost accounting
- Full workflow step execution and external tool/AI adapters

## Later Milestones

- Discovery, Validation, and Product runtimes
- Engineering, AI, Development, UX, QA, and Deployment runtimes
- Growth, Sales, and CEO Review runtimes

Later lifecycle modules must not begin before the executable runtime contracts, planner, and first vertical slice are validated.
