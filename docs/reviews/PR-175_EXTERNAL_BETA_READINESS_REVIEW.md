# PR-175 — Atlas External Beta Readiness Review

**Role:** Chief Product Architect / Enterprise UX Architect / Beta-Readiness Reviewer.
**Status:** audit only — nothing implemented, nothing modified, nothing committed.
**Method:** the running product, inspected in the browser on **two** workspaces — a **fresh
(never-discovered)** instance for the first-run journey and empty states, and the **live 85-device
estate** for populated behaviour. Every number below was measured, not estimated.

---

## 1. Executive verdict

**Atlas is much closer to external beta than the "visually busy / intimidating" framing suggests —
but it is not there yet, and the gap is not a visual-polish gap.**

The audit expected to find a product that looked good and explained itself badly. The opposite is
closer to the truth. The things that are usually broken at this stage are **already right**:

- **Every one of the 24 destinations renders on an empty workspace** with copy explaining what the
  page is and why it is empty. Nothing shows a bare "no data".
- **The trust model holds visually.** Unknown renders slate-grey (`rgb(100,116,139)`), never green.
  All five verdict chips pass WCAG AA contrast (4.51–14.36).
- **Zero form fields lack accessible names** across the wizard, profile and settings forms
  (wrapping `<label>`), and **zero of 578 focusable elements** on the densest page lack an
  accessible name.
- **Zero horizontal page overflow at 375 px** on the heaviest pages; wide tables sit in scrollable
  containers.
- **Home leads verdict-first** and volunteers *"Evidence freshness: 19onlyAI (stale — 8 day(s)
  old) — stale evidence weakens every conclusion above."* Very few products admit that unprompted.

What actually blocks beta is narrower and more structural: **the product presents its whole
implementation surface to a first-time user, and asks them to read rather than to act.** Twenty-four
destinations — including a developer playground — are visible before the user has a single device.
The densest pages carry 1,000–3,400 words. The first click on Policy blocks for ten seconds with no
progress indication.

**A new engineer can answer 9 of the 12 primary questions unaided. They cannot reliably answer
"What should I do first?", "Where do advanced capabilities live?", or "What can Atlas not
determine?" — because everything is presented at once and at equal weight.**

## 2. External-beta readiness score

# 72 / 100

| Dimension | Score | Note |
|---|---|---|
| Honesty & trust model | 19/20 | Best-in-class; unknown never reads as healthy |
| Empty states | 9/10 | Every page explains itself; some explain the *subsystem* not the *next step* |
| Accessibility foundations | 8/10 | Names, labels, contrast, focus rules all present; tab-depth is the gap |
| Responsive | 8/10 | No overflow at 375 px; 4 sub-32 px touch targets |
| First-run journey | 7/15 | Strong start, no "what is Atlas", no guided path after discovery |
| Information architecture | 5/15 | 24 destinations, dev playground in primary nav |
| Visual hierarchy / density | 6/15 | Prose volume and control counts, not colour or spacing |
| Perceived performance | 6/10 | 10 s cold Policy render with no progress |
| Consistency | 4/5 | One product; minor verdict-vocabulary drift |

## 3. Top 10 issues by impact

| # | Issue | Severity | Evidence |
|---|---|---|---|
| 1 | **First click on Policy blocks ~10 s with no progress indication** | **BLOCKER** | Cold render **9,975 ms**; warm 98–388 ms. Server-rendered, so the browser shows nothing. A beta tester will conclude Atlas has hung. |
| 2 | **24 primary destinations exposed before the user has any data** | **HIGH** | 5 groups / 24 items; on a fresh workspace 23 lead to "nothing here yet" pages. This is the "intimidating" complaint's actual cause. |
| 3 | **"PRISM Playground" ships in primary navigation** | **HIGH** | Present in nav on every page; page itself says *"Nothing here touches your enterprise"*. A developer tool in the operator's sidebar. |
| 4 | **Reading load on core pages** | **HIGH** | Policy 3,420 words · Audit 2,462 · Changes 2,341 · Investigate 1,429 · Advisor 1,288 · Timeline 1,235. Investigate is a *tool*, not an essay. |
| 5 | **No "what is Atlas / what do I do first" on first run** | **HIGH** | Only the tagline "Enterprise Network Intelligence". Home's CTA is good but singular; nothing frames the product or the journey. |
| 6 | **Discovery's required next step is the least prominent thing on the page** | **HIGH** | *"Add a profile"* is inline text; *"Execution Console (sample)"* and *"Discovery Wizard"* are the prominent CTAs. You cannot discover without a profile. |
| 7 | **"(sample)" and "Execution Console" in operator UI** | **MEDIUM** | Developer artifacts on `/discovery`. |
| 8 | **Home's tiles speak Atlas-internal vocabulary** | **MEDIUM** | "Canonical devices 85", "Observations 85", "Merged devices 0" — and 4 of 7 tiles show the same number (85). |
| 9 | **Version not visible outside Settings** | **MEDIUM** | `0.3.0` only on `/settings`. Beta bug reports need it at a glance. |
| 10 | **Keyboard depth on dense pages** | **MEDIUM** | 578 focusable elements on `/changes`; 207 buttons. Reaching page content by keyboard is impractical. |

**No BLOCKER was found in the trust model, the verdict vocabulary, empty states, or accessibility
naming** — the four areas most likely to sink an external beta.

## 4. First-time-user journey findings

Walked on a genuinely empty workspace.

| Step | Result | Finding |
|---|---|---|
| Launch | ✅ | Loads to Home, no crash, no auth wall in local mode |
| Understand what Atlas is | ⚠️ **HIGH** | Tagline only. No positioning, no "here's how this works". |
| Understand current state | ✅ **excellent** | *"Network state is unknown — no discovery has run yet. Atlas reports only what evidence proves."* + evidence line *"no topology snapshot exists in any scope"* |
| Know what to do first | ✅ | "Run your first discovery" — one clear CTA |
| Configure settings | ✅ | Not required before discovery. Correct default. |
| Provide credentials | ⚠️ **HIGH** | `/discovery` foregrounds "Execution Console (sample)" and the Wizard; the mandatory "Add a profile" is inline text. |
| Start discovery | ✅ **strong** | 6-step wizard — Scope → Credentials → Boundaries → Preview → Confirm → Results — with "Generate safe preview" and *"Drafts never contain passwords."* This is genuinely good safety-first design. |
| Understand progress | ⏳ not exercised | No live discovery run against real gear in this audit; flagged as a **gate item to verify**, not a finding. |
| Understand completion | ⏳ not exercised | Same. |
| View topology | ✅ (post PR-174) | Renders with nodes in view; wheel zoom gradual (PR-174.1). |
| Understand condition | ✅ | Home surfaces freshness and attention items. |
| Ask a question | ✅ | Advisor accepts natural questions; answers verdict-first. |
| Interpret verdict | ✅ | Chip + headline + context row + evidence. |
| Inspect evidence | ✅ | Every verdict deep-links to `/policy` or `/topology`. |
| Investigate a problem | ⚠️ MEDIUM | `/paths` opens with 1,429 words before the form. |
| Understand next action | ⚠️ MEDIUM | Present per-answer; absent as a global "what now?" after discovery completes. |

**"What am I supposed to do now?" moments:** (a) immediately after launch, before the CTA is read;
(b) on `/discovery`, deciding between Console/Wizard/profile; (c) after discovery completes — no
"here's what Atlas found, look here next"; (d) on first opening any of the 20 non-Home destinations.

## 5. Page-by-page readiness matrix

Measured: words, tiles, tables, controls, cold ms.

| Page | Class | Words | Controls | Cold ms | Note |
|---|---|---|---|---|---|
| Home `/` | **A** | 522 | 25 | 471 | Verdict-first, freshness volunteered, CTA clear. Tiles last. |
| Advisor `/advisor` | **A** | 1,288 | 135 | 441 | The product's best surface. Trim intro prose. |
| Topology `/topology` | **B** | 133 | — | 1,022 | Fixed by PR-174/174.1. Unresolved-identity count unexplained. |
| Action Center `/inbox` | **B** | 102 | 6 | 129 | Calm and clear. |
| Discoveries `/history` | **B** | 44 | 5 | 345 | Minimal, purposeful. |
| Compass `/compass` | **B** | 70 | 3 | 210 | Clear; name requires explanation. |
| Signals `/telemetry` | **B** | 159 | 4 | 118 | Honest "no adapter configured" state. |
| Schedules `/schedules` | **B** | 108 | 20 | 94 | Fine. |
| Incidents `/incidents` | **B** | 264 | 18 | 218 | Dense opening sentence. |
| Predict `/predict` | **B** | 383 | 8 | 128 | Fine. |
| Settings `/settings` | **B** | 442 | 28 | 363 | Holds version — should surface it globally. |
| Discovery `/discovery` | **C** | 145 | 10 | 233 | **Required action least prominent**; "(sample)" artifact. |
| Configuration `/configuration` | **C** | 989 | 205 | 320 | 102 buttons, 50 rows, 6 tiles. |
| Evidence `/evidence` | **C** | 1,092 | 271 | 563 | 105 buttons + 57 inputs. |
| Timeline `/timeline` | **C** | 1,235 | 77 | 404 | 5 tiles + 55 rows + 2 tables. |
| Investigate `/paths` | **C** | 1,429 | 29 | 290 | Essay before instrument. |
| Audit `/audit` | **C** | 2,462 | 7 | 270 | 50 rows of raw mutation log. |
| Changes `/changes` | **C** | 2,341 | 564 | 298 | **203 buttons, 159 inputs, 230 KB.** |
| Policy `/policy` | **C** | 3,420 | 687 | **9,975** | 12 tiles, 4 tables, 520 links. Cold render is the blocker. |
| PRISM `/settings/ai` | **C** | 1,083 | 81 | 45 | 8 tiles + 76 inputs for an optional feature. |
| PRISM Playground | **E** | 527 | 15 | 356 | **Not appropriate for external beta in primary nav.** |

**Why the C's are C's:** not colour, spacing or typography — all of which are competent. It is
**quantity at uniform weight**. `/changes` offers 564 controls with no primary action; `/policy`
offers 687. When everything is available, nothing is recommended.

**Why Playground is E:** it is a demonstration surface that explicitly touches no enterprise data,
sitting in the operator's permanent navigation. It signals "unfinished product" to an external
tester more than any missing feature would.

## 6. Navigation / information architecture

Current: **5 groups, 24 destinations**, Administration holding 9.

The grouping (Home / Network / Operations / Analyze / Administration) **is** operator-shaped — that
is the right axis. The failure is **volume and gating**, not taxonomy.

Evidence of implementation-shaped exposure: `Evidence`, `Configuration`, `Timeline`, `Discoveries`,
`Changes` are five separate destinations that a working engineer experiences as one question —
*"what does Atlas know, and what changed?"* `PRISM` and `PRISM Playground` are two destinations for
one optional feature.

**Recommendation — reduce exposure, not capability:**

1. **Remove PRISM Playground from primary nav** (reach it from the PRISM settings page). −1.
2. **Fold `PRISM` into Settings** as a section. −1.
3. **Progressive navigation:** before the first successful discovery, show only Home, Discover,
   Settings. Reveal the rest on completion. This is the single highest-leverage IA change and it
   removes nothing permanently.
4. **Consider merging `Discoveries` into `Timeline`** — both are chronologies of the same events.
   Evidence: Timeline's own copy says it contains "discoveries, …, changes"; `/history` is 44 words.

Net: 24 → 22 permanently, **24 → 3 on first run**. No capability lost, no deep link broken.

## 7. Visual hierarchy review

Typography, spacing, borders, chips and status colours are **consistent and competent**; there is no
evidence of a styling problem. The hierarchy problem is **density and prose**, and it is measurable:

- **Control density:** `/changes` 564 interactive elements, `/policy` 687, `/evidence` 271.
- **Tile inflation:** `/policy` 12 tiles, `/changes` 8, `/settings/ai` 8, `/` 7, `/configuration` 6.
- **Prose volume:** six pages exceed 1,000 words *before* the operator acts.
- **Redundant tiles:** Home shows 85 four times (Devices, Configurations, Canonical devices,
  Observations).

**Dashboard syndrome — confirmed on `/policy`:** 12 tiles + 4 tables + 520 links + 3,420 words,
opening with counts rather than a verdict. Contrast with Home, which opens with a sentence.
Home is the pattern; Policy is the anti-pattern. *The fix is to apply Atlas's own Experience Language
to the pages that predate it.*

## 8. Terminology review

| Term | Verdict | Action |
|---|---|---|
| **Advisor**, **Topology**, **Policy**, **Evidence**, **Schedules**, **Settings**, **Incidents**, **Changes**, **Timeline**, **Discover** | Intuitive | Keep as-is |
| **Action Center** | Intuitive, mildly generic | Keep |
| **Investigate** (`/paths`) | Good verb; page is about *paths* | Keep name, lead with the tool |
| **Signals** | Requires explanation | Keep + subtitle "telemetry evidence" |
| **Compass** | Branding, not self-evident | Keep + subtitle "maintenance planning" |
| **PRISM** | Product branding, well-explained on its page | Keep; move under Settings |
| **PRISM Playground** | Internal tool name | **Remove from nav** |
| **OIR**, **CORTEX** | Internal architecture | ✅ **Already absent from the UI** — verified; they appear only in code and docs. No action. |
| "Canonical devices", "Observations", "Merged devices" | **Implementation vocabulary in the operator's face** | Rename to plain English or move behind Detailed view |
| "Resolution Center" | Not present in current nav | No action |

Atlas has **already won** the terminology battle where it mattered: no internal subsystem name
reaches the UI. The remaining exposure is the Home tile labels.

## 9. Verdict / evidence / trust review

**This is Atlas's strongest area and it is genuinely differentiating.**

Verified by computed style, not inspection:

| State | Border | Chip bg | Chip text | Contrast |
|---|---|---|---|---|
| Healthy | green `21,128,61` | `220,252,231` | green | 4.57 ✅ |
| Attention | red `220,38,38` | `254,226,226` | red | 5.30 ✅ |
| Warning | amber `217,119,6` | `254,243,199` | amber | 4.51 ✅ |
| **Unknown** | **slate `100,116,139`** | **neutral grey** | near-black | **14.36 ✅** |
| Informational | blue `37,99,235` | `238,242,255` | blue | 4.62 ✅ |

**No visual treatment can cause "unknown" to read as "healthy."** The requested blocker check
**passes**. Grey is categorically separated from green, and unknown has the *highest* contrast of
any state.

Supporting behaviours verified: freshness volunteered on Home ("stale — 8 day(s) old"); staleness
refuses state verdicts outright (PR-173); not-applicable is never counted as compliance (PR-172/174.2);
capability gaps produce refusals naming what Atlas *can* do.

**One consistency gap (MEDIUM):** Atlas now carries two verdict vocabularies —
Compliant/Non-compliant (configuration) and Healthy/Degraded/Failed (state) — sharing a tail
(Not enough evidence / Not applicable / Unsupported). This is correct by design, but **nothing in
the UI explains the distinction to a first-time user.** An engineer seeing "Compliant" and
"Degraded" for BGP on adjacent surfaces needs one sentence telling them these are different axes.

## 10. Empty-state and error-state review

**Empty states: the strongest audit result.** All 24 destinations render on a never-discovered
workspace; all carry explanatory copy. Samples:

- Topology: *"No topology has been generated yet in any network. Run a discovery to build the
  interactive topology viewer."* — why, whether normal, what to do.
- Evidence: *"No evidence has been collected yet. Atlas records what every device returns during
  discovery — the exact output, kept so a conclusion can always be traced."*
- Signals: *"No live telemetry adapter is configured."* — honest unsupported state.
- Schedules: *"No discovery schedules yet."* + create action.

**The gap (MEDIUM):** several empty states explain **the subsystem** rather than **the user's next
step**. Incidents opens *"Detection to resolution, evidence all the way: an investigation runs
deterministically against one observation point's artifacts…"* — accurate, and not what someone with
zero devices needs. Empty states should say *"Nothing here yet — that's expected until discovery
runs"* and link to the one action that changes it.

**Error/degraded states:** the honesty ladder (what happened → what Atlas could still determine →
what it could not → what to do) is present in the engine layer and in Advisor answers. **Not
exercised in this audit:** unreachable device, auth failure, partial discovery, collector failure —
these need a live failing discovery and are listed as **gate items**, not findings.

## 11. Topology review

Post PR-174 / PR-174.1, measured: bounding box 5,427 (was 78,783); 23 nodes in view on load (was 0);
wheel 1.148×/notch (was 2.512×); no diagnostic violations under `?diag=1`.

- Initial readability ✅ · Fit all ✅ (→17%) · Reset view ✅ (→86%) · Lens ✅ · +/− ✅ (1.25×/press)
- Logical and Force layouts both render and zoom identically ✅
- Development-mode invariants available (`?diag=1`) ✅

**Remaining gaps for a first-time operator:**
- **"60 unresolved peer identities"** appears in the viewer header with no explanation of what an
  unresolved peer identity is or whether it is a problem. (MEDIUM — trust-adjacent: an unexplained
  count reads as an error.)
- The `/topology` host page is 133 words wrapping an iframe; the legend and controls live inside
  the artifact, so first-time guidance has nowhere to sit.

## 12. Responsive and accessibility review

**Responsive — measured at 375 / 768 / 1440 / 1920:**

| Page | 375 px page overflow | Wide tables | Handling |
|---|---|---|---|
| `/policy` | **0 px** | 4 (680–1080 px) | all in scrollable containers ✅ |
| `/changes` | **0 px** | 1 (1080 px) | scrollable ✅ |
| `/advisor` | **0 px** | — | ✅ |

**No horizontal page overflow anywhere tested.** This is better than most enterprise UIs.

**Accessibility:**
- **0 of 578** focusable elements on `/changes` lack an accessible name ✅
- **0 unlabelled fields** across wizard (21), profile (17), settings (14) — wrapping `<label>` ✅
- 21 `:focus` CSS rules present ✅ · all five verdict chips pass AA ✅
- ⚠️ **4 buttons under 32 px tall** at 375 px (touch-target minimum)
- ⚠️ **578 tab stops** on `/changes` — content is keyboard-reachable in principle, impractical in
  practice. Needs skip-links or landmark navigation on dense pages.
- ⚠️ 27 hover-only CSS rules — needs a focus-parity check before beta.

## 13. Perceived-performance review

| Page | Cold | Warm |
|---|---|---|
| `/policy` | **9,975 ms** | 98–388 ms |
| `/topology` | 1,022 ms | 431–456 ms |
| `/` | 471 ms | 259 ms |
| all others | 45–563 ms | — |

**The single blocker.** Because pages are server-rendered synchronously, the 10-second cold Policy
render shows **nothing at all** — no skeleton, no spinner, no progress. A first-time user clicking
"Policy" experiences a hung application. The warm path proves the work is cacheable; the cache is
simply cold on the first click after any discovery.

Everything else feels responsive. No layout shift observed; no frozen controls.

## 14. Cross-product consistency review

Atlas reads as **one product**. Consistent: chrome, nav, scope selector, Detail level, verdict chips,
Pin/favourite affordance, breadcrumbs, timestamps (`12-Aug-2026 14:54 IST`), freshness language,
evidence deep-links, "Apply filters/Clear" pattern.

Inconsistencies, all MEDIUM or below:
- **Page-opening pattern:** Home/Advisor open with a verdict; Policy/Changes/Timeline open with
  tiles and filters. The Experience Language is applied to newer surfaces only.
- **Two verdict vocabularies** with no in-product explanation (§9).
- **Tile vocabulary** on Home is implementation-shaped while every other surface is operator-shaped.

## 15. Beta-readiness blockers

**BLOCKER (must fix):**
1. **Policy cold render, 10 s, no progress indication.** Risk: tester concludes Atlas is broken.

**HIGH (fix before external beta):**
2. 24 destinations exposed on a workspace with no data.
3. PRISM Playground in primary navigation.
4. "(sample)" / "Execution Console" developer artifacts in operator UI.
5. Discovery's required next step ("Add a profile") is the least prominent element.
6. No product framing or first-run orientation.
7. Prose volume on six core pages.

**No blocker exists in:** trust/verdict treatment, empty-state coverage, accessibility naming,
responsive layout, or secret handling — the areas that would have forced a "NOT READY".

## 16. Beta Readiness Gate

Measurable pass/fail. Atlas ships the external beta when **all** are true.

| # | Criterion | Measure | Now |
|---|---|---|---|
| G1 | No page blocks >2 s without visible progress | cold render timed on every nav destination | ❌ Policy 9,975 ms |
| G2 | First run exposes ≤5 destinations until discovery completes | count nav items on fresh workspace | ❌ 24 |
| G3 | Zero developer artifacts in operator UI | grep rendered HTML for "sample/playground/demo/TODO" | ❌ 4 occurrences |
| G4 | Every page's required next action is its most prominent control | manual review, 24 pages | ❌ Discovery fails |
| G5 | Product framing visible on first launch | "what Atlas does" on Home for a new workspace | ❌ absent |
| G6 | Version visible without entering Settings | header or footer | ❌ Settings only |
| G7 | Unknown never renders as healthy | computed-style check per state | ✅ **passes** |
| G8 | Every verdict state visually distinct + AA contrast | contrast per chip | ✅ **passes (4.51–14.36)** |
| G9 | Every destination renders with guidance on an empty workspace | 24/24 | ✅ **passes** |
| G10 | Zero horizontal overflow at 375 px | scrollWidth vs clientWidth | ✅ **passes** |
| G11 | Zero focusable elements without accessible names | audit densest 3 pages | ✅ **passes** |
| G12 | All form fields labelled | wizard/profile/settings | ✅ **passes** |
| G13 | Discovery failure paths tested end-to-end | unreachable host, bad credentials, partial run | ⏳ **unverified** |
| G14 | Secrets never rendered | existing tests + spot check | ✅ passes (test-enforced) |
| G15 | Recovery from a failed discovery is possible without file surgery | retry/delete from UI | ⏳ unverified |
| G16 | Touch targets ≥32 px at 375 px | measure | ❌ 4 fail |
| G17 | Dense pages offer skip-to-content / landmarks | keyboard reachability | ⚠️ partial |

**7 pass, 6 fail, 2 unverified, 2 partial.**

## 17. Prioritized refinement PR plan

Grouped by **systemic cause**, not by page — five PRs, not twenty.

### MUST COMPLETE BEFORE BETA

**PR-176 — Nothing blocks without saying so**
*Objective:* no operator ever faces a silent wait. *Scope:* precompute or background-prime the
policy report so the first Policy click is warm; add a progress affordance to any render >1 s.
*Pages:* `/policy` primarily; audit `/topology`, `/evidence`. *Why:* the only BLOCKER — it reads as
a hung app. *Dependencies:* none. *Acceptance:* G1 — no destination exceeds 2 s cold without visible
progress; Policy cold ≤2 s or shows progress from 300 ms.

**PR-177 — First-run: show three doors, not twenty-four**
*Objective:* a new user sees only what they can act on. *Scope:* gate navigation to Home / Discover /
Settings until the first discovery completes, then reveal the rest with a one-time "Atlas is ready —
here's what it found" moment; add product framing to empty Home; make "Add a profile" the primary
action on `/discovery`; remove "(sample)" and "Execution Console" from operator UI; remove PRISM
Playground from nav and fold PRISM into Settings. *Pages:* nav shell, `/`, `/discovery`, `/settings`.
*Why:* issues 2, 3, 5, 6, 7 share one cause — everything exposed at once. *Dependencies:* none.
*Acceptance:* G2, G3, G4, G5 pass; no deep link breaks; all destinations still reachable by URL.

**PR-178 — Apply the Experience Language to the pages that predate it**
*Objective:* every page opens with an answer, not an inventory. *Scope:* verdict-first opening
(verdict → short explanation → key facts → evidence → advanced) on `/policy`, `/changes`,
`/timeline`, `/evidence`, `/configuration`, `/paths`; move the explanatory essays behind
"About this page"; progressive disclosure of filters/bulk controls; relabel Home's tiles into
operator English and drop the duplicated 85s; one sentence explaining configuration-vs-state
vocabularies. *Pages:* the six C-class pages + Home. *Why:* issues 4, 8 and the §7 density finding
are one systemic cause. *Dependencies:* none (uses the existing Experience Language).
*Acceptance:* no core page exceeds 600 words before first interaction; each has exactly one visually
dominant primary action; verdict-first pattern verified on all six.

### SHOULD COMPLETE BEFORE BETA

**PR-179 — Failure paths, proven**
*Objective:* prove Atlas explains failure as well as success. *Scope:* exercise unreachable device,
bad credentials, partial discovery, collector failure, unsupported platform; ensure each follows
what happened → what Atlas could still determine → what it could not → what to do next; ensure
recovery/retry from the UI. *Pages:* discovery wizard, `/history`, `/evidence`, Home.
*Why:* G13/G15 unverified, and beta testers *will* hit bad credentials on day one.
*Dependencies:* none. *Acceptance:* G13, G15 pass with recorded evidence per scenario.

**PR-180 — Beta hygiene**
*Objective:* the small things testers judge a product by. *Scope:* version + build in the header or
footer; explain "unresolved peer identities" in the topology viewer; raise sub-32 px touch targets;
focus-parity for the 27 hover-only rules; skip-links/landmarks on dense pages.
*Pages:* app shell, topology viewer, `/changes`, `/policy`.
*Why:* G6, G16, G17 plus the topology trust gap. *Dependencies:* PR-178 for dense pages.
*Acceptance:* G6, G16 pass; G17 satisfied by landmark navigation.

### CAN WAIT UNTIL AFTER BETA

- Merging `Discoveries` into `Timeline` (needs real usage evidence first).
- Terminology subtitles for Signals/Compass (tooltips suffice for beta).
- Reducing `/audit`'s 2,462-word raw log (correct for its audience).
- Any new capability whatsoever.

## 18. Explicitly deferred

This audit proposes **no new features**. Everything above is removal, reordering, disclosure, or
proving what already exists. Deferred to roadmap: multi-vendor breadth, state history, cross-device
rules, `for_each_block`, cloud/wireless subjects, live telemetry adapters.

## 19. Recommendation

# READY AFTER SPECIFIED PRs

Specifically: **PR-176, PR-177 and PR-178 (MUST), then PR-179 and PR-180 (SHOULD).**

Not "NOT READY": the foundations that are expensive to retrofit — honesty model, evidence
provenance, empty-state coverage, accessibility naming, responsive layout — are **already sound and
measurably so**. Not "READY": a first-time user today meets a 10-second silent wait, 24 doors, and a
developer playground.

**The remaining work is subtraction and sequencing, not construction.** That is a good position.

## 20. Approved product refinement plan

1. **PR-176** — eliminate the silent wait. *(BLOCKER)*
2. **PR-177** — first-run: three doors, product framing, artifacts removed. *(HIGH)*
3. **PR-178** — Experience Language applied to the six legacy pages + Home tiles. *(HIGH)*
4. **PR-179** — failure and recovery paths proven. *(SHOULD)*
5. **PR-180** — version, touch targets, focus parity, topology explanation. *(SHOULD)*

**Re-audit against the Gate after PR-178.** Target: 16/17 criteria, with G13/G15 closed by PR-179.

### Windows distribution readiness

**Do not begin installer, code-signing, licensing or update-channel work until PR-176, PR-177 and
PR-178 are complete and the Gate is re-run.** Rationale: each of those PRs changes what a
first-time user sees on launch, which is precisely what an installer delivers. Packaging a product
whose first-run experience is about to change means re-testing the installed experience twice.
PR-179 (failure paths) should also land first, because an installed beta on someone else's network
will hit credential and reachability failures immediately — and that is the moment Atlas's honesty
model either earns trust or loses it.

---

*Audited against the live 85-device estate and a fresh workspace. Every measurement in this document
was taken from the running application.*
