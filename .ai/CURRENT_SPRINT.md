# CURRENT_SPRINT

Sprint: Authorization Policy Foundation (Milestone 12C)

## Goal
Define and enforce local runtime authorization policy without adding external authentication or lifecycle modules.

## Tasks
- Define actor capabilities and Project ownership rules
- Enforce authorization at application and lifecycle service boundaries
- Protect human Approval and State Machine operations
- Add redacted denial diagnostics
- Add positive and negative authorization tests

## Definition of Done
Unauthorized actors cannot mutate protected records or advance state, while authorized local founders retain existing CLI behavior.

## Out of Scope
Authentication
Validation Runtime
Product Runtime
Web UI
LLM/AI provider integration
App package/runtime implementation
Tool execution
Knowledge runtime
