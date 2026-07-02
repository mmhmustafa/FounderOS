# Evaluation Rubric Manifest Contract

An Evaluation Rubric is an immutable, versioned declaration of reusable quality rules for an Artifact type. It defines what to check and the minimum passing score; it does not evaluate content by itself.

The `EvaluationRunner` remains the executable deterministic assessment engine. A loaded rubric translates directly into existing `EvaluationRule` objects and supplies the runner's `minimum_score`. There is no second rule language or scoring implementation.

Rubrics are declarative so Workflows and first-party Apps can reference exact quality gates without embedding Python behavior. They contain no prompts, Provider/model configuration, secrets, runtime state, Approval decisions, or executable code. A `custom` rule names a pre-registered pure handler; the manifest never carries handler code.

Relationships:

- **Workflow:** declares an exact rubric asset reference at an Evaluation checkpoint.
- **Artifact:** `applies_to` identifies the Artifact type and its schema reference.
- **Journey Runner:** may resolve and run a rubric in a future integration; PR-011 does not change Workflow execution.
- **Approval:** consumes Evaluation evidence at a separate human-control boundary. Passing a rubric never grants Approval.

Reusable versioned rubrics make quality gates consistent across Workflows while preserving deterministic replay and review.

