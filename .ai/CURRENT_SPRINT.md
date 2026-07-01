# CURRENT_SPRINT

Sprint: Evaluation Rubric Manifest Schema Foundation (PR-008)

## Goal
Define immutable, versioned declarative Evaluation rubrics that map exactly to the deterministic PR-007 runner without adding Workflow execution or persistence.

## Prerequisites Completed
- PR-001 through PR-005 manifest and Workspace foundations
- PR-006 Mock Provider Foundation
- PR-007 Evaluation Contract and Runner Foundation

## Expected Scope
- Rubric identity, version, target type, score threshold, and deterministic Evaluation rules
- Validation for rule parameters supported by PR-007
- One first-party example plus Manifest Loader/Workspace support only if required
- No Workflow/Agent execution, Provider invocation, human Approval, CLI, persistence, Event, or Kernel mutation

## Definition of Done
Apps can package a validated rubric whose rules can be translated directly into PR-007 Evaluation contracts without introducing another scoring or execution model.
