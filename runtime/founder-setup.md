# Founder Setup Vertical Slice

> **Status:** Executable through the runtime and local CLI

## Scope

The Founder Setup service is the first end-to-end runtime path. It creates or resumes a Project, verifies the Planner recommendation, starts version-pinned WorkflowRun and AgentRun records, validates a structured Founder Brief, stores canonical JSON content with a SHA-256 digest, records a passing schema Evaluation, and requests human Approval.

Only an approved Artifact, passing Evaluation, successful WorkflowRun, and current human Approval may satisfy the guarded `FOUNDER_SETUP -> FOUNDER_BRIEF_COMPLETE` transition.

## Determinism and Recovery

- Content assembly is deterministic and invokes no model or external provider.
- Events are appended in a gap-free per-Project sequence.
- Project state is checked against deterministic Event replay during resume.
- Repeating a completion correlation returns the original Transition.
- A stale expected Project revision produces a recorded rejected Transition.

## Limitations

The CLI reloads records and content between invocations and now provides single-writer protection plus backup recovery. File replacement is not transactional across the entire directory. Authentication, production authorization policy, generalized workflow execution, and lifecycle modules after Founder Setup are not implemented.
