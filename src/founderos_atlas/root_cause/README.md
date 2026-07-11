# Atlas Root Cause Analysis Engine (PR-035)

Evidence-based reasoning that explains *why* — deterministically, never AI.

- **Evidence** (`evidence.py`): configuration, operational, topology,
  discovery, and incident artifacts normalized into citable items with the
  run timestamp, a causal rank, affected devices/interfaces, and the source
  artifact.
- **Timeline** (`timeline.py`): ordered by timestamp, then causal rank
  (configuration → interface → protocol → topology → incident). Atlas has
  run-level timestamps, not per-event device clocks, so intra-run ordering
  is causal — documented, never invented seconds.
- **Correlation** (`correlation.py` + internal `graph.py`): edges only
  along documented rules and real shared devices/interfaces/adjacency —
  config→interface on the same device (stronger when the interface is
  named in the change), interface→protocol on the same interface,
  failure→removal/discovery-failure of a *previous-topology* neighbor.
  Unrelated evidence is never connected. The causal graph is internal;
  the artifact carries derived reasoning with evidence ids.
- **Hypotheses** (`hypothesis.py`): competing rule-based causes per
  problem — configuration change, physical failure, deliberate shutdown,
  authentication issue, device unreachable, upstream isolation, expected
  maintenance — each with supporting AND contradicting evidence.
- **Confidence** (`confidence.py`): documented arithmetic (base + evidence
  count − contradictions + interface match + recurrence − staleness),
  clamped to 0.95 (never 100%), banded very-high/high/medium/low.
- **Explanation** (`explanation.py`): the reasoning chain follows the
  causal graph and cites evidence ids in every sentence; renderers for the
  JSON artifact, markdown report, Morning Brief section, and incident
  section.
- **Historical replay** (`engine.analyze_record`): "what happened
  yesterday" re-analyzes any archived discovery's stored artifacts and —
  tested — reproduces the stored explanation byte for byte.

The pipeline writes `root_cause_report.json`/`.md` beside every run's
artifacts (profile-scoped, archived in history). Incidents automatically
carry the analysis; the dashboard shows "Most Likely Root Cause" when
confidence is high; the Morning Brief adds "Most Important Root Cause".
