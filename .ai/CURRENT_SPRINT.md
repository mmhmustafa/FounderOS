# CURRENT_SPRINT

Sprint: Prompt Pack Manifest Schema Foundation (PR-004)

## Goal
Define immutable, versioned prompt-pack metadata and safe asset references without implementing prompt rendering or Provider integration.

## Prerequisites Completed
- PR-001 Agent Manifest Schema Foundation
- PR-002 Workflow Manifest Schema Foundation
- PR-003 App Package Manifest Schema Foundation

## Expected Scope
- Prompt-pack identity, version, purpose, variables, input/output schema references, safety/data-handling metadata, and template asset references
- Deterministic schema validation and a first-party example
- No prompt renderer, Provider integration, model configuration, Agent execution, App loading, CLI, or Web UI

## Definition of Done
Apps can index a precise prompt-pack contract while prompt content remains a separate immutable asset and no execution capability is introduced.
