# CURRENT_SPRINT

Sprint: Prompt Pack Manifest Schema Foundation (PR-007)

## Goal
Define immutable, versioned prompt-pack metadata and safe template references without implementing prompt rendering or real Provider integration.

## Prerequisites Completed
- PR-001 Agent Manifest Schema Foundation
- PR-002 Workflow Manifest Schema Foundation
- PR-003 App Package Manifest Schema Foundation
- PR-004 Manifest Loader Foundation
- PR-005 Workspace Foundation
- PR-006 Mock Provider Foundation

## Expected Scope
- Prompt-pack identity, version, purpose, variables, input/output schema references, and safety/data-handling metadata
- Package-relative immutable template references and deterministic validation
- No prompt rendering, Provider registry, real model configuration, network, Agent/Workflow execution, CLI, or Web UI

## Definition of Done
Apps can index a precise validated prompt-pack contract while prompt content remains a separate immutable asset and no real Provider or execution capability is introduced.
