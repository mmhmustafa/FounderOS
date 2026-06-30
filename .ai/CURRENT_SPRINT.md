# CURRENT_SPRINT

Sprint: Durable Runtime Persistence (Milestone 6)

## Goal
Make the completed Founder Setup slice survive process restarts without changing its runtime contracts or adding lifecycle modules.

## Tasks
- Define storage ports for records, ordered Events, and artifact content
- Select one minimal transactional durable adapter
- Rehydrate idempotency and runtime composition after restart
- Run Founder Setup acceptance tests against both storage implementations

## Definition of Done
Founder Setup resumes after a real process restart with identical Project state, event order, content digest, approvals, and idempotency behavior.

## Out of Scope
Authentication
Discovery Runtime
Validation Runtime
Product Runtime
Web UI
General-purpose CLI
LLM/AI provider integration
