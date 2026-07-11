# Atlas Predictive Change Intelligence (PR-036A — architecture)

The deterministic foundation for answering "what happens if I make this
change?" — see the Prediction Architecture section of `ARCHITECTURE.md`
for the full design.

- `models.py` — ChangeRequest, Boundary, PredictedOutcome, Prediction,
  ConfidenceAssessment (plain JSON, AI-consumable later, never a secret).
- `change_requests.py` — open change-type registry (nothing hardcoded).
- `dependency.py` — extensible layered dependency graph; links traverse
  both interface endpoints; first builder from topology snapshots.
- `impact.py` — blast radius by *lost reachability*, bucketed across
  devices/interfaces/protocols/services/applications/sites/users.
- `critical_paths.py` / `redundancy.py` — which forwarding paths break,
  and whether alternates exist.
- `rollback.py` — complexity, reversibility, prerequisites per change type.
- `confidence.py` — documented arithmetic, capped at 0.95, root-cause
  confidence bands reused.
- `recommendations.py` — CAB-ready advice from the prediction.
- `simulator.py` — the pipeline + evaluator registry, seeded with honest
  first evaluators (shutdown-interface, reboot-device). Unmodeled change
  types predict with explicit unknowns and low confidence — never guesses.

PR-036B implemented the first vertical slice on this architecture:
- `risk.py` — Low/Medium/High/Critical from documented, auditable factors
  (unknown redundancy is a risk; verified redundancy reduces it).
- `recommendations.py` — a structured `Advice` ladder: CAB approval /
  investigate redundancy / maintenance window / fresh discovery / proceed,
  always with reasons.
- `service.py` — `predict_change()` over a scope's real artifacts
  (snapshot, history freshness, target instability, captured config,
  intelligence health, site catalog) + CAB-ready JSON/markdown reports.
- GUI: the Predict page and the Latest Prediction dashboard panel.

Only interface shutdown (and reboot at architecture level) is modeled;
redundancy is topology-layer (unknowns stated, never assumed). No AI, no
LLM, no randomness.
