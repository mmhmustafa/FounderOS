# Atlas Decision Log

Key architectural decisions, their WHY, and where they were made.
(Concise by design — the CHANGELOG carries the detail.)

| # | Decision | Why | PR |
|---|---|---|---|
| 1 | Profile-scoped isolation keyed by stable `profile_id` | one network's discovery can never overwrite or be compared against another's | 031A |
| 2 | Legacy unscoped data is archived out of aggregation once profiles hold data | stale artifacts must not duplicate devices or skew health | 031A |
| 3 | Discovery jobs run in-process (daemon thread + global run lock), never a child process | determinism, observability, no shell surface | 032 |
| 4 | Credential ordering is lockout-safe: remembered success → most-specific scope → profile default | wrong-password retries lock enterprise accounts | 033 |
| 5 | Identity merging: serials always; hostname+IP only within a declared admin domain; names/IPs alone never | real enterprises reuse hostnames and RFC1918 space | 033/037A |
| 6 | Health scores are explained arithmetic (`score = 100 + Σ factor points`) | a score no one can audit is a score no one trusts | 034 |
| 7 | RCA confidence caps at 0.95 and hypotheses carry contradicting evidence too | honesty over false certainty | 035 |
| 8 | Prediction is an open registry of change types + evaluators; unmodeled types predict honestly | new change types must plug in without redesign | 036A |
| 9 | Redundancy is *unknown, not absent* when no alternate path is visible | undiscovered links may exist; never assume | 036B |
| 10 | Management-plane loss requires a verified alternate before proceeding advice | you must be able to reach a device to roll it back | 036C |
| 11 | FLOW reports equal-cost paths as AMBIGUOUS and never walks past the first deterministic failure | never guess which path traffic takes | 037 |
| 12 | Federation is a derived view under `.atlas/enterprise/`, regenerated from profile evidence | never a second source of truth | 037A |
| 13 | A link's far-end NAME resolves only within the observing profile | cross-profile hostname matching would invent connectivity | 037A |
| 14 | Search is a flat in-memory index behind an evidence fingerprint — no Elasticsearch, no fuzzy ranking | deterministic, dependency-free, instant at enterprise scale | 038 |
| 15 | The `hidden` attribute must always have a CSS state (`[hidden]{display:none}`) when author CSS sets display | author CSS silently defeats the UA rule (the PR-038 modal bug) | 038.1 |
| 16 | Compass derives dependencies from prediction blast radii + reload semantics only; conflicts warn, never block | an advisor, not an approval gate; the engineer stays in control | 039 |
| 17 | An IOS upgrade is predicted through reload semantics | an upgrade deterministically includes a reload — evidence, not invention | 039 |
| 18 | Mission is pure orchestration (`web/mission.py` shapes; engines execute) | the workspace must never become another source of truth | 040 |
| 19 | Browser-local context only (recent searches/devices in localStorage) | no sensitive activity data persisted server-side | 040 |
| 20 | Global scope label is "Enterprise" (id stays `all`) | enterprise-first language; stable URLs/sessions | 041 |
| 21 | The enterprise graph is cached behind the search fingerprint | stop rebuilding the graph + rewriting artifacts per request | 041 |
