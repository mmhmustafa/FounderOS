# Runtime Observability and Audit Diagnostics

> **Status:** Milestone 9 implemented

## Purpose

Provide a read-only explanation of what happened, in what order, which command caused it, which Approval allowed it, which Transition changed state, and which Artifacts were involved.

## Diagnostic Sections

`RuntimeDiagnostics` summarizes Project state, ordered Events, command groups and timing, WorkflowRuns, AgentRuns, Approvals, Evaluations, Transitions, Artifacts, persistence health, and consistency checks.

## Correlation

Each CLI mutation receives one root identifier in the form `cli:<operation>:<token>`. Child lifecycle and transition Events retain that root with optional suffixes. Audit output normalizes every child correlation back to the root command.

## Traceability

Transitions expose their WorkflowRun, Approval references, and Artifacts targeted by those Approvals. The ordered timeline retains Event subject, actor, sequence, correlation, timestamp, and redacted payload.

Discovery retains the correlation chain from command to WorkflowRun, AgentRun, Opportunity Report, Evaluation, Approval, selection Decision, and Transition.

## Redaction

Founder Brief content is omitted by default. Approval rationale and known sensitive fields are replaced with `[REDACTED]`. Explicit `--include-sensitive` output includes Artifact content and sensitive fields; callers are responsible for handling it securely.

## Consistency

Audit checks confirm gap-free Event sequences, deterministic Project replay equality, and resolution of transition Events to Transition records. Checks report only; they never repair or mutate state.

## Risks

- Correlation timing measures persisted Event timestamps, not CPU or external wall-clock phases.
- Older pre-Milestone-9 Events may have correlations that cannot be grouped into a CLI root.
- Redaction is rule-based and must evolve as new sensitive fields are introduced.
- Explicit sensitive output can expose founder or customer context.

## Next Step

Define local authorization capabilities and redacted denial diagnostics before adding lifecycle workflows.
