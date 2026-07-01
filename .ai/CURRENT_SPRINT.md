# CURRENT_SPRINT

Sprint: Prompt Pack Manifest Schema Foundation (PR-006)

## Goal
Define immutable, versioned prompt-pack metadata and safe template references without implementing prompt rendering or Provider integration.

## Prerequisites Completed
- PR-001 Agent Manifest Schema Foundation
- PR-002 Workflow Manifest Schema Foundation
- PR-003 App Package Manifest Schema Foundation
- PR-004 Manifest Loader Foundation
- PR-005 Workspace Foundation

## Expected Scope
- Prompt-pack identity, version, purpose, variables, input/output schema references, and safety/data-handling metadata
- Package-relative immutable template references and deterministic validation
- Workspace compatibility only if required for loading; no rendering, Provider, model configuration, execution, CLI, or Web UI

## Definition of Done
Apps can index a precise validated prompt-pack contract while prompt content remains a separate immutable asset and no execution capability is introduced.
