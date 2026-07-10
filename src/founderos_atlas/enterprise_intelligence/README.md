# Atlas Enterprise Intelligence Engine (PR-034)

Turns the deterministic artifacts every discovery produces into answers a
network manager actually needs: *what matters, what changed, should I care,
what should I do first.*

- **Health** (`health.py`): a calculated 0-100 score. Every point is a
  named, capped factor with evidence — `score == clamp(100 + sum(points))`
  always holds; the weight table is documented in the module docstring.
  Confidence reflects evidence quality (baseline present, freshness,
  discovery failures), never the health itself.
- **Risk** (`risk.py`): every finding carries severity (how bad), risk
  (how much damage from where it sits — blast radius, recurrence),
  confidence (how directly observed), and urgency (when to act).
- **Priority** (`priority.py`): a documented weighted ranking producing the
  top 5 things to care about; deterministic ties.
- **Recommendations** (`recommendations.py`): likely cause first, concrete
  next step second, with cross-signal reasoning (an interface failure on a
  device whose configuration changed points at the change, not hardware).
- **Trends** (`trend.py`): health trajectory versus the previous run's
  archived report, configuration churn, recurring instability, topology
  stability across the recent history window.
- **Summary** (`summary.py`): the JSON artifact (machine contract), the
  markdown report, and the Morning Brief v2 section.

The pipeline writes `intelligence_report.json`/`.md` beside the run's other
artifacts (profile-scoped) and archives them in history, which is what
makes trends comparable run over run. Everything is rule-based and
deterministic — no AI, no randomness. The JSON is deliberately shaped so a
future AI layer can consume summary, evidence, risk, confidence, and
recommendations without recomputation; no LLM is integrated here.
