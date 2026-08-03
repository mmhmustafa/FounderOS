# PR-173 — Operational State Validation Framework — Engineering Handover

**Status: implemented per the approved architecture review
(`PR-173_OPERATIONAL_STATE_VALIDATION.md`), tested and validated on the live 85-device estate.**
Full regression suite: **2,948 passed / 0 failed / 2 skipped / 897 subtests** (+42 over PR-172).

## 1. Architectural compliance

All ten steps implemented in order. Every non-goal honoured: no collector added, no driver
touched, no polling, no state history store, no temporal verdict emitted, no second registry,
no OIR change, no new objective, **no `(engine, "assess")` dispatch key** (PR-171's forbidding
test passes unmodified), and PRISM, graph construction and the Policy Engine untouched.

The S3 acceptance gate held: **every PR-172 test passed unmodified.**

One deviation within the review's own intent: success criterion 4 is a literal grep, so the
listing helper was **renamed** (`_session_is_established` → `_established_by_rule`) rather than
kept. It now reads its vocabulary back from the rule data, so a listing and a verdict can never
disagree about what "established" means.

## 2. What shipped — and the live proof

The review's defining risk (R1: stale state presented as current) was proven live on the first
ask. The estate's last discovery is **5 days old**:

> **"Is BGP healthy?"** → *"The BGP sessions could not be judged: the observations are too old to
> support a verdict. 28 device(s) hold observations older than the workspace's staleness horizon
> (60 minute(s); observed 5 day(s) ago)."* — chip **Not enough evidence**.

Pre-PR-173 code would have confidently listed those 5-day-old sessions as current. Widening the
workspace horizon to 7 days (the new `state_horizon_minutes` preference; restored to 60
afterwards):

> *"BGP sessions: Healthy — every observation is in its expected state **(78 of 78)**;
> **observed 5 day(s) ago**. 57 evaluation(s) were not applicable — those devices do not run
> BGP."* — High confidence, and the age is stated even when the evidence is fresh by policy.

Also verified live: OSPF (63 stale devices refused); **"Is HSRP healthy?"** → refusal naming the
missing *shape* half and listing what Atlas *can* assess; **"Are interfaces flapping?"** →
temporal refusal quoting the operator's word; the estate summary and PR-172 configuration
validation byte-identical.

## 3. Implementation summary

- **Dating without touching the graph.** Observations are dated by a read-only join: their own
  `observed_at` when a parser stamped one, else the contributing profile's discovery timestamp
  (`observed_by` → contribution). A set with any undatable member is undated, and undated is
  **stale** — Atlas never assumes unstamped means recent.
- **The freshness gate.** FRESH within the horizon; AGEING to 4× (verdict allowed, age stated,
  Medium confidence); STALE beyond, undated, or future-dated ⇒ *Not enough evidence*. The horizon
  is workspace policy (`state_horizon_minutes`, default 60, bounds 5–10080).
- **`StateRule`** — the second CORTEX `Rule` adapter, over structured observations carried in
  `Evidence.payload` (a field the reasoning layer already had). It inherits the confidence
  calculus, result schema, provenance (`atlas-state-rules@1.0`), the four dispositions and
  PR-172's `applicable` flag. Closed operator vocabulary: `all_in_states`, `none_in_states`,
  `min_count`, `ratio_at_least`.
- **Health as data.** Role suffixes (`Full/DR`) are identity, not health; `admin-down` is excluded
  **by name** as configured intent, never counted as a failure.
- **Degraded vs Failed is decided at the observation level** — "27 of 28 Established" is Degraded
  even when every evaluation failed; Failed means *nothing* is in its expected state.
- **`Unstable` is reserved**: defined in code, never emitted, pinned by a test, so the word cannot
  later be redefined to something weaker.

## 4. Files changed

**New:** `investigation/state.py` (provider + freshness), `investigation/state_rules.py` (adapter +
rules), `tests/test_state_validation.py` (**42 tests**), `docs/ATLAS_STATE_VALIDATION.md`,
`docs/reviews/PR-173_OPERATIONAL_STATE_VALIDATION.md`, this handover.

**Modified:** `routing/evidence.py` (identity keys — computed, never serialised, so stored graph
artifacts are unchanged), `investigation/validation.py` (aspect axis + state verdict projection),
`investigation/subjects.py` (+3 descriptor fields), `investigation/templates.py` (state template +
selection rung 1b), `investigation/engines.py` (state engine step; inline predicates deleted),
`investigation/orchestrator.py` (two refusals + the state summary branch),
`investigation/extraction.py` + `models.py` (temporal terms), `advisor/presentation.py` (2 markers,
state engine chip), `advisor/engine.py` + `advisor/service.py` + `web/routes.py` (horizon
threading), `workspace/administration.py` (the preference, with save-preservation so an unrelated
settings save never resets it), `docs/ATLAS_INVESTIGATOR.md`.

## 5. Tests

`tests/test_state_validation.py` — 42 tests across the provider, the freshness gate, the aspect
axis, the `StateRule` adapter, end-to-end verdicts, honest refusals, the synthetic-protocol
genericity test and the chip mapping. Headline tests: the staleness refusal (criterion 2) and
"adding a protocol is a shape plus rules" (criterion 5).

**R8 pinned-test edits — three, each reviewed and commented in place:**

1. `test_question_understanding.py` assess-ladder pin: "Is OSPF healthy at chennai?"
   `ospf-scope` → `ospf-state` (the deliberate upgrade from listing to judged verdict).
2. `test_investigation.py` selection pin: the same upgrade, plus a new assertion that
   "Show me OSPF for Mumbai" still selects the listing.
3. `test_investigation.py` OSPF listing test: repointed to the locate phrasing, so the listing
   behaviours it actually pins stay pinned.

"Show me BGP…" and endpoint questions keep their templates untouched.

## 6. Browser and accessibility validation

Verified in the browser on the live estate: stale → `verdict-unknown` / "Not enough evidence";
temporal refusal → `verdict-info` / "Informational"; healthy (wide horizon) → `verdict-ok` /
"Healthy". Every `aria-labelledby` target resolves; the heading ladder is unbroken. No new UI and
no CSS changed — PR-168's accessibility work stays authoritative. No server errors in the logs.

## 7. Performance impact

State answers run **160–220 ms** warm — observations are already in the graph, so there is no I/O
(the first ask, ~3.3 s, is the enterprise world build, not the state engine). Non-state questions
are unchanged; PR-172 configuration validation is unchanged at ~4 s.

## 8. Remaining limitations

- State is judged **as of the last discovery**. Atlas does not poll and retains no history, so
  flapping, instability and convergence remain honest refusals.
- HSRP/VRRP, STP, MLAG, EVPN and VPN state await one canonical shape and one parser each; their
  text is already collected on NX-OS and IOS-XE.
- Observation counts in the verdict sentence follow the **primary** rule if a subject ever gains
  more than one state rule.
- The horizon preference has no settings-page field yet (file/API only; an unrelated settings save
  preserves it).
- Interface state falls back to the device's raw status word when it reports something other than
  up / down / administratively down.

## 9. Future opportunities

The state history store is unblocked — the observation identity keys
(`device|bgp|vrf|af|peer`) ship in this PR precisely so it has a join key. With history:
`Unstable` becomes emittable, and the `min_count` / `ratio_at_least` operators already in the
vocabulary cover expected-count rules. Cross-device rules (HSRP pairs, MLAG sync, STP root)
remain the one genuinely new rule shape, and would be solved once for both aspects. A settings-page
field for the horizon is a small UI addition.
