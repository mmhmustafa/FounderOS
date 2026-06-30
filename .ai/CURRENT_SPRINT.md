# CURRENT_SPRINT

Sprint: Runtime Observability and Audit Diagnostics (Milestone 9)

## Goal
Make existing runtime operations diagnosable and auditable without adding lifecycle modules or external infrastructure.

## Tasks
- Define structured diagnostic and audit summaries
- Preserve command correlation across application and runtime boundaries
- Add safe inspection for runs, transitions, approvals, persistence, and recovery
- Define sensitive-field redaction rules
- Add end-to-end audit consistency tests

## Definition of Done
Operators can explain what happened, correlate commands to records and Events, and verify audit consistency without exposing sensitive content.

## Out of Scope
Authentication
Discovery Runtime
Validation Runtime
Product Runtime
Web UI
Discovery commands
LLM/AI provider integration
