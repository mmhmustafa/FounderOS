# PR-172 — Operational Validation Framework — Architecture Review

**Role:** Chief Software Architect. **Status:** review only — nothing implemented, nothing committed.
**Base:** `ce42559` + uncommitted PR-170 and PR-171.

---

## Verdict first

**Atlas does not need a validation framework. It already has one — and it has a correctness defect
that will surface the moment the framework is opened past OSPF.**

Three findings decide this PR:

1. **Six of the nine constructs the brief proposes already exist** in the policy engine, the pack
   registry and the platform layer. Building them again would fork governance for no capability.
   Two are genuinely missing, and both are small.

2. **A device that does not run a protocol is currently counted as PASSING that protocol's
   policies.** Proven by execution (§1.3). OSPF hides this because every device on the estate runs
   OSPF. BGP, HSRP, VXLAN, MLAG and wireless are *minority* technologies — for them this defect is
   not an edge case, it is the dominant answer shape, and it inverts severity: a fleet where the
   only real BGP speaker is broken reports as ~99% compliant.

3. **The ceiling on "validate any technology" is not registration. It is the rule language and the
   evidence port.** The matcher has five presence-only operators over whole-file text, and the
   policy engine can see exactly **two** evidence kinds — `running-config` and `access-transport`.
   No amount of registry design lets that judge "every BGP neighbour is Established" or "the HSRP
   pair agrees on priority".

The brief says *"challenge assumptions"*. The assumption worth challenging is that the missing
piece is registration machinery. It is not. Registration is roughly 200 lines. The honest answer to
*"can Atlas validate ACLs, QoS, EVPN, wireless?"* is **not yet, and the framework is not what
stands in the way** — and Atlas should say so in exactly those terms rather than register
capabilities it cannot deliver.

---

## 1. Architecture Review

### 1.1 What PR-171 actually left behind

The validation path already exists end to end and is already subject-generic. Reading it closely:

| Component | Subject-specific? | Evidence |
|---|---|---|
| `investigation/engines.py::policy_validation` | **No** | Reads `descriptor.policy_tags`, `label_for(subject)`. Zero OSPF. |
| `investigation/engines.py::enterprise_scope` | **No** | Pure graph walk. |
| `investigation/engines.py::aggregate_policy_report` | **No** | Pure; parameterised by `tags`. |
| `_locate(False)` | **No** | PR-167, shared by six templates. |
| `templates.py::ospf-configuration` | **Prose only** | `key`, `title`, `objective`, `completion`, one step label. |
| `VALIDATION_TEMPLATES` | Yes — one line | `{"ospf": "ospf-configuration"}` |
| `routing/intents.py::ospf-configuration-validation` | Yes — one intent | OSPF examples + fallback keywords |

So adding BGP today is four edits: a dict entry, a near-identical template block, an intent, and
rules. **Three of the four are pure boilerplate that differ only by a noun.** That is the
duplication PR-172 must delete — and it is the *whole* of the "expand OSPF into BGP" work the brief
rightly forbids doing by hand.

The sharpest evidence that the seam is already right: `subjects.py` **already declares
`policy_tags=("bgp",)` for BGP**, and the starter pack **already ships `STD-BGPRID-001` tagged
`bgp`**. The rules and the linkage exist. Only the boilerplate is missing. **Done correctly, BGP
validation ships with zero new validation data on the day the framework lands** — that is the
proof-of-genericity, and it belongs in the success criteria.

### 1.2 What already exists that the brief proposes to build

| Brief proposes | Reality | Where |
|---|---|---|
| Validation **Rule Packs** | Exists: `PolicyPack(pack_id, name, description, version, author, policies)`, an `INSTALLED_PACKS` registry with `get_pack`/`list_packs`/`default_pack`, unique-id validation | `policy/packs/__init__.py`, `policy/models.py` |
| **Versioned** validation packs | Exists: `pack_id@version` is already threaded into every reasoning result as `rule_set_version` | `policy/engine.py:_build_engine` |
| **Rule Metadata** | Exists, richer than proposed: `category`, `severity`, `tags`, `intent`, `version`, `author`, `evidence_required`, `expected_state`, `recommendation`, `remediation`, `base_confidence`, `applicability` | `policy/models.py::Policy` |
| **Severity Classification** | Exists twice over: `info/low/medium/high/critical` **and** an orthogonal obligation axis `required/recommended/informational` | `reasoning/result.py`, `policy/applicability.py` |
| **Vendor-specific Overrides** | Exists, and is better than an override mechanism: `PolicyApplicability` targets platforms, roles, sites, site types, tags, profiles, networks, environments, named devices — ANDed across dimensions, ORed within, wildcards, explicit exclusions win, and **unknown attributes are never guessed** | `policy/applicability.py` |
| **Capability Discovery** | Exists *at the collection layer*: 23 named capabilities (`BGP`, `OSPF`, `VRF`, `VLAN`, `LAG`, `STP`, `FIRST_HOP_REDUNDANCY`, …), per-driver `CommandSpec`s, five honest statuses (`supported`, `supported-with-limitations`, `unsupported`, `not-attempted`, `failed`) and three maturity levels | `platforms/capabilities.py`, `platforms/registry.py`, 15 drivers |

**Six of nine already exist.** Re-implementing any of them under a `validation_` prefix would give
Atlas two pack registries, two severity scales and two vendor-targeting models to keep in step. That
is the single largest architectural risk in this PR, and the recommendation is simply: **don't**.

### 1.3 The defect: not-applicable is counted as compliant

`policy/rule.py:159` returns `conclusion_kind=CONCLUSION_PASS` for the not-applicable outcome.
`STATUS_PASSED = CONCLUSION_PASS`, so `PolicyReport.passed` — and therefore `score`, and therefore
PR-171's `aggregate_policy_report` — count a device the policy explicitly **did not apply to** as a
device that passed it.

Proven by running the real engine over three synthetic devices (one BGP speaker with a router-id,
one BGP speaker without, one device with no BGP at all):

```
bad     STD-BGPRID-001  status=fail   :: BGP Router ID Present: non-compliant - required but missing
bgp     STD-BGPRID-001  status=pass   :: BGP Router ID Present: compliant - the required directive is present
nobgp   STD-BGPRID-001  status=pass   :: BGP Router ID Present: not applicable - the antecedent is not present
                                                  ^^^^ the conclusion text says "not applicable"
                                                       and the status says "pass"

aggregate counts -> {"pass": 2, "fail": 1, "warning": 0, "unknown": 0}
devices_judged   -> {'bgp', 'bad', 'nobgp'}          # nobgp was NOT judged
```

The operator sentence PR-171 builds from this reads **"2 of 3 passed"**. The truth is **1 of 2
judged passed**.

Why this is severe rather than cosmetic:

- **It scales with irrelevance.** On an 85-device estate with 4 BGP speakers, 81 devices that have
  never run BGP would be counted as BGP-compliant — arithmetically, "84 of 85 passed".
- **It inverts severity.** If *every* real BGP speaker is misconfigured, that same estate reports
  ~95% compliant. The worse the true state and the rarer the protocol, the healthier Atlas sounds.
- **It is invisible today and load-bearing tomorrow.** OSPF is on every device on this estate, so
  the not-applicable branch is rarely taken. Most of the brief's target list — HSRP, VRRP, MLAG,
  EVPN, VXLAN, wireless, VPN, NAT — is deployed on a *minority* of devices by nature. PR-172 turns a
  latent bug into the normal case.

This is the same failure class PR-171 was written to eliminate — a confident answer that outruns
the evidence — living one layer below where PR-171 looked. **Fixing it is not optional scope for
this PR; opening validation without fixing it makes Atlas systematically overstate compliance.**

### 1.4 The two real ceilings

**Ceiling 1 — the rule language.** `policy/matcher.py` has five operators (`any_present`,
`all_present`, `none_present`, `conditional_present`, `interfaces_shutdown`) over whole-file text.
They express *existence*, never *universality over instances*. Compare what the brief's technology
list actually requires:

| Rule an engineer would write | Expressible today? |
|---|---|
| "OSPF is configured with a router-id" | ✅ `conditional_present` |
| "Telnet is not enabled" | ✅ `none_present` |
| "**Every** BGP neighbour has a description" | ❌ needs ∀ over `neighbor` stanzas |
| "**Every** VLAN has a name" | ❌ ∀ over VLAN blocks |
| "**Every** HSRP group has preemption" | ❌ ∀ over group blocks |
| "**Every** VRF with an RD has route-targets" | ❌ ∀ + intra-block relation |
| "**No** ACL ends without an explicit deny-log" | ❌ ∀ + positional |
| "The HSRP pair's priorities differ" | ❌ **cross-device** |
| "MLAG peers agree on the VLAN set" | ❌ **cross-device** |
| "STP root is the intended device" | ❌ **cross-device + intent data** |
| "Every configured BGP neighbour is Established" | ❌ **operational state, not config** |

`interfaces_shutdown` is the tell: the one genuinely structural rule Atlas has needed so far was
implemented as a *bespoke Python operator*, because the data language could not express it. Ship a
few more technologies and that pattern produces one hand-written operator per technology — which is
"Subject-specific Validators" arriving through the back door.

**Ceiling 2 — the evidence port.** `MemoryEvidenceProvider` emits exactly two kinds:
`running-config` and `access-transport`. Everything the platform drivers collect — BGP neighbours,
OSPF adjacencies, VLANs, ARP, MAC, LLDP, routes — reaches Enterprise Memory and the Graph but is
**invisible to the policy engine**. So "validation" today means, precisely, *"configuration text
validation"*.

That is a defensible product position — but it must be **said**, not implied. "Is BGP compliant?"
answered purely from config text, while Atlas holds session-state evidence it did not consult, is a
half-truth of exactly the kind the Experience Language forbids.

### 1.5 One more constraint worth recording

Policies match **masked** text (`providers.py:111` → `memory.view_configuration(...)`; the matcher
docstring says so explicitly). Directive *keywords* survive masking, so presence/absence rules are
unaffected — but any rule that inspects a secret's **value** (weak key, `password 7`, key length,
cipher strength) cannot be written correctly and would silently mis-judge. The framework must refuse
such rules at freeze time rather than let a pack author discover it in production.

---

## 2. Validation Framework

### 2.1 The corrected model

The brief proposes:

```
Subject → Validation Capability → Validation Rules → Policy Engine → Evidence → Verdict
```

**The stages are right. The order is wrong in one decisive place: Evidence is an input, not an
output.** Evidence appearing after the Policy Engine implies a verdict can be formed and *then*
evidenced. That is the exact inversion that produces confident answers over absent data.

Recommended:

```
        Subject  +  Objective                     (PR-171 — unchanged)
                    │
                    ▼
        Validation Capability                     DISCOVERED, never declared:
        = subject.policy_tags ∩ installed rules   a capability that selects zero
                    │                             rules does not exist
                    ▼
        Scope resolution                          (PR-171 — unchanged)
                    │
                    ▼
        Evidence availability  ───────────────►   no evidence ⇒ NOT ENOUGH EVIDENCE
        (per device, per required kind)           and the answer stops here
                    │
                    ▼
        Rule selection  (tags ∩ applicability)    per device; unknown attributes
                    │                             never guessed
                    ▼
        Policy Engine                             UNCHANGED
                    │
                    ▼
        Determinations                            pass / fail / warning / unknown
        + applicability                           + applicable / not applicable
                    │
                    ▼
        Verdict                                   a PROJECTION of the above,
                                                  computed, never stored
```

Two properties this order buys that the brief's does not:

- **Capability cannot lie.** It is a join over data that already exists, so Atlas can never
  advertise a validation for which no rule is installed.
- **Absent evidence outranks absent violations.** A device with no config snapshot is *unjudged*,
  never compliant.

### 2.2 Decisions on the nine proposed constructs

| Construct | Decision | Reasoning |
|---|---|---|
| Validation **Capability Registry** | **BUILD** — small, derived | The one genuinely missing piece. A *pure function* over the subject registry × the installed pack, not a hand-maintained list. ~40 lines. |
| Validation **Descriptor** | **BUILD as three fields on `SubjectDescriptor`** | Not a new type. `policy_tags` and `evidence_kinds` already exist; add `validation_title`, `platform_capability`, and let capability be derived. A parallel descriptor would immediately drift from the subject registry. |
| Validation **Rule Packs** | **REJECT — exists** | `policy/packs/`. Use it. |
| **Vendor-specific Overrides** | **REJECT — exists** | `PolicyApplicability.platforms`. §5. |
| **Subject-specific Validators** | **REJECT — actively harmful** | Code per subject is precisely what this PR exists to delete. The escape hatch is a new *operator* (reviewed once, reusable by every subject), never a validator per subject. |
| **Capability Discovery** | **BUILD — as a function, not a subsystem** | Must intersect three existing facts: the subject declares tags, the pack installs matching rules, and (where relevant) the platform can collect the evidence. |
| **Rule Metadata** | **REJECT — exists** | `Policy` already carries more metadata than the brief lists. |
| **Versioned Validation Packs** | **REJECT — exists** | `pack_id@version` already flows into every result. |
| **Severity Classification** | **REJECT — exists** | Two orthogonal axes already: severity and obligation intent. |

**Net: two new things and three new fields.** That is the "simplest architecture" the brief asks
for, and it is defensible line by line from the code above.

### 2.3 The one intent, not N intents

PR-171 registers `ospf-configuration-validation` as a bespoke OIR intent. Registering one per
subject would be twenty intents that differ only by a noun — the same boilerplate, moved.

**Recommendation: replace it with a single generic `configuration-validation` intent**
(`objective="validate"`), whose fallback keywords describe *validation wording*
(`compliant`, `misconfigured`, `correctly configured`, `configuration` + `fine`) and say nothing
about any subject. The subject comes from extraction, which already handles all fifteen.

This is the PR-171 model applied consistently: **the intent says what shape of answer; the subject
registry says what it is about.** Two orthogonal axes, neither multiplying the other. After it,
**adding a technology touches no intent at all.**

Risk to test explicitly: the generic intent must still outrank plain "OSPF Investigation" when
configuration wording is present, exactly as the OSPF-specific one does today. PR-171's routing
tests pin that behaviour and must stay green unmodified.

---

## 3. Capability Registry

```python
# investigation/validation.py — new, ~120 lines total

@dataclass(frozen=True)
class ValidationCapability:
    """What Atlas can validate about one subject, and on what basis.

    DISCOVERED, never declared. A capability exists exactly when the
    active pack installs at least one rule the subject's tags select.
    """
    subject: str                      # SubjectDescriptor.key
    label: str                        # "BGP"
    title: str                        # "BGP configuration"
    rules: tuple[str, ...]            # the policy_ids that will judge it
    pack: str                         # "atlas-starter@1.0" — provenance
    evidence_kinds: tuple[str, ...]   # what must be present to judge
    platforms: tuple[str, ...]        # platforms the rules target, () = all


def capabilities(pack=None) -> tuple[ValidationCapability, ...]: ...
def capability(subject: str, pack=None) -> ValidationCapability | None: ...
def unrealised(pack=None) -> tuple[tuple[str, str], ...]:
    """Subjects declaring tags that select no rule — a pack/registry
    disagreement, reported as a diagnostic, never as a crash."""
```

Design commitments:

- **Derived, so it cannot lie.** No hand-maintained list to drift from the pack.
- **Pack-scoped.** Install a CIS pack and capability grows without a code change — the brief's
  "reusable capability registration", achieved by *not* building a registration API.
- **Carries provenance.** `pack` and `rules` let every verdict name the exact rules behind it,
  which the Experience Language already requires of findings.
- **`unrealised()` is the honesty valve.** PR-171 hit this by hand (NTP/SNMP declare no tags because
  the starter pack tags those rules `time`/`observability`); this makes the mismatch visible instead
  of a silent absence, and it is the natural place for an admin page later.

Adding a technology becomes, in full:

1. Ensure the subject exists in `subjects.py` (most already do) and declares `policy_tags`.
2. Write rules in a pack, tagged accordingly.

No template, no intent, no dict entry, no code.

---

## 4. Rule Registration Model

**Rules register exactly where they do today: in a pack.** The only new thing is a governed link.

- **The link is the tag.** `SubjectDescriptor.policy_tags` ∩ `Policy.tags`. Both already exist.
- **Convention: the canonical tag is the subject key** (`ospf`, `bgp`, `vlan`). Packs may add any
  other tags freely; the subject only needs one that selects.
- **Governance is a diagnostic, not an exception.** A subject whose tags select nothing is reported
  by `unrealised()` and is simply not validatable — Atlas refuses honestly, as it does now. Raising
  at import time would make an uninstalled pack a crash.
- **A freeze-time check for the masking hazard (§1.5):** refuse to register a rule whose patterns
  target a masked secret's value. Better a loud refusal at pack-load than a quiet wrong verdict.
- **Rule → evidence stays declared** on the policy (`check.evidence`, `evidence_required`), so
  extending the evidence port later (§9) needs no rule rewrite.

---

## 5. Vendor Integration Strategy

**Vendor knowledge lives in three places, none of them OIR, the subject registry, or the
Investigator.** All three already exist.

| Layer | Where | What it knows | Adding Juniper/Nokia/Huawei means |
|---|---|---|---|
| **Collection** | `platforms/drivers/*.py` (15 today: ios, ios_xe, nxos, eos, junos, fortios, panos, aruba_cx, frr, cisco_wlc, adc, lldpd, …) | Which CLI/API commands produce which capability, fallbacks, limitations, maturity | One driver file |
| **Normalisation** | `platforms/capabilities.py` | A vendor-neutral capability vocabulary (`BGP`, `VRF`, `VLAN`, `LAG`, `STP`, `FIRST_HOP_REDUNDANCY`, …) and five honest statuses | Usually nothing |
| **Targeting** | `PolicyApplicability.platforms` | Which rules apply to which platforms | Rules, as data |

The load-bearing principle: **vendor differences in what is *correct* are expressed as separate
rules with different selectors — never as branches in code.** "BGP neighbour description" spelled
differently on IOS and Junos is two policies sharing the tag `bgp`, one selecting `Cisco IOS*`, one
selecting `Juniper*`. The engine already ANDs dimensions, ORs within them, honours wildcards, lets
exclusions win, and — critically — **refuses to guess**: a rule targeting a platform is *not
applicable* to a device whose platform Atlas has not established, rather than silently applying.

Consequences worth stating plainly:

- **OIR never learns a vendor name, and needs no change.** Neither does the subject registry. The
  brief's "avoid hardcoding vendor logic into OIR" is already satisfied — the correct action is to
  *keep* it satisfied by refusing to add a vendor axis to the validation layer.
- **A new vendor with no new rules still validates**, via universal rules, and reports
  `supported-with-limitations` / `unsupported` per capability from the driver — honestly.
- **Cloud providers fit the same shape** (an API collector is a driver; `api_collectors.py` already
  exists) — but see §8, R6: cloud "devices" are not the Enterprise Graph's device model, and that is
  a separate PR, not a footnote.

---

## 6. Validation Lifecycle

1. **Question** — operator asks. OIR routes on `(engine, objective)`; extraction yields subject,
   objective, scope. *(PR-171, unchanged)*
2. **Capability** — `capability(subject)`. **None ⇒ stop and refuse honestly**, naming what Atlas
   *can* validate. This is the only place "unsupported" is decided.
3. **Scope** — resolve to devices; enterprise scope is positive and stated. *(PR-171, unchanged)*
4. **Evidence** — per device, the required kinds are present or the device is **unjudged, with the
   reason**. Never inferred.
5. **Applicability** — per device, per rule, from `PolicyApplicability` **and** the check's own
   antecedent. Not applicable is a **third outcome**, not a pass. *(the §1.3 fix)*
6. **Judgement** — `PolicyEngine`, unchanged. Dispositions and confidence are the engine's.
7. **Aggregation** — counts by disposition, over **judged** devices only, with applicable /
   not-applicable / unjudged reported separately.
8. **Verdict** — a projection (§ below), never stored state.
9. **Presentation** — the existing Experience Language surfaces: verdict → key findings → next
   actions → supporting detail. No new UI.

### Verdict vocabulary — recommendation

Atlas already carries **four** status vocabularies (policy dispositions; applicability; platform
capability statuses; Experience-Language chips). A fifth would be debt. So the verdict vocabulary
must be a **projection of determinations Atlas already makes**, with each term having exactly one
defined source.

Of the eight candidates offered: **drop "Verified"** (a synonym of Compliant — two words for one
state is how vocabularies rot), **drop "Unknown"** as a *verdict* (keep it as the per-device
disposition it already is; as a headline it tells the operator nothing), and **merge "No Evidence"
into "Not enough evidence"** (the Experience Language's existing wording — one phrase, not two).

Six terms:

| Verdict | Defined as | Experience-Language status |
|---|---|---|
| **Compliant** | ≥1 device judged; every applicable rule passed | Healthy |
| **Non-compliant** | ≥1 applicable rule failed | Attention required (severity critical/high) · Warning (medium/low) |
| **Partially verified** | Some devices judged, some unjudged or unknown | Warning |
| **Not enough evidence** | No device in scope could be judged | Not enough evidence |
| **Not applicable** | Every device in scope was excluded by applicability or antecedent | Informational |
| **Unsupported** | No capability: no rules installed, **or** no platform can collect the evidence | Informational |

Rules that make this honest rather than decorative:

- **"Partially verified" is computed, never stored** — it is the shape of the counts, and it must
  appear whenever any device in scope went unjudged. This is the term that makes §1.3's fix visible
  to operators rather than merely correct internally.
- **"Unsupported" always names which of the two causes applies** — no rules, or no collection. They
  lead to different operator actions (install a pack vs. add a driver).
- **"Compliant" requires ≥1 judged device.** Zero judged is never compliant.
- Each maps onto an **existing** Experience-Language chip. No new visual vocabulary.

---

## 7. Sequence

```
Operator        OIR         Extraction    Validation      Policy        Reasoning     Advisor
   │             │              │          Registry       Engine        Engine          │
   │─ "Is BGP    │              │             │             │              │            │
   │   compliant?"──────────────│             │             │              │            │
   │             │─ objective=validate ──────►│             │              │            │
   │             │              │─ subject=bgp, scope=enterprise (stated)  │            │
   │             │              │             │             │              │            │
   │             │              │             │ capability("bgp")          │            │
   │             │              │             │  = tags{bgp} ∩ pack        │            │
   │             │              │             │  → STD-BGPRID-001          │            │
   │             │              │             │    @atlas-starter          │            │
   │             │              │             │             │              │            │
   │             │              │   ┌─────────┴──── none? ──────────────────────────────►│
   │             │              │   │   REFUSE: "Atlas has no validation rules for X;    │
   │             │              │   │   it can validate: …"  (never a pass)              │
   │             │              │             │             │              │            │
   │             │              │  scope → devices (Enterprise Graph)      │            │
   │             │              │             │─ evaluate_scopes() ────────►│            │
   │             │              │             │             │─ evidence?   │            │
   │             │              │             │             │   absent → UNJUDGED, reason│
   │             │              │             │             │─ applicable? │            │
   │             │              │             │             │   no → NOT APPLICABLE ◄── §1.3 fix
   │             │              │             │             │─ judge ──────►│            │
   │             │              │             │◄─ dispositions + applicability + gaps    │
   │             │              │             │                                          │
   │             │              │        aggregate over JUDGED devices only              │
   │             │              │        → verdict projection ─────────────────────────►│
   │◄────────────────────────────────────── verdict · findings · actions · detail ───────│
   │              "BGP configuration: 3 of 4 BGP speakers pass. 81 devices do not run
   │               BGP and were not judged."      ← the sentence §1.3 makes possible
```

---

## 8. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | **Not-applicable counted as compliant** (§1.3, proven). Opening validation past OSPF makes Atlas systematically overstate compliance and invert severity. | **Critical** | Carry applicability through to the evaluation and exclude it from `passed`; report it as its own count. Regression test with a minority-protocol estate. **Mandatory in this PR.** |
| **R2** | **Fixing R1 changes the /policy page's headline compliance number**, which is business-visible and pinned by tests. | **High** | **Do not silently change it.** Fix the *validation verdict* in PR-172; report the discrepancy to the user with a recommendation to align /policy in a follow-up, with the number's meaning stated on the page. Changing a headline metric is the user's call, not the implementer's. |
| **R3** | **Capability claimed without rules** — a descriptor declares tags that select nothing, and Atlas advertises a validation it cannot perform. | High | Capability is *derived*, so this is structurally impossible; `unrealised()` surfaces the mismatch. |
| **R4** | **Bespoke operators multiply** — one hand-written Python operator per technology, i.e. subject-specific validators through the back door. | High | Operators are a **closed, reviewed vocabulary**. Add *one* general operator (§9) rather than N specific ones; a new operator requires review of `matcher.py`, by design. |
| **R5** | **Config-only validation presented as full validation.** Atlas holds session-state evidence it does not consult. | High | Every validation answer states the basis: *"judged against collected configuration"*. Do not claim operational validation until the evidence port is extended (§9). |
| **R6** | **Cloud and wireless do not fit the device model.** A VPC route table is not a device with a running-config. | Medium | Out of scope for PR-172. Name it; do not let a registry design imply it is solved. |
| **R7** | **Pack version drift silently changes verdicts** — the same question answers differently after a pack update. | Medium | `pack_id@version` already travels in every result; surface it in the validation answer's supporting detail. |
| **R8** | **Performance.** PR-171 measured **3,082 ms** for one subject over 85 devices — the full pack is evaluated and then filtered. Twenty subjects, or a per-subject dashboard, multiplies that. | Medium | Evaluate once per report and slice per subject (already the shape); the /policy page's fingerprint cache is the ready-made pattern. Measure before optimising. |
| **R9** | **Masked-secret rules** (§1.5) silently mis-judge. | Medium | Freeze-time refusal at pack registration. |
| **R10** | **The generic intent regresses PR-171's routing** — validation wording must still outrank plain protocol intents. | Medium | PR-171's routing tests stay green **unmodified**; that is the acceptance gate. |
| **R11** | **Scope silently widening.** Validation with no named place is estate-wide. | Low | Already handled: PR-171 records enterprise scope *positively* with the basis stated. Preserve it. |

---

## 9. Future Extensibility

In dependency order — each is a separate PR, and none is blocked by the framework:

1. **`for_each_block` operator** (next, highest value). One general operator: *"within every block
   matching HEADER, PATTERNS must hold"*. Unlocks BGP neighbour descriptions, VLAN names, HSRP
   preemption, VRF route-targets, ACL hygiene — most of the brief's list — as **data**, with one
   reviewed code change instead of one per technology. The single highest-leverage item in this
   review after R1.
2. **A state evidence provider.** Expose what the collectors already gather (BGP sessions, OSPF
   adjacencies, VLANs, routes) as evidence kinds. Lifts Atlas from *"the config says"* to *"the
   device is doing"*. This is the real two-year item.
3. **Cross-device rules** (HSRP pairs, MLAG consistency, STP root, EVPN symmetry). A genuinely
   different rule shape — the current engine evaluates one device at a time. Needs its own design;
   do not smuggle it in.
4. **Vendor packs.** Cisco Enterprise, CIS, STIG, PCI-DSS — pure data on the existing pack registry.
5. **Cloud and wireless subjects** — once their evidence model exists (R6).
6. **Multi-subject validation** — *"is everything compliant?"* iterates capabilities. Trivial once
   capability is a registry; gate on R8.

The framework recommended here is the one that makes all six additive.

---

## 10. Recommended PR Scope

**PR-172 — Operational Validation Framework.** Small, and it must include R1.

**In scope**
1. Fix R1: applicability carried through aggregation; not-applicable is never a pass in a validation
   verdict.
2. `investigation/validation.py`: `ValidationCapability`, `capabilities()`, `capability()`,
   `unrealised()`.
3. Three fields on `SubjectDescriptor`; `policy_tags` filled in for the subjects that have rules.
4. One generic validation template, parameterised by subject; delete `VALIDATION_TEMPLATES` and the
   `ospf-configuration` block.
5. One generic `configuration-validation` OIR intent replacing the OSPF-specific one.
6. The six-term verdict vocabulary as a projection, mapped to existing Experience-Language chips.
7. Refusals and the "can currently validate" list read from the capability registry.
8. Freeze-time refusal of masked-secret rules (R9).
9. Tests + documentation (`ATLAS_VALIDATION_FRAMEWORK.md`).

**Explicitly out of scope** — and each should be *said*, not silently omitted:
- New operators, including `for_each_block` (PR-173 — but see the note below).
- The state evidence provider (PR-174).
- Cross-device rules, cloud/wireless subjects, multi-subject validation.
- Changing the /policy page's headline compliance number (R2 — user's decision).
- Writing rule content for twenty technologies. **The framework's job is to make rules the only
  thing left to write.**

**Honest note on what PR-172 alone delivers:** BGP validation, immediately and for free (§1.1).
Every other technology on the brief's list needs *rules*, and most need `for_each_block` before
useful rules can be written at all. PR-172 makes Atlas *able* to validate any technology; it does
not make Atlas *already* validate twenty of them, and the answer to "is ACL compliant?" will remain
an honest refusal until rules exist. **If the intent is to demonstrate breadth rather than
structure, PR-173 (`for_each_block`) is the more valuable PR and should be scheduled immediately
after — or merged into — this one.**

---

## 11. Success Criteria

1. **BGP validation works with zero new validation data** — no template, no intent, no dict entry —
   proving genericity from existing declarations. *(the headline test)*
2. **Adding a technology touches only data:** a subject descriptor and rules. Pinned by a test that
   adds a synthetic subject + rule at runtime and gets a working validation.
3. **R1 is closed:** a device that does not run the protocol is reported as *not applicable*, never
   as passing; the operator sentence distinguishes judged / not-applicable / unjudged. Pinned by the
   minority-protocol estate test.
4. **OIR and the Investigator are unchanged in structure** — the generic intent uses the existing
   registration API; no vendor name appears in either.
5. **PR-171's routing and validation tests pass unmodified** (R10).
6. **A subject with no rules still refuses honestly**, naming what Atlas *can* validate, sourced
   from the registry.
7. **No device is ever reported compliant without evidence.**
8. **Every verdict names its pack and version.**
9. **No new status vocabulary** — the six verdicts map onto existing Experience-Language chips.
10. **Full suite green** (baseline: 2,862 passed / 2 skipped / 866 subtests, plus the PR-170
    open-redirect fix).
11. **No regression in non-validation latency**; validation latency documented.

---

## 12. APPROVED IMPLEMENTATION PLAN

For Claude Fable. Order matters: R1 first, because every later step's tests assert against corrected
counts.

**Step 1 — Close R1 (correctness before capability).**
Carry applicability through to the evaluation without changing `conclusion_kind` (keeping the blast
radius narrow and leaving R2 to the user): add an additive `applicable: bool` to the rule outcome /
evaluation, set False from `_not_applicable_outcome`, and teach `aggregate_policy_report` to report
`not_applicable` as its own count, excluded from `pass`. Existing `PolicyReport` counters keep
today's meaning; the *validation verdict* uses the honest split. Regression test: an estate where
most devices do not run the protocol must not report them compliant.

**Step 2 — `investigation/validation.py`.**
`ValidationCapability` + `capabilities()` / `capability()` / `unrealised()`, derived from
`SUBJECTS × pack.policies` by tag intersection. Pure, no I/O, pack-parameterised with the default
pack as default. Tests: derivation, ordering, `unrealised()` catches a tag/pack mismatch, an empty
pack yields no capabilities.

**Step 3 — Descriptor fields.**
Add `validation_title`, `platform_capability` to `SubjectDescriptor` (defaulted, additive). Fill
`policy_tags` only where the pack really has matching rules — the PR-171 discipline; a wrong tag
validates the wrong thing. Do not invent rules to make subjects light up.

**Step 4 — The generic template.**
One subject-parameterised `InvestigationTemplate` built from the capability (title, objective,
completion, step labels all from `capability.label`). Delete `VALIDATION_TEMPLATES` and the
`ospf-configuration` block. `select()` rung 1 becomes `capability(subject)` → template, or None →
the existing honest refusal, unchanged. The three engines are untouched.

**Step 5 — The generic intent.**
Replace `ospf-configuration-validation` with one `configuration-validation` intent
(`objective="validate"`), subject-free wording. **Acceptance gate: PR-171's routing tests pass
unmodified.** If any must change, stop and report the conflict rather than editing the test.

**Step 6 — Verdict projection.**
The six terms as a pure function of the aggregate, mapped to existing Experience-Language chips.
"Partially verified" whenever any in-scope device went unjudged. "Unsupported" names its cause.
No new chip, no new CSS.

**Step 7 — Refusals from the registry.**
The "can currently validate" list reads `capabilities()`. Wording must stay operator-grade as the
list grows past a few subjects (PR-171 flagged this).

**Step 8 — R9 guard.**
Freeze-time refusal of rules whose patterns target masked secret values.

**Step 9 — Tests.** `tests/test_validation_framework.py`, covering all eleven success criteria,
including the two headline tests: BGP-for-free, and the synthetic-subject genericity test.

**Step 10 — Documentation.** `docs/ATLAS_VALIDATION_FRAMEWORK.md`: the corrected model, the verdict
vocabulary and its mapping, how to add a technology (two data edits), the vendor strategy, and —
stated plainly — the two ceilings and what Atlas does **not** yet validate.

**Non-goals (do not do these):**
- Do not add operators. Do not add evidence kinds. Do not touch PRISM, the Enterprise Graph, the
  collectors, or any Atlas engine beyond the aggregation seam.
- Do not add vendor logic to OIR, the subject registry, or the Investigator.
- Do not change the /policy page's headline compliance number (R2 — report it, let the user decide).
- Do not write rule content for twenty technologies.
- Do not build a second pack registry, severity scale, or vendor-targeting model.
- Do not commit.

**Handover must state:** the R1 fix and its evidence; the /policy discrepancy (R2) as an explicit
decision for the user; measured validation latency; every subject that is validatable and every one
that is not, with the reason; and what remains impossible until `for_each_block` and the state
evidence provider land.
