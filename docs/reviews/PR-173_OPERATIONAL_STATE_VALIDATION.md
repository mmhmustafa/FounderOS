# PR-173 — Operational State Validation Framework — Architecture Review

**Role:** Chief Software Architect. **Status:** review only — nothing implemented, nothing committed.
**Base:** `4dc3e67` (PR-170 + PR-171 + PR-172 committed and pushed).

---

## Verdict first

**Atlas already collects, normalises and carries operational state for BGP, OSPF and interfaces.
What it does not do is *judge* it — and the judging rules it does have are hardcoded Python.**

Four findings decide this PR:

1. **The state pipeline exists end to end for the flagship protocols.** `BgpSessionObservation` and
   `OspfAdjacencyObservation` are canonical, versioned, vendor-neutral shapes carrying `state`,
   `source_command` and `observed_at`; seven drivers already normalise into them; the Enterprise
   Graph already carries them; `routing_evidence_for(graph, device_id)` is already the projection.
   Five of the brief's eight proposed constructs therefore already exist.

2. **The health rules are the thing that is missing — and today they are code.**
   `_ESTABLISHED` / `_session_is_established()` for BGP, and a bare `state.startswith("full")` for
   OSPF, sit inline in `investigation/engines.py`. That is exactly the *Subject-specific Validators*
   antipattern PR-172 rejected for configuration, already present for state. PR-173's real job is to
   turn those two expressions into **data** before there are twenty of them.

3. **Half the brief's example questions are not answerable, and would be lies if attempted.**
   "Are interfaces flapping?", "Are OSPF adjacencies unstable?", "Are VRRP elections stable?" all
   require a **state time series Atlas does not retain**. Configuration has snapshots
   (`configuration_snapshots`); state does not — `routing_evidence` is graph metadata regenerated
   per discovery, with no history. Instability must be an honest refusal in this PR, not a guess.

4. **State is perishable in a way configuration is not — and this is the single most important
   difference.** A three-day-old `running-config` is still legitimate evidence of how a device is
   configured. A three-day-old `Established` is **not** evidence that BGP is up now. Atlas's
   freshness model is currently binary and estate-wide (`overall_freshness` = every contribution
   fresh) while the per-observation `observed_at` it already records goes unused. Without a
   freshness gate, state validation is the most confident-sounding wrong answer Atlas could give.

The brief asks for reuse. The correct reuse is not the Policy Engine's text matcher — structured
observations forced through a regex operator would be a square peg. It is the layer beneath:
**CORTEX's `Rule` protocol**, of which `PolicyRule` is merely one adapter. A second adapter buys
the same confidence calculus, result schema, provenance, dispositions and PR-172's `applicable`
flag, for free.

---

## 1. Architecture Review

### 1.1 What already exists

| Brief proposes | Reality | Where |
|---|---|---|
| **State Collectors** | Exist: `CommandSpec(capability, commands, tier, limitation)` per driver, with five honest statuses and three maturity levels. NX-OS already collects `BGP`, `OSPF`, `FIRST_HOP_REDUNDANCY`, `STP`, `LAG`, `VLAN`, `VRF`, `MAC_TABLE`; Junos and EOS collect BGP/OSPF/LAG/VLAN/VRF | `platforms/capabilities.py`, `platforms/drivers/*` |
| **Vendor-specific State Adapters** | Exist, and are the *right* design: each driver parses its own CLI into one canonical shape. Seven drivers already produce BGP summaries | `platforms/drivers/{frr,ios_xe,nxos,eos,junos,fortios}.py` |
| **Operational State Provider** | Exists as a graph projection: `routing_evidence_for(graph, device_id)` → `{bgp_sessions, ospf_adjacencies}`; interface status/protocol_status on graph interfaces | `investigation/engines.py:31` |
| **State Capability Registry** | Exists as PR-172's derived registry — needs **one new axis**, not a second registry | `investigation/validation.py` |
| **Subject-specific State Providers** | **Reject** — the PR-172 lesson, verbatim: code per subject is what these frameworks exist to delete | — |

The canonical shape is already better than most of what the brief asks for:

```python
@dataclass(frozen=True)
class BgpSessionObservation:
    peer_address: str; remote_as: str | None; local_as: str | None
    state: str; vrf: str = "default"; address_family: str = "ipv4-unicast"
    router_id: str | None = None; accepted_prefixes: int | None = None
    source_command: str = ""        # provenance: which command proved it
    observed_at: str | None = None  # provenance: WHEN — currently unused
```

`routing_metadata()` stamps `schema_version: "1.0.0"`. Vendor neutrality, provenance and versioning
are already solved. **The state framework is two-thirds built.**

### 1.2 What is genuinely missing

| Missing | Size | Note |
|---|---|---|
| **Health rules as data** | Small | Two inline expressions become descriptors; one new CORTEX rule adapter |
| **A freshness gate on state answers** | Small | `observed_at` already recorded; nothing consumes it |
| **Canonical shapes for the other protocols** | Medium, **per protocol** | HSRP/STP/LAG output is *collected as raw text* but never parsed into observations |
| **A state time series** | Large — **out of scope** | No history ⇒ no "flapping", no "unstable" |

### 1.3 The two-class split in the brief's own examples

| Question | Class | Answerable in PR-173? |
|---|---|---|
| Are all BGP sessions established? | point-in-time | ✅ today's observations |
| Are any BGP peers down? | point-in-time | ✅ |
| Is BGP healthy? | point-in-time | ✅ |
| Are OSPF neighbours healthy? | point-in-time | ✅ |
| Are VPN tunnels up? | point-in-time | ❌ no collection, no shape |
| Are HSRP groups healthy? | point-in-time | ❌ collected as text, no shape |
| Is STP converged? | point-in-time | ❌ collected as text, no shape |
| Are MLAG peers synchronized? | point-in-time | ❌ |
| Are EVPN sessions healthy? | point-in-time | ❌ |
| **Are interfaces flapping?** | **temporal** | ❌ **needs history** |
| **Are OSPF adjacencies unstable?** | **temporal** | ❌ **needs history** |
| **Are VRRP elections stable?** | **temporal** | ❌ **needs history** |

Three of twelve ship immediately; three more are one canonical shape each; **three are blocked on a
capability Atlas does not have and must not pretend to have.** Naming this in the PR is what stops
the framework advertising instability detection it cannot perform.

### 1.4 A confusion already latent in the codebase

`config_memory/extract.py` defines `HsrpGroupFact` — parsed from `standby 1 priority 110`, i.e. the
**configured** HSRP intent. That is not operational state; it says nothing about which router is
Active right now. The brief's warning ("Atlas must never confuse the two") is not hypothetical: the
two live in the same repository under similar names today. **The state framework must never read
`config_memory` facts**, and the naming must keep them apart (`HsrpGroupFact` = configuration;
`HsrpGroupObservation` = state, when it lands).

---

## 2. Operational State Framework

### 2.1 The model

```
        Subject + Objective                  (PR-171 — unchanged)
                    │
                    ▼
        State Capability                     DISCOVERED, as in PR-172:
        = subject has a canonical            no observation shape and no
          observation shape                  rule ⇒ no capability
          AND state rules exist
                    │
                    ▼
        Scope resolution                     (PR-171 — unchanged)
                    │
                    ▼
        Observation retrieval  ──────────►   none ⇒ NOT ENOUGH EVIDENCE
        (per device, from the graph)
                    │
                    ▼
        FRESHNESS GATE  ─────────────────►   stale ⇒ NOT ENOUGH EVIDENCE,
        (observed_at vs the answer's           naming the age
         staleness horizon)                    ** the state-specific step **
                    │
                    ▼
        State rules over structured          a SECOND CORTEX Rule adapter,
        observations                         not the text matcher
                    │
                    ▼
        CORTEX ReasoningEngine               UNCHANGED
                    │
                    ▼
        Determinations                       pass / fail / warning / unknown
        + applicable                         + applicable (PR-172 R1, free)
                    │
                    ▼
        Verdict                              a PROJECTION — computed, never stored
```

One step is new relative to PR-172, and it is the one that makes state honest: **the freshness
gate**. Everything else is the configuration pipeline with a different rule adapter.

### 2.2 Decisions on the eight proposed constructs

| Construct | Decision | Reasoning |
|---|---|---|
| **Operational State Provider** | **BUILD — thin** | Exists as a graph projection; promote it to a named `StateProvider` returning typed observations plus their `observed_at`. ~60 lines. Not a collector. |
| **State Descriptor** | **BUILD — as canonical observation shapes** | The one genuinely per-protocol cost. BGP and OSPF already have theirs; each new protocol is one frozen dataclass plus one parser in the driver that already collects the text. |
| **State Capability Registry** | **REUSE PR-172's, plus one axis** | `capability(subject, aspect)` where `aspect ∈ {configuration, state}`. A second registry would fork the honesty guarantee that took PR-172 to establish. |
| **State Collectors** | **REJECT — exist** | `CommandSpec` per driver, tiered, with limitations and maturity. |
| **Subject-specific State Providers** | **REJECT — actively harmful** | Precisely what `_session_is_established` already is. Delete the pattern; do not institutionalise it. |
| **Vendor-specific State Adapters** | **REJECT — exist** | The drivers. Vendor CLI differences are absorbed at parse time into one canonical shape — already the design. |
| **Time-aware State Evaluation** | **SPLIT — accept half** | Point-in-time evaluation: yes, now. Temporal evaluation (flapping, instability): **defer** — it needs a state history store, and without one every "unstable" verdict is invention. |
| **State Freshness Model** | **BUILD — the most important item** | Per-answer, derived from `observed_at` + contribution timestamps Atlas already records. Not a subsystem: one function and one gate. |

**Net: three new things (a thin provider, observation shapes per protocol, a freshness gate), one
new axis on an existing registry, and one new CORTEX rule adapter.**

### 2.3 Why a second CORTEX adapter, not the Policy Engine

The Policy Engine's operators (`any_present`, `none_present`, `conditional_present`, …) are pure
functions **of text**. Operational state is a list of structured records. Serialising observations
back to text so a regex can read them would be an architectural joke, and it would lose the typed
fields (`state`, `accepted_prefixes`, `vrf`) that make state rules meaningful.

But the Policy Engine is not the reuse boundary — **CORTEX is**. The `Rule` protocol is
evidence-agnostic:

```python
def applies(self, evidence) -> bool: ...
def evaluate(self, evidence, gaps) -> RuleOutcome: ...
```

`PolicyRule` is one adapter over `running-config` text. A `StateRule` is a second adapter over
structured observations. Both feed the identical engine, so state validation inherits — without a
line of new machinery — the confidence calculus, `ReasoningResult`, provenance, the four
dispositions, the no-evidence-⇒-unknown guarantee, and **PR-172's `applicable` flag** (a device
with no BGP configured is *not applicable* to BGP state rules, exactly as it is to BGP config
rules).

That is deep reuse. Forcing state through `PolicyCheck` would be shallow reuse that costs more.

---

## 3. State Capability Model

```python
# investigation/validation.py — EXTENDED, not replaced

ASPECT_CONFIGURATION = "configuration"
ASPECT_STATE = "state"

@dataclass(frozen=True)
class ValidationCapability:
    subject: str
    aspect: str = ASPECT_CONFIGURATION   # NEW — the second axis
    label: str = ""
    title: str = ""                      # "BGP sessions" for state
    rules: tuple[str, ...] = ()
    pack: str = ""
    evidence_kinds: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

def capability(subject, aspect=ASPECT_CONFIGURATION, pack=None): ...
def capabilities(aspect=None, pack=None): ...
```

A **state** capability is discovered when both hold:

1. the subject declares a canonical observation kind (`SubjectDescriptor.state_kind`), **and**
2. at least one state rule targets that kind.

Both halves are data, so — as in PR-172 — capability cannot lie. A subject with a shape but no rules
is not validatable; a subject with rules but no shape is not validatable; and the refusal names
which half is missing, because those lead to different actions (write a rule vs. write a parser).

**Adding a protocol's state validation:**

| Step | Where | Cost |
|---|---|---|
| 1. Canonical observation shape | `routing/evidence.py` (or a peer module) | one frozen dataclass |
| 2. Parser in the driver that already collects the text | `platforms/drivers/*.py` | one function per vendor |
| 3. `state_kind` on the subject descriptor | `investigation/subjects.py` | one field |
| 4. State rules | a state rule pack | data |

Steps 3–4 are data. Steps 1–2 are the irreducible per-protocol cost, and they are irreducible for a
good reason: *someone has to know that `show hsrp brief` column 4 is the group state.* No registry
design removes that.

---

## 4. State Collection Strategy

**Do not build a collector.** The drivers already collect; the framework consumes what discovery
stored. Three consequences, all deliberate:

- **State is as fresh as the last discovery.** Atlas does not poll. Every state answer therefore
  carries an age, and the freshness gate (§2.1) decides whether that age still supports a verdict.
  This is honest and it is cheap; live polling is a different product decision, not a framework one.
- **Collection tiers already govern cost.** `STP` is `TIER_DEEP` on NX-OS; a fast discovery skips it
  and the capability reports `not-attempted` **by name**. State validation must surface that as
  *Unsupported — not collected in this discovery tier*, never as healthy.
- **Missing collection is a capability answer, not an error.** A driver with no `FIRST_HOP_REDUNDANCY`
  spec means HSRP state is unsupported *on that platform*, and the answer should say so per-platform
  rather than estate-wide.

### The freshness model — concretely

```python
def state_freshness(observations, *, now, horizon_minutes) -> Freshness:
    """FRESH | AGEING | STALE, from observed_at — never a guess.

    An observation with no observed_at is UNDATED and cannot support a
    verdict: Atlas does not assume that unstamped means recent.
    """
```

Recommended default horizon: **60 minutes** for a verdict, with 60–240 minutes reported as
*ageing* (verdict allowed, age stated in the answer), and beyond that **stale ⇒ not enough
evidence**. The horizon belongs in workspace preferences, not in code, because a lab and a change-
frozen production estate reasonably differ. Undated observations are treated as stale.

The wording matters as much as the gate: *"BGP was healthy as of 09:12 (3 hours ago); Atlas has not
observed it since"* is a true sentence. *"BGP is healthy"* over the same evidence is not.

---

## 5. Relationship with Configuration Validation

**Two aspects of one subject, never merged, never conflated, never averaged.**

```
                        BGP
                         │
        ┌────────────────┴────────────────┐
        │                                 │
  CONFIGURATION                       STATE
  aspect=configuration                aspect=state
        │                                 │
  policy pack rules                 state rules
  over running-config               over observations
        │                                 │
  "Compliant"                       "Degraded"
  (27 devices judged)               (27 Established, 1 Idle)
```

Design rules, each enforceable by a test:

1. **Separate capabilities, separate rules, separate verdicts.** No combined "BGP score". A
   compliant configuration with a dead session is *Compliant* **and** *Degraded* — both true, both
   said.
2. **Separate vocabularies.** Configuration says Compliant / Non-compliant. State says Healthy /
   Degraded / Failed. An operator must never have to ask which axis a word refers to.
3. **A shared honest tail.** *Not enough evidence*, *Not applicable* and *Unsupported* mean the same
   thing on both axes and use the same words — three phrases, not six.
4. **They may appear together, adjacently, never blended.** When both capabilities exist, the answer
   may show both lines; the verdict chip reflects the aspect that was asked about.
5. **State never reads configuration facts, and vice versa.** `config_memory`'s `HsrpGroupFact` is
   not state evidence (§1.4).

**Routing (the elegant part): no OIR change is needed, and no new objective.** "Is BGP healthy?"
already routes to `bgp-investigation` (`engine=health`, `objective=assess`) and already runs
`bgp_for_devices`, which *lists* sessions. PR-173 upgrades that listing into a judged verdict by
adding **one selection rung** in `templates.py`:

```
rung 1  subject + objective=validate + config capability  -> config validation   (PR-172)
rung 1b subject + objective=assess   + STATE capability   -> state validation    (PR-173, NEW)
rungs 2-6  the PR-167 ladder, unchanged
```

The dispatch table is untouched — critically, **no `(engine, "assess")` key is added**, which
PR-171's test explicitly forbids. The estate-wide contract is preserved by the same subject gate
PR-172 uses: "Is the network healthy?" names no subject and still reaches the enterprise summary.

---

## 6. Sequence

```
Operator      Extraction   Capability    State        Freshness    CORTEX      Advisor
   │              │        Registry      Provider      Gate        Engine        │
   │─ "Is BGP     │           │             │            │           │           │
   │   healthy?" ─┤           │             │            │           │           │
   │              │─ subject=bgp, objective=assess, scope=enterprise │           │
   │              │           │             │            │           │           │
   │              │  capability("bgp", aspect="state")   │           │           │
   │              │   = state_kind ∩ state rules         │           │           │
   │              │           │             │            │           │           │
   │              │   ┌───────┴── none? ────────────────────────────────────────►│
   │              │   │  REFUSE: "Atlas cannot assess BGP state — no observation │
   │              │   │  shape / no rules." Never a health claim.                │
   │              │           │             │            │           │           │
   │              │      scope → devices (Enterprise Graph)          │           │
   │              │           │─ observations + observed_at ─►│      │           │
   │              │           │             │       age > horizon?   │           │
   │              │           │             │   ┌────┴── STALE ─────────────────►│
   │              │           │             │   │  "not enough evidence —        │
   │              │           │             │   │   last observed 3 days ago"    │
   │              │           │             │            │           │           │
   │              │           │        StateRule.evaluate(observations) ─►│      │
   │              │           │             │            │   pass/fail/warning/  │
   │              │           │             │            │   unknown + applicable│
   │              │           │◄─ determinations ────────────────────┤           │
   │              │      aggregate over JUDGED devices only          │           │
   │              │      → state verdict projection ─────────────────────────────►│
   │◄──────────── verdict · findings · next actions · supporting detail ──────────│
   │   "BGP sessions: Degraded — 27 of 28 Established; 1 Idle (core-2 → 10.0.0.9).
   │    Observed 6 minutes ago."
```

---

## 7. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | **Stale state presented as current.** The defining failure mode of this PR: a confident "Healthy" over days-old evidence. | **Critical** | The freshness gate is **mandatory**, not advisory. Every state answer states its observation age. Undated observations are stale, never assumed recent. |
| **R2** | **Instability claimed without history.** "Flapping"/"unstable" invented from a single sample. | **Critical** | No temporal verdict ships in PR-173. `Unstable` is reserved vocabulary and those questions are refused honestly, naming the missing capability. |
| **R3** | **Configuration and state conflated** — a combined score, or config HSRP facts read as state. | **High** | Separate aspects, separate rules, separate vocabularies; a test asserts no answer mixes the two word-sets, and that the state path never imports `config_memory`. |
| **R4** | **`not-attempted` read as healthy.** A fast-tier discovery skipped `show spanning-tree`; absence of a problem is not evidence of health. | **High** | Absence of observations ⇒ *not enough evidence*, never Healthy — the PR-172 R1 discipline applied to state. Tier and per-platform capability status are surfaced. |
| **R5** | **Per-subject state code multiplies** — one hand-written health function per protocol. | **High** | Rules are data over a closed operator vocabulary; the two existing inline predicates are **deleted**, not joined. |
| **R6** | **Vendor state-string drift** — `Established` vs `ESTABLISHED` vs `Estab`, `FULL/DR` vs `Full`. | **Medium** | Normalisation belongs in the driver's parser (already the pattern); rules compare canonical values. A test pins the vocabulary each driver may emit. |
| **R7** | **Observation identity across discoveries** — the same session must be recognisable run to run, or future history work has no key. | **Medium** | Fix the identity now (device + vrf + address-family + peer), even though history lands later; retrofitting keys is far more expensive. |
| **R8** | **Upgrading `bgp-scope`/`ospf-scope` changes existing answers** from listings to verdicts. | **Medium** | Deliberate and desirable, but it must be test-visible: PR-167/171 tests that pin those templates get reviewed edits, exactly as PR-172 handled its three. |
| **R9** | **Scale.** State rules over every session on 85 devices, per answer. | **Low** | Observations are already in memory on the graph; no I/O. Measure, do not pre-optimise. |
| **R10** | **PRISM disclosure.** Peer addresses and router-ids in state findings are identity-adjacent. | **Medium** | Route state findings through the existing PRISM semantic redaction and RBAC path — no new disclosure surface, no bypass. |

---

## 8. Future Extensibility

In dependency order; none blocked by this framework:

1. **A state history store** (the real two-year item). Append-only, keyed by observation identity
   (R7), retention-bounded. Unlocks *flapping*, *unstable*, *converged*, and trend answers — the
   entire Class B of §1.3.
2. **Canonical shapes for HSRP/VRRP, STP, LAG/MLAG** — the text is already collected on NX-OS and
   IOS-XE; each is a dataclass plus a parser.
3. **VPN / EVPN / VXLAN** — needs collection *and* shapes; a driver-side project first.
4. **Cross-device state rules** — "the HSRP pair agrees", "MLAG peers synchronised", "STP root is
   the intended device". Same shape problem PR-172 deferred for configuration; solve once, for both.
5. **State rule packs as data files** — mirroring policy packs, so customers can express their own
   "healthy" (e.g. "a peer with zero accepted prefixes is degraded even if Established").
6. **Live/on-demand refresh** — a targeted re-collect when the freshness gate would otherwise
   refuse. A product decision with real cost, deliberately not smuggled into a framework PR.

---

## 9. Recommended PR Scope

**PR-173 — Operational State Validation Framework.** Deliberately narrow.

**In scope**
1. `aspect` axis on the PR-172 capability registry (`configuration` | `state`), with derived state
   capability discovery and honest, cause-naming refusals.
2. `StateRule` — a second CORTEX `Rule` adapter over structured observations, with a small closed
   operator vocabulary (`all_in_states`, `none_in_states`, `min_count`, `ratio_at_least`).
3. A thin `StateProvider` over the existing graph projection, returning typed observations plus
   `observed_at`.
4. **The freshness gate** and its wording, with the horizon in workspace preferences.
5. State rules for **BGP sessions, OSPF adjacencies and interface operational status** — replacing
   the two inline predicates, which are deleted.
6. One new selection rung (`subject + assess + state capability`). No OIR change, no new objective,
   no dispatch-table change.
7. The state verdict vocabulary (§10) as a projection onto existing Experience-Language chips.
8. Observation identity keys (R7).
9. Tests + `docs/ATLAS_STATE_VALIDATION.md`.

**Explicitly out of scope — and each must be *said*, not silently omitted**
- Any temporal verdict: flapping, unstable, converged, "elections stable" (R2).
- The state history store.
- HSRP/VRRP, STP, MLAG, EVPN, VPN state — refused honestly, per platform, until their shapes land.
- Live polling or on-demand refresh.
- Any change to configuration validation, PRISM, the collectors, or the Policy Engine.

**Honest note on what PR-173 alone delivers:** three of the brief's twelve questions, answered
well — BGP session health, OSPF adjacency health, interface operational status — plus a framework
where the fourth through ninth cost one dataclass and one parser each. It does **not** deliver
instability detection, and the answer to "are interfaces flapping?" will remain a refusal naming the
missing history until PR-174. That refusal is the feature.

---

## 10. Success Criteria

1. **"Is BGP healthy?" returns a judged verdict**, not a listing — with per-session evidence and the
   observation age stated.
2. **Stale evidence never yields a health verdict.** Pinned by a test that ages observations past
   the horizon and asserts *not enough evidence*, with the age named.
3. **A device that does not run the protocol is *not applicable*, never healthy** — PR-172's R1
   discipline holding on the state axis.
4. **The two inline predicates are gone**; grep for `_session_is_established` and
   `startswith("full")` returns nothing.
5. **Adding a protocol's state validation touches only a shape, a parser and rules** — pinned by a
   synthetic-protocol test.
6. **Configuration and state never blend**: no combined score, no shared verdict word, no
   `config_memory` import in the state path.
7. **Temporal questions refuse honestly**, naming the missing capability rather than guessing.
8. **Every state verdict names its observation age and source command.**
9. **No new Experience-Language chip**; state verdicts map onto the existing five.
10. **No OIR change and no dispatch-table change** — verified by the frozen registry's version hash
    and PR-171's objective-table test passing unmodified.
11. **Full suite green** (baseline: 2,906 passed / 2 skipped / 886 subtests).

### The verdict vocabulary

Of the eight candidates: **drop "Partially Healthy"** (a synonym of Degraded — the PR-172 lesson
that two words for one state is how vocabularies rot), **drop "Unknown"** as a headline (keep it as
the per-item disposition it already is), **merge "Insufficient Evidence" into "Not enough
evidence"** (the Experience Language's existing phrase, shared with configuration), and **reserve
"Unstable"** until history exists — defining it now and refusing to emit it is better than
redefining it later.

Six terms, mirroring configuration's six one-for-one:

| State verdict | Defined as | Chip | Configuration analogue |
|---|---|---|---|
| **Healthy** | ≥1 judged; every applicable observation in its expected state | Healthy | Compliant |
| **Degraded** | some in expected state, some not | Warning · Attention required if a critical rule fired | Non-compliant |
| **Failed** | no observation is in its expected state | Attention required | Non-compliant (grave) |
| **Not enough evidence** | nothing judged: absent, undated **or stale** observations | Not enough evidence | same |
| **Not applicable** | the subject is not configured on any device in scope | Informational | same |
| **Unsupported** | no shape, no rules, or the platform cannot collect it — cause always named | Informational | same |

Reserved, not emitted by PR-173: **Unstable** (state changed repeatedly across observations) —
its meaning is fixed here so the word cannot be reused for something weaker later.

---

## 11. APPROVED IMPLEMENTATION PLAN

For Claude Fable. Order matters: the shapes and the gate precede any rule, so nothing can judge
before it can date its evidence.

**Step 1 — Observation identity and the state provider.**
Add stable identity keys to `BgpSessionObservation` / `OspfAdjacencyObservation`
(device + vrf + address-family + peer / neighbour-router-id), and a thin
`investigation/state.py::observations_for(graph, device_id, kind)` returning typed observations with
their `observed_at`. Pure, no I/O beyond the graph. Do not change the collectors.

**Step 2 — The freshness gate (before any rule).**
`state_freshness(observations, *, now, horizon_minutes) -> FRESH | AGEING | STALE`, with undated
treated as stale. Horizon read from workspace preferences with a 60-minute default. Regression test:
aged observations produce *not enough evidence* with the age named, never a verdict.

**Step 3 — The `aspect` axis on the capability registry.**
Extend `ValidationCapability` and `capability()/capabilities()` with `aspect`, defaulted to
`configuration` so every PR-172 caller is unchanged. State capability = `state_kind` on the
descriptor ∩ state rules installed. `unrealised()` gains the aspect. **Acceptance gate: every
PR-172 test passes unmodified.** If any must change, stop and report the conflict.

**Step 4 — `StateRule`, the second CORTEX adapter.**
Implements the `Rule` protocol over structured observations, with a closed operator vocabulary:
`all_in_states`, `none_in_states`, `min_count`, `ratio_at_least`. Sets `applicable=False` when the
subject is absent from the device (PR-172 R1 semantics on the state axis). Reuses the engine's
calculus, result schema and provenance — no new scoring, no new result type.

**Step 5 — State rules for BGP, OSPF and interfaces, as data.**
Delete `_session_is_established` and the inline `startswith("full")`; their vocabulary moves into
rule data. Interface rule judges operational status from the graph's existing status fields.

**Step 6 — The state investigation template and its selection rung.**
One generic subject-parameterised template (mirroring PR-172's builder) and rung 1b in `select()`.
No OIR change, no new objective, no dispatch-table key. `bgp-scope`/`ospf-scope` upgrade from
listing to verdict; their pinned tests get reviewed edits (R8) — report each, do not edit silently.

**Step 7 — The verdict projection and its wording.**
Six state terms as a pure function of the aggregate, mapped onto existing chips. Every answer states
the observation age and the source command. "Unstable" is defined in code as reserved and asserted
unreachable.

**Step 8 — Honest refusals.**
Temporal questions ("flapping", "unstable", "stable elections") are detected and refused with the
missing capability named. Unsupported subjects name *which* half is missing — shape or rules — and
report per-platform collection status where it differs.

**Step 9 — Tests.** `tests/test_state_validation.py`, covering all eleven success criteria,
including the two headline tests: the staleness refusal, and the synthetic-protocol genericity test.

**Step 10 — Documentation.** `docs/ATLAS_STATE_VALIDATION.md`: the model, the freshness contract,
the two vocabularies and why they stay apart, how to add a protocol (shape + parser + rules), and —
stated plainly — that Atlas assesses state *as of the last discovery* and cannot yet detect
instability.

**Non-goals (do not do these):**
- Do not add a collector, poll a device, or change any driver's command set.
- Do not build the history store, or emit any temporal verdict.
- Do not touch PRISM, the Enterprise Graph's construction, the Policy Engine, or configuration
  validation.
- Do not add a second capability registry, severity scale, or verdict vocabulary beyond the six.
- Do not add an `(engine, "assess")` dispatch key.
- Do not commit.

**Handover must state:** the freshness horizon chosen and why; every subject with state capability
and every one without, with the reason (shape missing vs rules missing vs not collected); measured
latency for a state answer; which pinned tests were edited under R8 and why; and what remains
impossible until the state history store lands.
