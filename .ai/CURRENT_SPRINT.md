# CURRENT_SPRINT

Sprint: Runtime Foundation

## Goal
Implement the approved contracts as a minimal, testable runtime foundation without starting lifecycle modules or user interfaces.

## Tasks
- Select the minimal runtime language and dependency baseline
- Implement schema loading and validation
- Implement repository interfaces and in-memory contract test doubles
- Implement Project State and ordered Event persistence boundaries
- Implement guarded State Machine transitions with optimistic concurrency
- Implement WorkflowRun and AgentRun lifecycle foundations
- Implement Artifact, Decision, Evaluation, and Approval boundaries
- Automate all contract-level acceptance scenarios

## Definition of Done
The runtime foundation enforces Milestone 2 schemas and invariants and passes all contract-level acceptance scenarios without implementing Discovery, Validation, Product, CLI, or web behavior.

## Out of Scope
Web UI
Database implementation
Authentication
Discovery Runtime
Validation Runtime
Product Runtime
Founder Brief vertical slice
