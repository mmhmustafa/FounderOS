# The Atlas Operational Validation Framework (PR-172)

*Teach Atlas how to validate any technology — by discovering, never declaring.*

Architecture review: `docs/reviews/PR-172_OPERATIONAL_VALIDATION_FRAMEWORK.md` (the authoritative
design; this document describes what shipped).

## The model

```
Subject + Objective            (PR-171 extraction — unchanged)
        │
        ▼
Validation Capability          DISCOVERED, never declared:
= subject.policy_tags          a capability that selects zero rules
  ∩ installed pack rules       does not exist, so Atlas can never
  (mask-blind rules refused)   advertise a validation it cannot do
        │
        ▼
Scope resolution               (PR-171 — enterprise scope is positive)
        │
        ▼
Evidence availability          no evidence ⇒ unjudged, with the reason
        │                      — never inferred, never compliant
        ▼
Rule selection                 tags ∩ applicability, per device;
        │                      unknown attributes never guessed
        ▼
Policy Engine                  UNCHANGED — dispositions + confidence
        │                      are the engine's own
        ▼
Determinations                 pass / fail / warning / unknown
+ applicability                + applicable / NOT APPLICABLE (R1)
        │
        ▼
Verdict                        a PROJECTION of the above —
                               computed, never stored
```

**Evidence is an input, not an output.** The one correction to the original proposal: a verdict is
never formed first and evidenced afterwards. Absent evidence stops the pipeline with "not enough
evidence"; it never becomes a silent pass.

## R1 — not applicable is a third outcome, never a pass

Before this PR, a device that did not run a protocol was counted as **passing** that protocol's
policies (`conditional_present` with an absent antecedent produced `conclusion_kind=pass`). On an
85-device estate with 4 BGP speakers, "Is BGP compliant?" would have read *"84 of 85 passed"* even
with every real speaker broken.

Now:

- `RuleOutcome.applicable` / `ReasoningResult.applicable` / `PolicyEvaluation.applicable` carry the
  determination through (additive fields; `conclusion_kind` is unchanged — see the R2 note below).
- `aggregate_policy_report()` counts `not_applicable` as its own bucket, excluded from `pass`, with
  per-evaluation precedence **unknown (no evidence) → not applicable → judged disposition** and
  device-level splits: `devices_judged`, `devices_not_applicable`, `devices_evaluated`.
- The operator sentence distinguishes all three: *"BGP configuration: Non-compliant — 1
  evaluation(s) failed; 1 of 2 judged evaluation(s) pass. 3 device(s) in scope do not have BGP
  configured and were reported as not applicable, never as compliant."*

**R2 — DECIDED and aligned (PR-174.2).** PR-172 deliberately left the `/policy` headline compliance
number counting not-applicable evaluations as passes, and reported the discrepancy rather than
changing a business-visible metric unasked. That decision has since been taken: `PolicyReport.passed`
now excludes them, `not_applicable` is its own count in the report and its `to_dict()`, and the
score's numerator and denominator both ignore it. `PolicyEvaluation.applicable` is the authority —
`status` alone cannot distinguish "passed" from "never applied", because the engine gives the
not-applicable outcome `conclusion_kind = pass`.

The page's own bucketing (`explorer.effective_status`) now reads that same flag instead of sniffing
reasoning-path prose for the phrase *"not applicable"* — prose that only `conditional_present`
produced, so `interfaces_shutdown`'s not-applicable detail (*"no non-loopback interfaces found to
assess"*) was bucketed as a pass and inflated both the posture score and the recorded trend. Engine
score and page score are now computed from the same definition and verified equal.

## The capability registry (`investigation/validation.py`)

```python
capability("bgp")   # ValidationCapability(subject, label, title, rules,
                    #   pack="atlas-starter@1.0", evidence_kinds, platforms)
capabilities()      # every validation Atlas can perform, sorted by label
unrealised()        # subjects declaring tags that select no rule
mask_blind_rules()  # rules the masked config view blinds (R9)
verdict_for(...)    # the six-term verdict projection
```

- **Derived, so it cannot lie**: `SUBJECTS × active pack`, joined on `policy_tags ∩ Policy.tags`.
  Install a pack and capability grows; no registration API, no code change.
- **Provenance on every capability**: the exact `rules` and `pack_id@version` behind any verdict.
- **`unrealised()`** surfaces registry/pack disagreements as diagnostics, never crashes.

## Adding a technology

1. Ensure the subject exists in `investigation/subjects.py` and declares `policy_tags` (most
   already exist; the canonical tag is the subject key).
2. Write rules in a pack, tagged accordingly.

That is the whole list. No template (one generic builder serves every subject), no intent (one
subject-free `configuration-validation` intent serves every subject), no dict entry, no code.
BGP validation lit up on the day this framework landed with **zero new validation data** — the
descriptor and the starter rule already existed.

## The verdict vocabulary

Six terms, each a projection of determinations Atlas already makes, each mapped onto an
**existing** Experience-Language chip — no fifth status vocabulary:

| Verdict | Defined by | Chip |
|---|---|---|
| **Compliant** | ≥1 device judged; every applicable rule passed | Healthy |
| **Non-compliant** | ≥1 applicable rule failed | Attention required (critical/high) · Warning (medium/low) |
| **Partially verified** | some judged, some unjudged or unknown | Warning |
| **Not enough evidence** | nothing in scope could be judged | Not enough evidence |
| **Not applicable** | everything evaluated, nothing applied | Informational |
| **Unsupported** | no capability — no rules for the subject | Informational, naming the cause and what Atlas *can* validate |

Rules that keep it honest: "Compliant" requires at least one judged device; "Partially verified"
is computed from the counts whenever any in-scope device went unjudged; severity is **grave unless
proven lenient** — a failing rule with no declared severity keeps the Attention chip.

## The masked-secret guard (R9)

Policies match **masked** configuration text: any line containing a sensitive term (`password`,
`secret`, `key`, `community`, `token`, `credential`) is replaced wholesale before matching. A rule
whose pattern contains one of those terms is structurally blind — its target line cannot exist in
the text it searches — and would mis-judge silently in both directions.

The guard (`mask_blind_reason` / `mask_blind_rules`) refuses such rules **at the capability seam**:
they never enter a capability, never shape a verdict, and are named as diagnostics. Scope:
`running-config` evidence only — other evidence kinds are not rewritten by the masker.

> Found on arrival, **now fixed at the cause (PR-174.2)**: the starter pack's `STD-PWENC-001`
> ("service password-encryption") was mask-blind and had always mis-judged — it failed *compliant*
> devices, because their `service password-encryption` line was masked away before the matcher ran.
> PR-172 excluded it from verdicts and reported it rather than silently editing the pack.
>
> The rule was correct; the **masker** was wrong. `service password-encryption` is an argument-free
> switch: it contains a sensitive word but carries no secret *value*, so masking it hid whether a
> security control was enabled while hiding nothing worth hiding. `mask_line` now spares a small
> allowlist of such directives (`_SAFE_DIRECTIVES`), matched **whole line** — never by prefix, so a
> directive cannot vouch for whatever a device appends after it — and every entry must be
> argument-free, which a test asserts per entry. Real secret-bearing lines are still masked, also
> pinned by test. The R9 guard skips these directives, so it no longer flags the rule; a rule hunting
> a secret's *value* is still refused, as before.
>
> This is why the guard reports rather than deletes: the diagnostic named a real defect, and the
> defect turned out to be in the masker, not in the rule it flagged.

## One judgement, two surfaces (governance parity)

The web layer supplies the Advisor's policy evaluation (`AdvisorContext.policy_runner`): the
**same governance-effective pack and device contexts the /policy page renders**. A governance
edit — a retired rule, a platform retarget — shapes the validation verdict and the policy page
identically, because there is only one pipeline. Consequences enforced in code:

- The capability's vetted rules are derived from **the pack the report was judged with**
  (`report.pack`), never the raw default, at both answer paths.
- A scope that produced no evaluations is *"not enough evidence"*; *"no configuration policies"*
  is said only when the report's own pack truly carries none.
- The summary layer only ever **repeats** the stored verdict projection — the not-applicable
  sentence ("No device in scope has X configured") requires every in-scope device to have been
  examined; anything unjudged downgrades the answer to *Not enough evidence*, never a positive
  claim about devices Atlas has not seen.
- Headless callers (tests, CLI) that supply no runner keep the advisor's ungoverned fallback.

## Vendor integration

Vendor knowledge lives in three existing layers — none of them OIR, the subject registry, or the
Investigator:

| Layer | Where | Adding a vendor means |
|---|---|---|
| Collection | `platforms/drivers/*.py` | one driver file |
| Normalisation | `platforms/capabilities.py` | usually nothing |
| Targeting | `PolicyApplicability.platforms` | rules, as data |

Vendor differences in what is *correct* are separate rules with different selectors — never
branches in code. A rule targeting a platform is **not applicable** to a device whose platform
Atlas has not established; it never guesses.

## The two ceilings (stated, not implied)

What Atlas validates today is precisely **configuration-text validation**, and the answer's basis
says so. Two ceilings bound the technology list until their own PRs land:

1. **The rule language** — five presence-class operators over whole-file text. "Every BGP
   neighbour has a description", "every VLAN has a name", ACL hygiene and their kin need a
   `for_each_block` operator (the planned next PR). Cross-device rules (HSRP pairs, MLAG
   consistency) need a genuinely new rule shape.
2. **The evidence port** — the policy engine sees `running-config` and `access-transport` only.
   Everything else the collectors gather (BGP sessions, OSPF adjacencies, VLANs, routes) awaits a
   state evidence provider before "the device is doing" can be judged alongside "the config says".

A subject whose rules cannot be expressed yet is an honest refusal — never a capability
registered beyond what the engine can deliver.
