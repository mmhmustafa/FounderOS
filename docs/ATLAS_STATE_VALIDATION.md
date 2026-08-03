# Atlas Operational State Validation (PR-173)

*Know whether the network is actually working — as of the last observation, and honestly no
further.*

Architecture review: `docs/reviews/PR-173_OPERATIONAL_STATE_VALIDATION.md` (authoritative design;
this document describes what shipped).

## The model

```
Subject + Objective              (PR-171 extraction — unchanged)
        │
        ▼
State Capability                 DISCOVERED, as in PR-172:
= SubjectDescriptor.state_kind   a subject with no observation shape,
  ∩ installed state rules        or a shape no rule judges, has NO
        │                        capability — and the refusal names
        ▼                        WHICH half is missing
Scope resolution                 (PR-171 — unchanged)
        │
        ▼
Observation retrieval            typed observations the Enterprise
(investigation/state.py)         Graph already carries, DATED by a
        │                        read-only join (own stamp, else the
        ▼                        contributing profile's discovery time)
FRESHNESS GATE                   stale or undated ⇒ NOT ENOUGH
        │                        EVIDENCE, with the age named
        ▼
State rules (state_rules.py)     the second CORTEX Rule adapter —
        │                        structured observations, never text
        ▼
CORTEX ReasoningEngine           UNCHANGED — confidence, provenance,
        │                        dispositions, `applicable` for free
        ▼
Verdict                          a projection — computed, never stored
```

## The freshness contract

**State is perishable.** A three-day-old `Established` is not evidence that BGP is up now.

- Every observation set is dated: its own `observed_at` when a parser stamped one, else the
  contributing profile's discovery `observed_at` (the `observed_by` → contribution join). Atlas
  never invents a timestamp; a set with any undatable member is undated.
- **FRESH** (within the horizon): a verdict may stand. **AGEING** (one to four horizons): a verdict
  is allowed and the answer says *"the evidence is ageing"* at Medium confidence. **STALE** (beyond
  four horizons, undated, or future-dated): *Not enough evidence*, with the age named — never a
  health verdict.
- The horizon is **workspace policy** (`state_horizon_minutes`, default 60, bounds 5–10080), not
  code: a lab and a change-frozen production estate reasonably differ.
- Every verdict sentence carries the observation age; the evidence citation carries the source
  command.

## Health as data

The old inline predicates (`_session_is_established`, `startswith("full")`) are **gone**. A health
rule is a `StateRuleDefinition` over a closed operator vocabulary — `all_in_states`,
`none_in_states`, `min_count`, `ratio_at_least` — judged by `StateRule`, the second adapter of
CORTEX's evidence-agnostic `Rule` protocol (`PolicyRule` is the first). State comparison folds case
and strips role suffixes: `Full/DR` and `Full/BDR` are one state wearing its role, which is
identity, not health. Shipped rules:

| Rule | Judges | Expected |
|---|---|---|
| `STATE-BGP-001` | `bgp-sessions` | every session Established (vendor spellings `estab`/`up` included as data) |
| `STATE-OSPF-001` | `ospf-adjacencies` | every adjacency Full |
| `STATE-IFACE-001` | `interface-status` | every enabled interface up — `admin-down` excluded **by name** (configured intent is not a failure) |

The listing templates (`bgp-scope`, `bgp-between`, `ospf-scope`) read their "established"/"full"
counts back **from the rules**, so a listing and a verdict can never disagree about what healthy
means.

## The verdict vocabulary

Six terms mirroring configuration's six one-for-one, mapped onto existing Experience-Language
chips — no new chip, no blended vocabulary (state never says Compliant; configuration never says
Healthy-as-a-state-verdict):

| State verdict | Defined as | Chip |
|---|---|---|
| **Healthy** | ≥1 judged; every applicable observation in its expected state | Healthy |
| **Degraded** | some observations in expected state, some not (decided at the *observation* level: "27 of 28 Established" is Degraded even when every evaluation failed) | Attention required · Warning (medium/low) |
| **Failed** | no observation in its expected state | Attention required |
| **Not enough evidence** | nothing judged — absent, undated **or stale** observations | Not enough evidence |
| **Not applicable** | no device in scope runs the subject | Informational |
| **Unsupported** | no shape, or no rules — cause always named | Informational |

**Reserved, never emitted: `Unstable`.** It means "state changed repeatedly across observations" —
a determination that requires a state history Atlas does not retain. The word is defined so it can
never be redefined weaker, and a test asserts no projection produces it.

## Routing

No OIR change, no new objective, no dispatch-table key. One selection rung (1b): a
judgement-phrased assessment of a state-capable subject — *"Is BGP healthy?"*, *"Are all BGP
sessions established?"* — selects the generic state template. Endpoints keep the richer peering
investigation; *"show me BGP for X"* extracts `objective=locate` and keeps its listing; the
estate-wide contract (*"Is the network healthy?"*) is untouched.

## Honest refusals

- **Temporal questions** — *flapping, unstable, stable, intermittent* — are refused before any
  template runs, quoting the operator's word: one observation per discovery cannot distinguish a
  link that flapped from one that was down when observed. The refusal names what Atlas *can*
  assess.
- **Unsupported subjects** name the missing half — *no canonical observation shape* (write a
  parser) vs *no state rules* (write data) — and list the live capabilities. A subject-plus-site
  question still earns its site investigation instead of a refusal.

## Configuration and state never blend

Two aspects of one subject: `capability(subject, aspect=ASPECT_STATE)` vs the PR-172 default.
Separate rules, separate verdicts, separate vocabularies, a shared honest tail (three phrases, not
six). The state path never reads `config_memory` — a configured HSRP priority says nothing about
which router is Active — and a test greps that the import never appears.

## Adding a protocol's state validation

1. A canonical observation shape (one frozen dataclass) — the irreducible per-protocol cost.
2. A parser in the driver that already collects the text.
3. `state_kind` (+ `state_title`) on the subject descriptor.
4. State rules, as data.

Steps 3–4 are data. HSRP/STP/LAG text is already collected on NX-OS and IOS-XE; each is one shape
and one parser away.

## What Atlas still cannot do (stated, not implied)

Atlas assesses state **as of the last discovery**. It does not poll, it does not retain state
history, and therefore it cannot detect flapping, instability, or convergence over time — those
wait for the state history store (the observation identity keys it will join on ship in this PR).
HSRP/VRRP, STP, MLAG, EVPN and VPN state are honest refusals until their shapes land.
