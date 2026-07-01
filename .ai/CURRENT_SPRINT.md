# CURRENT_SPRINT

Sprint: Bounded Manifest Discovery Foundation (PR-005)

## Goal
Discover supported Agent, Workflow, and App manifests beneath explicit trusted roots and validate each through PR-004 without creating a registry or executing definitions.

## Prerequisites Completed
- PR-001 Agent Manifest Schema Foundation
- PR-002 Workflow Manifest Schema Foundation
- PR-003 App Package Manifest Schema Foundation
- PR-004 Manifest Loader Foundation

## Expected Scope
- Explicit bounded roots and supported manifest filenames
- Deterministic path ordering and typed discovery failures
- Symlink/root-escape and ambiguous-kind protection
- Delegation to the existing stateless Manifest Loader
- No registry, version resolver, package installation, execution, Provider, Tool, CLI, or Kernel behavior

## Definition of Done
Callers can obtain a deterministic collection of validated manifests from a bounded source tree without assigning identity lifecycle, resolving versions, or executing anything.
