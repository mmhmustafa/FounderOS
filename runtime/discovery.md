# Discovery Workflow v1

> **Status:** Deterministic local vertical slice implemented

## Purpose

Transform an approved Founder Brief and founder-provided candidates into a structured Opportunity Report, obtain human Approval, record the selected opportunity Decision, and move the Project to `OPPORTUNITY_SELECTED`.

## Scoring

Each candidate includes problem, target user, pain, frequency, budget, AI advantage, MVP feasibility, founder fit, assumptions, and risks. Scores are integers from 0 to 10. `total_score` is their unweighted sum. Ranking is descending total, then problem and target-user text.

## Runtime Sequence

1. Require `FOUNDER_BRIEF_COMPLETE` and an approved Founder Brief.
2. Start the Discovery WorkflowRun and enter `DISCOVERY_RUNNING` using the Founder Brief Approval.
3. Run the deterministic Opportunity Scoring AgentRun.
4. Persist the Opportunity Report, Evaluation, and pending Approval.
5. Remain blocked until a human approves the report.
6. Approve the Artifact, record the selection Decision, complete the WorkflowRun, and request `OPPORTUNITY_SELECTED`.

## Inputs and Outputs

Input is local JSON only. Outputs are an Opportunity Report, runs, Evaluation, Approval, Decision, Transitions, and ordered Events. No web, model, provider, or external API is used.

## Risks

- Scores are founder-provided judgments rather than market evidence.
- Equal weighting is intentionally simplistic.
- Discovery v1 performs no competitor, market-size, or customer research.

## Next Step

Define authorization policy before implementing Validation or nondeterministic research.
