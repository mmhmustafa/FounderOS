# CURRENT_SPRINT

Sprint: Evaluation Rubric Manifest and Loader Foundation (PR-011)

## Goal
Define loadable deterministic Evaluation rubric assets so Journey quality checks use declared rules instead of a minimal built-in availability floor.

## Prerequisites Completed
- PR-001 through PR-009 platform and Journey foundations
- PR-010 Plan Validation and Authorization Foundation

## Expected Scope
- Immutable rubric identity, version, target, score threshold, and deterministic rules
- Validation for rule parameters supported by the existing Evaluation Runner
- Loader integration for exact Workflow rubric references
- No real Provider, human Approval, persistence, CLI, Event, or Kernel mutation

## Definition of Done
A validated Workflow Evaluation reference resolves to an exact deterministic rubric that can be translated directly into existing Evaluation contracts without introducing another execution or scoring model.
