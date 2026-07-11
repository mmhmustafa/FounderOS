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

No GUI in this PR (deliberate: no placeholder cruft); the prediction API
is service-level and fully tested. No AI, no LLM, no randomness.
