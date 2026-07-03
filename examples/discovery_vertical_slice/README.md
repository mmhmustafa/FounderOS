# Discovery Vertical Slice

This first-party example demonstrates the complete deterministic FounderOS path:

```text
Workspace -> Planner -> Plan Validation -> Authorization -> Journey Runner
          -> Mock Provider -> Evaluation Rubric -> JourneyResult
```

The package includes exact Agent, Workflow, App, rubric, Founder Brief, Provider fixture, schema, and expected-output assets. `founderos_runtime.demo.run_discovery_vertical_slice()` loads them from disk, but all orchestration state and generated results remain in memory.

The Mock Provider is intentional. It proves routing, correlation, Artifact generation, quality evaluation, and deterministic replay without network access, API keys, cost, latency, or nondeterministic model output.

The demonstration proves that independently built platform layers compose through their public contracts. The Planner decides; validation checks structure; authorization checks capabilities; the Journey follows the fixed plan; the Provider supplies fixture-backed structured output; the rubric uses the existing Evaluation Runner; and the immutable JourneyResult contains both the generated Opportunity Report and Evaluation evidence.

Intentionally excluded:

- real AI Providers or web research;
- persistence, Events, or Project state mutation;
- human Approval execution or transition application;
- CLI and Web UI;
- authentication, marketplace installation, and network-specific product packs.

Approval and transition-request steps remain visible but skipped. A successful demo means the deterministic in-scope steps passed; it does not mean a human approved the opportunity or Project state changed.

PR-013 should add a thin Demo CLI over this helper without moving orchestration logic into the command layer.

