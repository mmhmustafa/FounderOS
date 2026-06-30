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

## Current Milestone
Implement the Runtime Foundation against the approved Milestone 2 contracts.

## Planned
- Executable Project State repository and event boundary
- State Machine and guarded transitions
- Workflow Engine
- Agent and Artifact Registries
- Decision, Evaluation, Approval, and Knowledge services
- Discovery, Validation, and Product runtimes
- Executable application and persistent storage

The runtime component files are completed contract-level specifications, not application implementations.

## Long-term Goal
Evolve FounderOS into a web application with persistent project state and AI orchestration.
