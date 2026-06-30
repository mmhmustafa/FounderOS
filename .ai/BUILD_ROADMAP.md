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

## Milestone 7 - Persistence Hardening

- [x] Add exclusive single-writer protection
- [x] Reject stale writes using monotonic store revisions
- [x] Create a validated backup before replacing committed files
- [x] Detect corrupt/missing state, Event errors, replay mismatch, and Artifact digest mismatch
- [x] Add explicit backup recovery and persistence health reporting
- [x] Add format-version migration structure and future-version rejection
- [x] Add corruption, locking, stale-write, migration, and recovery tests

## Milestone 8 - Runtime Service Boundary Hardening

- [x] Replace persistence hydration through repository internals with explicit import/export ports
- [x] Extract Artifact, Evaluation, and Approval lifecycle operations from the Founder Setup coordinator
- [x] Retain WorkflowRun and AgentRun services as reusable lifecycle boundaries
- [x] Persist command idempotency keys independently of in-process service instances
- [x] Define stale-lock inspection and guarded manual lock removal
- [x] Add failure-injection coverage across multi-file save phases

## Milestone 9 - Runtime Observability and Audit Diagnostics

- [x] Define structured runtime diagnostic summaries without adding a database
- [x] Add command correlation and operation timing summaries
- [x] Add inspectable run, transition, approval, Artifact, and persistence diagnostics
- [x] Add default redaction and explicit sensitive-content opt-in
- [x] Add end-to-end audit consistency checks
- [x] Add read-only audit, runs, and transitions CLI commands

## Milestone 10 - Discovery Workflow v1

- [x] Add deterministic Discovery service and static candidate input
- [x] Define Opportunity Report and Candidate contracts
- [x] Compute and rank six-factor scores deterministically
- [x] Persist runs, Artifact, Evaluation, Approval, and selection Decision
- [x] Apply guarded transitions through `DISCOVERY_RUNNING` to `OPPORTUNITY_SELECTED`
- [x] Add CLI, audit traceability, replay, and acceptance tests

## Milestone 11 - Authorization Policy Foundation (Next)

- [ ] Define actor capabilities for Project, Approval, Artifact, and Transition operations
- [ ] Enforce founder ownership at application and runtime service boundaries
- [ ] Define authorization denial diagnostics without leaking sensitive context
- [ ] Add authorization acceptance and negative tests
- [ ] Preserve local CLI usability without external authentication

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
