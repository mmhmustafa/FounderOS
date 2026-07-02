# CURRENT_SPRINT

Sprint: Journey Rubric Resolution Foundation (PR-012)

## Goal
Resolve exact Workflow Evaluation rubric references so Journey quality checks use declared reusable rules instead of a minimal built-in availability floor.

## Prerequisites Completed
- PR-001 through PR-010 platform, Journey, validation, and authorization foundations
- PR-011 Evaluation Rubric Manifest and Loader Foundation

## Expected Scope
- Bounded exact rubric reference resolution
- Journey integration using existing EvaluationRubric and EvaluationRunner contracts
- Validation and authorization behavior preserved before execution
- No real Provider, human Approval, persistence, CLI, Event, or Kernel mutation

## Definition of Done
A validated Workflow Evaluation reference resolves to an exact rubric and Journey execution uses its rules without introducing another scoring model or runtime mutation boundary.
