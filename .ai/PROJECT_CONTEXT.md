# PROJECT_CONTEXT

## Vision
FounderOS is an AI operating system that helps technical founders discover, validate, design, build, launch, and scale B2B SaaS products.

## Mission
Create a repeatable system that combines AI agents, workflows, and structured artifacts into a practical startup-building platform.

## Current Architecture
Core object types:
- Agent
- Artifact
- Workflow
- State
- Decision

Runtime:
- Master Orchestrator
- State Machine
- Project State
- Workflow Engine
- Decision Engine
- Knowledge Base

## Repository Structure
`.ai/`, `runtime/`, `architecture/`, `agents/`, `prompts/`, `templates/`, `domains/`, `examples/`, `roadmap/`, `docs/`

## Completed
- Repository scaffold
- AI governance location and onboarding entry point
- Architecture Specification v1.0-alpha
- Guarded state-transition and recovery specification
- Thin Master Orchestrator specification
- Machine-valid contracts for the five core objects
- Machine-valid contracts for Project, WorkflowRun, AgentRun, Transition, Evaluation, Approval, and Event
- Persistence/state-mutation boundaries and contract acceptance scenarios
- Contract-level specifications for runtime foundation components
- Python runtime package and JSON Schema validation
- In-memory runtime repositories and Project State
- Guarded State Machine with optimistic concurrency and atomic Event append
- Basic WorkflowRun and AgentRun lifecycle services
- Automated contract acceptance suite
- Deterministic read-only Runtime Planner Engine
- ExecutionContext and ExecutionPlan models
- Workflow selection, missing-artifact analysis, agent-role routing, and quality-gate planning
- Founder Brief content contract and immutable in-memory content store
- Executable Founder Setup service with human approval and deterministic replay/resume
- Thin FounderOS CLI and validated local JSON/JSONL persistence
- Local single-writer protection, stale-write checks, backups, recovery, migration handling, and health reporting
- Public persistence ports, reusable lifecycle services, restart-safe command idempotency, and guarded stale-lock recovery
- Correlated read-only runtime diagnostics, audit traceability, consistency checks, and default redaction
- Deterministic Discovery Workflow v1 through approved Opportunity selection
- Stable cross-platform pytest setup with official developer test scripts and standard cache behavior
- FounderOS v0.2 Architecture Review Board and revised implementation-gated Blueprint
- Runtime authorization architecture, placeholder contracts, deterministic policy semantics, and ADR
- RFC-0001 durable Activity/side-effect architecture, placeholder contracts, lifecycle, replay, failure semantics, and ADR
- PR-001 versioned Agent Manifest schema, Product Manager example, and independent deterministic validation
- PR-002 versioned Workflow Manifest schema, Discovery example, lifecycle/utility boundaries, and semantic reference validation
- PR-003 versioned App Package Manifest schema, Discovery App example, first-party asset index, and package-boundary validation
- PR-004 stateless Manifest Loader with safe YAML parsing, deterministic structural/semantic validation, and typed contextual errors
- PR-005 read-only Workspace with bounded discovery, exact manifest relationships, compatibility checks, cycle detection, and deterministic queries
- PR-006 immutable Provider contracts and deterministic offline Mock Provider with fixtures, error simulation, schema checks, and no runtime mutation
- PR-007 immutable Evaluation contracts and deterministic quality runner with built-in/custom rules, scoring, and no persisted evidence mutation
- PR-008 immutable Workspace Execution Plans with exact reference resolution, dependency ordering, checkpoints, and no execution or mutation
- PR-009 deterministic in-memory Journey Runner with Mock Provider Agent tasks, Evaluation checkpoints, critical stopping, and no persistence or state mutation

## Current Milestone
PR-010: validate Execution Plans and derive authorization requests before expanding execution beyond the deterministic in-memory harness.

## Planned
- Durable persistence adapters
- Full Workflow step execution
- Artifact, Decision, Evaluation, and Approval lifecycle services beyond repository boundaries
- Knowledge Entry schema and executable Knowledge Base
- Executable authorization enforcement at application and Kernel mutation boundaries
- Authorization decision persistence/audit integration and acceptance tests
- Executable durable Activity service, persistence, scheduling, and enforcement
- Minimal bundled first-party App package contract
- Versioned Evaluation Rubric Manifest contract
- Versioned Prompt Pack Manifest contract
- Deterministic fake structured-generation Provider
- Validation and Product runtimes
- Web application and database persistence

The Runtime Foundation, Founder Setup, deterministic Discovery v1, and local CLI are implemented. General orchestration and later lifecycle modules remain planned.

The Planner remains read-only. Founder Setup consumes its recommendation and coordinates explicit runtime mutations; it does not call models.

For v0.2, an App is a package of existing definitions and assets, while Workflow remains the executable unit. FounderOS remains a modular monolith; the Kernel is the sole runtime mutation authority, and authorization precedes Provider or Tool execution.

Milestone 12C defines authorization contracts only. Current services do not yet enforce them, and existing runtime Actor schemas remain unchanged. Runtime enforcement is a required future gate before Provider or Tool execution.

RFC-0001 defines durable Activity contracts only. The current runtime does not record, schedule, execute, retry, cancel, compensate, or audit Activities. Activity and authorization enforcement remain mandatory before Provider or Tool execution.

## Long-term Goal
Evolve FounderOS into a web application with persistent project state and AI orchestration.
