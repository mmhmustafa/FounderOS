# CURRENT_SPRINT

Sprint: Workflow Manifest Schema Foundation (PR-002)

## Goal
Define a versioned, independently validated Workflow Manifest that references exact Agent Manifest versions while preserving Workflow as the sole executable process definition.

## Prerequisite Completed
PR-001 added the strict Agent Manifest schema, Product Manager example, and deterministic contract tests without changing runtime behavior.

## Expected Scope
- Workflow identity, version, lifecycle/utility classification, inputs, outputs, steps, quality gates, failure policy, and exact Agent references
- Contract-only examples and deterministic schema validation
- No loader, registry, coordinator, execution, Provider, Tool, memory, CLI, or UI behavior

## Definition of Done
Workflow metadata can reference exact Agent definitions and be validated independently without introducing a second execution or mutation authority.
