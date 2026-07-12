# Atlas Engineering Principles

The rules every Atlas PR has followed since PR-001 — and must keep
following.

## Evidence

1. **Never guess.** A conclusion exists only because evidence produced
   it. When evidence is insufficient, the answer is *Unknown* — stated,
   never hidden.
2. **Cite everything.** Every merge, ranking, ordering, prediction, and
   recommendation names the evidence it rests on. Engineers must always
   see the WHY.
3. **Confidence is arithmetic.** Documented factors, never vibes; capped
   below 100% — always. Bands (very-high/high/medium/low) are shared
   across every engine.
4. **Deterministic before AI.** Identical evidence yields byte-identical
   output. No wall clock in business logic (timestamps are injected), no
   randomness, no fuzzy ranking. A future AI layer explains; it never
   decides.

## Architecture

5. **Engines are authoritative; surfaces orchestrate.** Discovery,
   federation, prediction, path intelligence, compass, and search own
   their logic. The GUI, CLI, Mission, and future REST/assistant clients
   are thin consumers of the same services.
6. **One implementation per concept.** Reuse before rebuild: Compass
   consumes Prediction; Mission consumes everything; Search indexes what
   engines produced. Extracting a helper beats duplicating it.
7. **Open registries over hardcoding.** Change types, evaluators, match
   rules, and search groups extend at runtime without model changes.
8. **Profiles are observation points, never boundaries.** Per-profile
   scopes stay isolated on disk; the enterprise graph is a derived VIEW,
   regenerated from evidence — never a second source of truth.

## Safety

9. **No secrets, anywhere.** Reports, APIs, logs, HTML, snapshots, test
   fixtures — credential *references* only. Read-only network posture
   (`show` commands); the GUI binds to 127.0.0.1.
10. **Backward compatibility is mandatory.** Artifacts are additive;
    scope ids and layouts are stable; deliberately replaced behavior is
    called out and its tests are updated, never silently weakened.

## Delivery

11. **GUI is the primary experience** — every capability must be usable
    without the CLI, and empty states teach.
12. **Small PRs, full suites.** Every PR runs the complete pytest suite
    green before handover; corrections found in manual CML testing become
    pinned regression tests.
