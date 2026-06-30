# CURRENT_SPRINT

Sprint: First Executable Vertical Slice (Milestone 5)

## Goal
Use the Runtime Planner and Runtime Foundation to create, resume, produce, review, and approve a Founder Brief without implementing Discovery or other lifecycle modules.

## Tasks
- Define the Founder Setup Workflow and minimum Agent definition
- Define the Founder Brief content contract/template
- Implement the vertical-slice application service over existing runtime boundaries
- Persist and resume the slice using a minimal approved persistence adapter
- Require human review and Approval before transition
- Add end-to-end tests from Project creation through `FOUNDER_BRIEF_COMPLETE`

## Definition of Done
A Project can be created or resumed, a Founder Brief can be produced and approved, and the guarded transition to `FOUNDER_BRIEF_COMPLETE` is persisted and replayable.

## Out of Scope
Authentication
Discovery Runtime
Validation Runtime
Product Runtime
Web UI
General-purpose CLI
LLM/AI provider integration
