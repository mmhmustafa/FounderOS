# CURRENT_SPRINT

Sprint: Durable Activity and Side-Effect Contracts (Milestone 12D)

## Goal
Define durable contracts for bounded, recoverable future Provider and Tool activities without executing either capability.

## Tasks
- Define Activity identity, exact references, attempts, leases, and deadlines
- Define cancellation, retry classification, and idempotency
- Define input/output and external-effect receipts
- Define crash recovery, reconciliation, and compensation semantics
- Define correlation with commands, runs, outputs, approvals, decisions, transitions, and Events

## Definition of Done
Activity and side-effect contracts are precise enough for later adapters without adding Provider or Tool execution.

## Out of Scope
Provider implementation
Tool implementation
Validation Runtime
App package/runtime implementation
Web UI
Cloud/multi-user execution
