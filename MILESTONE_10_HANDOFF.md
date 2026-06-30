# FounderOS Milestone 10 Handoff

Milestone 10 — Discovery Workflow v1 is complete.

The deterministic Discovery vertical slice now moves projects from `FOUNDER_BRIEF_COMPLETE` through `DISCOVERY_RUNNING` to an approved `OPPORTUNITY_SELECTED` state.

## Files changed

- Added `src/founderos_runtime/discovery.py`.
- Added `runtime/contracts/opportunity-report-content.schema.json`.
- Added `runtime/discovery.md`.
- Added `tests/test_discovery.py`.
- Updated the application facade, CLI, lifecycle services, diagnostics, package exports, and contract registry.
- Updated acceptance tests and the architecture, runtime, README, changelog, roadmap, sprint, project context, and engineering decisions documentation.

## Discovery design

- Accepts Opportunity Candidate data from a local JSON file.
- Validates the candidate problem, target user, assumptions, risks, and six integer component scores from 0 through 10.
- Calculates `total_score` as the unweighted sum of the six component scores.
- Ranks candidates deterministically by descending score, then problem and target user.
- Persists a structured Opportunity Report with Founder Brief lineage.
- Creates correlated WorkflowRun, AgentRun, Artifact, Evaluation, Approval, Decision, Transition, and Event records.
- Uses the existing guarded state-machine transitions.
- Requires explicit human approval before selecting the recommended opportunity.
- Redacts Opportunity Report content from default audit output.
- Supports deterministic replay, resume, and persisted command idempotency.

## CLI commands added

- `founderos discovery --input candidates.json`
- `founderos approve-opportunity --rationale "..."`

Existing CLI behavior remains intact.

## Tests added

Discovery coverage includes:

- rejection without an approved Founder Brief;
- Opportunity Report creation;
- deterministic scoring and ranking;
- invalid candidate rejection;
- blocked transition without approval;
- successful opportunity selection after approval;
- planner behavior before, during, and after Discovery;
- complete audit correlation and default redaction;
- deterministic replay and resume;
- CLI behavior; and
- persisted command idempotency after restart.

Final verification:

- 86 total tests passed.
- 11 Discovery-specific tests passed.
- Python compilation passed.
- `git diff --check` passed.

## What works now

FounderOS can deterministically accept local opportunity candidates, produce and persist a contract-valid Opportunity Report, evaluate it, request human approval, record the selected opportunity as a Decision, transition to `OPPORTUNITY_SELECTED`, and reconstruct the result from the event history.

## Limitations

- Candidate evidence and component scores are supplied by the user.
- All scoring dimensions currently have equal weight.
- Discovery v1 performs no market research or evidence gathering.
- No web browsing, LLM, external API, database, Validation, Product Design, or Web UI functionality was added.

## Recommended next milestone

Milestone 11: Authorization Policy Foundation. Centralize actor permissions and authorization checks before expanding the executable lifecycle into Validation.
