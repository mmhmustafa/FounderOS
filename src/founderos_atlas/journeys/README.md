# Atlas Journeys

Atlas Journeys are domain compositions executed by the existing FounderOS `JourneyRunner`. Atlas supplies deterministic networking computations and Artifact models; FounderOS remains responsible for Workspace loading, planning, plan validation, authorization, ordered execution, Evaluation, and immutable `JourneyResult` production.

## Morning Brief

`MorningBriefJourney` accepts a current `TopologySnapshot` and an optional previous Snapshot. It compares canonical device facts, computes changes and operational recommendations, creates a structured `MorningBrief`, evaluates it through the declared rubric, and renders deterministic Markdown.

The Workflow is a utility Workflow. It requests no Project state transition, external Activity, Provider, Tool, Approval, persistence, or network access. The CLI alone owns optional Markdown file delivery.

## Boundaries

- No AI or LLM call
- No live discovery or network access
- No persistence inside Journey execution
- No scheduler, email, notification, or GUI
- No Atlas-specific planning or authorization implementation
