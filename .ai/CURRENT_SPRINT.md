# CURRENT_SPRINT

Sprint: Runtime Service Boundary Hardening (Milestone 8)

## Goal
Remove remaining implementation shortcuts between the CLI persistence adapter and runtime services without adding lifecycle modules.

## Tasks
- Define explicit repository import/export ports for persistence adapters
- Extract reusable Artifact, Evaluation, and Approval lifecycle services
- Persist command idempotency keys across process restarts
- Define safe stale-lock inspection and recovery
- Add phase-specific persistence failure injection tests

## Definition of Done
Persistence no longer depends on repository-private hydration methods, lifecycle mutations have reusable service boundaries, and restart-safe idempotency is tested.

## Out of Scope
Authentication
Discovery Runtime
Validation Runtime
Product Runtime
Web UI
Discovery commands
LLM/AI provider integration
