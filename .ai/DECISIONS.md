# DECISIONS

## D-001
Decision: FounderOS uses five core objects.
Reason: Simplicity and scalability.
Status: Accepted.

## D-002
Decision: Master Orchestrator is the single user-facing entry point and a thin facade over runtime services.
Reason: Preserve a simple user experience without creating a monolithic controller.
Status: Accepted.

## D-003
Decision: FounderOS is state-driven.
Reason: Predictable workflow transitions.
Status: Accepted.

## D-004
Decision: Networking is the first specialization.
Reason: Founder's expertise and easier validation.
Status: Accepted.

## D-005
Decision: `.ai/` is the official location for AI governance and onboarding documents.
Reason: Provide one explicit entry point and separate project governance from product documentation.
Status: Accepted.

## D-006
Decision: Empty scaffold files represent planned work, not completed components.
Reason: Repository status must distinguish structure from implementation.
Status: Accepted.

## D-007
Decision: Executable runtime contracts precede lifecycle module development.
Reason: Validate shared semantics before implementing Discovery, Validation, Product, or other domain workflows.
Status: Accepted.

## D-008
Decision: FounderOS runtime contracts use JSON Schema Draft 2020-12.
Reason: Provide language-neutral, machine-valid structural contracts with standard reference and conditional validation support.
Status: Accepted.

## D-009
Decision: Persisted entities use immutable type-prefixed ULIDs; definition/content versions use Semantic Versioning; mutable records use integer revisions.
Reason: Separate identity, compatibility, and optimistic concurrency instead of overloading one field.
Status: Accepted.

## D-010
Decision: State changes occur only through guarded Transition records at the State Machine boundary.
Reason: Prevent orchestrators, workflows, agents, or registries from bypassing evidence, approval, authorization, and concurrency checks.
Status: Accepted.

## D-011
Decision: Project mutation and its Event append must commit atomically, while AI and external tool calls occur outside mutation transactions.
Reason: Preserve consistent state and audit history without holding transactions across nondeterministic external operations.
Status: Accepted.

## D-012
Decision: Important lifecycle transitions and decisions require explicit authorized human Approval records.
Reason: Implement the constitutional principle that humans approve important decisions and prevent confidence scores or agent output from implying consent.
Status: Accepted.

## D-013
Decision: Supporting runtime records do not expand the five product-level core objects.
Reason: Project, run, transition, evaluation, approval, and event records are operational infrastructure for Agent, Artifact, Workflow, State, and Decision.
Status: Accepted.

## D-014
Decision: The Runtime Foundation uses Python 3.11+ with `jsonschema` 4.x as its only runtime dependency and standard-library `unittest` for tests.
Reason: Python provides a small, readable implementation surface while `jsonschema` enforces the approved language-neutral contracts without introducing an application framework.
Status: Accepted.

## D-015
Decision: Milestone 3 uses thread-safe in-memory repositories behind explicit service boundaries.
Reason: Validate contracts, transactions, guards, and lifecycle semantics before choosing durable storage technology.
Status: Accepted.

## D-016
Decision: `Project.last_event_sequence` identifies the latest aggregate-mutating Event incorporated into the Project snapshot; the Event repository independently owns the complete gap-free audit-stream sequence.
Reason: Rejected transitions and run lifecycle Events must remain auditable without changing Project state or optimistic revision.
Status: Accepted.

## D-017
Decision: The Runtime Planner is a deterministic, read-only layer that produces recommendations but never creates runs, transitions, events, artifacts, decisions, or state mutations.
Reason: Separate planning from execution so recommendations cannot bypass runtime contracts, quality gates, approvals, or persistence boundaries.
Status: Accepted.

## D-018
Decision: Planner workflow and agent-role mappings are explicit static metadata in Milestone 4, while allowed transitions and guard requirements remain authoritative in the State Machine.
Reason: Keep routing transparent and testable without duplicating transition authority or introducing AI-based planning.
Status: Accepted.

## D-019
Decision: Founder Brief content is caller-supplied structured data validated by a dedicated versioned schema; Milestone 5 performs no generative AI work.
Reason: Exercise the complete runtime path deterministically before introducing nondeterministic providers.
Status: Accepted.

## D-020
Decision: The Founder Setup application service coordinates existing Planner, run, registry, approval, Event, and State Machine boundaries instead of becoming a second transition authority.
Reason: Keep orchestration thin and preserve the runtime contracts as the source of truth.
Status: Accepted.

## D-021
Decision: Milestone 5 stores canonical JSON content immutably in memory and records its SHA-256 digest on the Artifact.
Reason: Verify content integrity and replay semantics while deferring storage technology to Milestone 6.
Status: Accepted.

## D-022
Decision: Milestone 6 uses Python standard-library `argparse` and JSON output for the CLI.
Reason: Keep the interface testable and dependency-free while the command surface is small.
Status: Accepted.

## D-023
Decision: CLI commands delegate to a thin application facade, which delegates all planning, approvals, runs, and transitions to existing runtime services.
Reason: Prevent presentation code from duplicating or bypassing runtime rules.
Status: Accepted.

## D-024
Decision: The initial CLI persists one Project using a validated JSON record snapshot, an ordered JSONL Event stream, and immutable JSON Artifact content files under `.founderos/`.
Reason: Provide understandable restart-safe local use without introducing a database or claiming production-grade transaction semantics.
Status: Accepted.
