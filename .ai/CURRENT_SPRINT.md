# CURRENT_SPRINT

Sprint: Minimal First-Party App Package Manifest Foundation (PR-003)

## Goal
Define an immutable, independently validated first-party App Package Manifest that indexes exact Workflow and Agent definitions plus supporting assets without introducing execution or registry behavior.

## Prerequisites Completed
- PR-001 Agent Manifest Schema Foundation
- PR-002 Workflow Manifest Schema Foundation

## Expected Scope
- Package identity, version, Kernel compatibility, first-party trust declaration, and content digest
- Exact Workflow and Agent definition references
- Schema, prompt, rubric, policy, fixture, test, documentation, and configuration-overlay references
- No App registry, installation, execution, Provider, Tool, CLI, Web UI, or marketplace behavior

## Definition of Done
A bundled first-party App package can be validated as an immutable asset index without duplicating Workflow execution semantics or Kernel mutation authority.
