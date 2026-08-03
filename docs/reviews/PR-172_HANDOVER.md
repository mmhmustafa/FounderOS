# PR-172 — Operational Validation Framework — Engineering Handover

**Status: implemented per the approved architecture review
(`PR-172_OPERATIONAL_VALIDATION_FRAMEWORK.md`), adversarially reviewed, re-fixed, tested and
validated on the live 85-device estate.** Full regression suite: **2,906 passed / 0 failed /
2 skipped / 886 subtests.**

## 1. What shipped

Atlas validates **any subject whose declared `policy_tags` select rules in the active pack** —
capability is *discovered* (`investigation/validation.py`), never declared, so Atlas can never
advertise a validation it cannot perform. One generic template builder and one subject-free
`configuration-validation` OIR intent replace the OSPF-specific boilerplate. **Adding a technology
is two data edits**: a subject descriptor with `policy_tags`, and rules in a pack carrying those
tags. No template, no intent, no dict entry, no code.

Proof of genericity, live: **BGP validation worked on day one with zero new validation data** —
*"BGP configuration: Compliant — every judged evaluation passed (28 of 28). 57 device(s) in scope
do not have BGP configured and were reported as not applicable, never as compliant."*

## 2. R1 — the correctness fix, and what it revealed

A device that does not run a protocol was counted as **passing** that protocol's policies
(`_not_applicable_outcome` → `conclusion_kind=pass`). The fix carries an additive `applicable`
flag through `RuleOutcome` → `ReasoningResult` → `PolicyEvaluation`, and the aggregation counts
`not_applicable` as its own bucket with precedence *unknown → not applicable → judged*.

On the live estate, PR-171's flagship *"85 of 85 passed"* became **"63 of 63 judged, 22 not
applicable"** — 22 devices had been silently counted as OSPF-compliant without running OSPF.

**R2, deliberately untouched:** `PolicyReport.passed` (the /policy headline number) keeps its
historical meaning. Every evaluation now carries `applicable`; aligning the page is a one-line
product decision, not an implementation side effect.

## 3. The verdict vocabulary

Six terms, each a projection (`verdict_for`) of determinations the engine already made, mapped
onto **existing** Experience-Language chips: Compliant → Healthy · Non-compliant → Attention
required (critical/high) / Warning (medium/low) · Partially verified → Warning · Not enough
evidence → Not enough evidence · Not applicable → Informational · Unsupported → Informational,
naming its cause. Severity is *grave unless proven lenient*. "Compliant" requires ≥1 judged
device; "Partially verified" appears whenever anything in scope went unjudged and is always
Medium confidence.

## 4. Adversarial review — 7 confirmed findings

Five-lens review with per-finding adversarial refuters; every confirmed defect in uncommitted
code was fixed with a regression test:

| Finding | Disposition |
|---|---|
| Summary claimed "No device in scope has X configured" (High) over devices never examined | **Fixed** — summaries are projection-led and cannot contradict the stored verdict |
| All-unknown validation rendered "Compliant (0 of 0)" / Healthy | **Fixed** — `judged == 0` peels to *Not enough evidence* first |
| Validation judged the raw default pack; /policy renders the governance-effective pack with device contexts | **Fixed** — the web layer hands the Advisor the same governed runner (`AdvisorContext.policy_runner`); vetted rules derive from `report.pack` |
| Subject-free questions ("Is anything misconfigured?") emitted a garbled refusal | **Fixed** — clean refusal, Informational chip, browser-verified |
| "Partially verified" could carry High confidence | **Fixed** — always Medium |
| Unknown-reasons discarded the engine's own words | **Fixed** — the missing evidence kind is named |
| /policy explorer counts engine-level not-applicable as *Passed* (text-sniffing), inflating posture score and trend | **Reported, not fixed** — pre-existing and R2-gated; the reliable `applicable` flag makes the fix one line when the owner decides |

Security lens (PR-170 features, both **fixed with tests**): favourite pins accepted backslash
hrefs browsers normalise to protocol-relative URLs (now vetted by the central redirect
validator); the command palette listed admin pages the nav hides (now filtered by the same RBAC
predicate — `allowed_nav_path` — with 403 parity asserted).

## 5. The R9 guard found a shipped defect

Policies match **masked** text; the guard (`mask_blind_rules`) refuses rules whose patterns
contain a sensitive term. Applied to the starter pack it caught **`STD-PWENC-001`**: it hunts
`service password-encryption`, but masking erases every line containing "password" before
matching — **the rule has always failed compliant devices**. Per R2 discipline it is excluded
from validation verdicts and reported here; editing the pack (and the /policy score) is the
owner's decision.

## 6. Performance

Non-validation questions: **145 ms — zero regression**. Validation: **3.6–4.1 s** on the
85-device estate (~0.5 s over PR-171's ungoverned 3.1 s — the price of the effective pack and
device contexts). The /policy fingerprint cache is the ready-made pattern if it ever matters.

## 7. Remaining limitations

- Rule coverage: OSPF + BGP (one starter rule each). Everything else refuses honestly, naming
  what Atlas *can* validate. Most of the technology list needs the `for_each_block` operator
  (PR-173); operational-state validation needs the state evidence provider (PR-174).
- The refusal's capability list reads the default pack, not governance (display-only residual).
- Fallback keywords cover common validation phrasings, not every extraction combination — some
  phrasings mislabel the intent row while the investigator still answers correctly
  (pre-existing shape).
- Aggregation device sets key by hostname; same-named devices across merged scopes could
  miscount (pre-existing, edge).
- The R9 guard inspects pattern text; a regex reaching a sensitive term obliquely can evade it.

## 8. Open decisions for the owner

1. **Align the /policy headline number** with the honest applicability split (R2)?
2. **`STD-PWENC-001`** — fix, retire, or leave the mask-blind rule?
