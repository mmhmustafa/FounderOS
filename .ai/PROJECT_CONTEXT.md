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

## Current Milestone
Milestone 12C: define local authorization policy without external authentication infrastructure before App, Provider, Tool, Knowledge, or Validation implementation.

## Planned
- Durable persistence adapters
- Full Workflow step execution
- Artifact, Decision, Evaluation, and Approval lifecycle services beyond repository boundaries
- Knowledge Entry schema and executable Knowledge Base
- Authorization and observability
- Durable activity and external side-effect contracts
- Minimal bundled first-party App package contract
- Deterministic fake structured-generation Provider
- Validation and Product runtimes
- Web application and database persistence

The Runtime Foundation, Founder Setup, deterministic Discovery v1, and local CLI are implemented. General orchestration and later lifecycle modules remain planned.

The Planner remains read-only. Founder Setup consumes its recommendation and coordinates explicit runtime mutations; it does not call models.

For v0.2, an App is a package of existing definitions and assets, while Workflow remains the executable unit. FounderOS remains a modular monolith; the Kernel is the sole runtime mutation authority, and authorization precedes Provider or Tool execution.

## Long-term Goal
Evolve FounderOS into a web application with persistent project state and AI orchestration.
