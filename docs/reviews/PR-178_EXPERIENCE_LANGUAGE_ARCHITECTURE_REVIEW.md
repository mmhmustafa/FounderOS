# PR-178 — Apply the Experience Language to the Pages That Predate It

**Answers First. Evidence When You Need It.**
*Audit and architecture. No code was modified. Nothing was committed.*

Measured against the running application at `eeb2e7e`: the live 16-profile / 865-device estate
and a pristine workspace, at 375 / 768 / 1440 / 1920 px.

---

## 1. Executive diagnosis

### Atlas already has an Experience Language. It has one adopter.

`templates/_disclosure.html` is a complete, documented component library — ten macros covering
exactly what this PR asks for:

```
page_summary        the one-paragraph conclusion a page leads with — visible at EVERY level
primary_action      the single dominant action
secondary_actions   inline from Detailed, collapsed at Simple
advanced_details    open only at Expert
evidence_disclosure provenance, open at Expert
warning_disclosure  always visible, never collapsed
empty_state         what is absent, why, and the one action that changes it
error_state         honest, with the correlation id
technical_metadata  ids, hashes, versions
contextual_help     collapsed at every level
```

Its contract is already the right one: *"content is NEVER removed — a section below the current
level renders as a collapsed, labelled `<details>` the user can always open."*

**Exactly one template imports it** (`mission.html`), using two macros. **Eight of the ten have
zero call sites anywhere in the product.** The six pages in scope hand-roll their own
disclosures instead.

The consequence is measurable. On `/policy`, moving the topbar Detail control
Simple → Detailed → Expert changes open disclosures from **0 → 1 → 2 out of 52**. Atlas ships a
density control that does almost nothing on its densest page, because 50 of those 52 disclosures
are level-blind.

**PR-178 is therefore an adoption exercise, not a redesign.** That is a far smaller and safer PR
than the brief assumes, and it is the strongest possible answer to "reuse before creating".

### A correction to PR-175's measurements

PR-175's word counts included text inside collapsed `<details>`. Measured as an operator
actually meets them (1440×900, live estate):

| Page | Visible words | Total (incl. collapsed) | PR-175 said | Words before first task |
|---|---|---|---|---|
| Policy | **773** | 3,349 | 3,420 | 62 |
| Investigate | **409** | 1,440 | 1,429 | 56 |
| Evidence | 1,068 | 1,127 | 1,092 | 48 |
| Changes | 136 | 188 | 2,341 † | 193 |
| Timeline | 1,196 | 1,264 | — | 146 |
| Configuration | 858 | 1,004 | — | 93 |

† Changes reads 136 words on this estate because it has nothing to show — see §5.

"1,429 words before the operator meaningfully uses the tool" is not what Investigate does: its
search box sits 56 words in, above the fold. The real defects are different and sharper:

1. **Ordering.** Policy opens with an *Operational priorities* table and 12 tiles before any
   verdict. Changes puts eight zeros above the sentence that makes them honest.
2. **Volume in the row region, not the prose.** Policy renders 523 links and a 50-row table,
   5,130 px tall — 7.3 screens at 375 px. ~95 % of its control count is the per-row action
   menu, repeated 50 times.
3. **Noise.** Timeline's visible 50 rows are **42 annotation records** against 5 discoveries —
   including the display-level preference changes I made minutes earlier — while `/audit`
   already exists for exactly those.
4. **Zeros that were never measured.** All four deferred defects reproduce.

---

## 2. Before-state measurements

| Metric | Policy | Changes | Timeline | Evidence | Config | Investigate |
|---|---|---|---|---|---|---|
| Visible words | 773 | 136 | 1,196 | 1,068 | 858 | 409 |
| Words before task | 62 | 193 | 146 | 48 | 93 | 56 |
| Task depth (px) | 157 | 754 | 527 | 301 | 689 | 443 |
| Task above fold | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Visible tiles | 12 | 8 | 5 | 10 | 6 | 0 |
| Visible controls | 167 | 6 | 61 | 279 | 209 | 26 |
| Links | 523 | 5 | 68 | 116 | 104 | 9 |
| Tables (rows) | 4 (5/12/50/1) | 0 | 2 (50/5) | 2 (50/5) | 1 (50) | 0 |
| `<details>` (open) | 52 (0) | 2 (0) | 2 (0) | 2 (0) | 1 (0) | 19 (0) |
| Page height | 5,130 px | 900 px | 5,413 px | 5,810 px | 3,650 px | 2,534 px |

**Reference pages.** Advisor: 874 visible words, tool at 315 px, 29 disclosures with 2 open, and
the pattern this PR should copy — *question → answer → "Why Atlas reached this conclusion" →
"Evidence — 2 artifact(s) cited" → "Limitations — what Atlas could not determine"*. Home: 256
visible words, verdict-led, already the calmest page in the product.

**Narrow screen.** No horizontal overflow at 375 px anywhere (`scrollWidth == 375`); tables do
not overflow their containers. That strength is intact and must stay intact.

---

## 3. Page-purpose matrix

| Page | The ONE job | Operator's question | Leads with | Primary action |
|---|---|---|---|---|
| **Policy** | Judge configurations against policy | "Are my configurations compliant, and what needs attention?" | **Verdict** | Review failures |
| **Changes** | Detect and triage differences between runs | "What changed, and does it matter?" | **Basis + delta** (no verdict — nothing here is judged) | Review high severity |
| **Timeline** | Narrate what happened, when, and who did it | "What happened yesterday?" | **Chronology** | Apply filters (narrow time) |
| **Evidence** | Prove what Atlas actually observed | "Did Atlas get the bytes, and can I find them?" | **Coverage, then search** | The search box |
| **Configuration** | Find and inspect remembered configurations | "Find BGP config / compare this device" | **Search** | The search box |
| **Investigate** | Answer a connectivity question from evidence | "Why can't A reach B?" | **Tool** when empty, **verdict** when answered | Investigate |

**Only two pages legitimately earn a verdict**: Policy (it judges) and Investigate (it concludes).
Forcing one onto Changes, Timeline, Evidence or Configuration would invent a judgement Atlas
never made — the brief's own warning, and the audit confirms it.

---

## 4. Policy redesign architecture

**Today:** h1 → 53-word feature list → *Operational priorities* card (4 tiles + a 5-row themes
table) → 8 status tiles → the 40-word score-derivation sentence → trend card → heatmap →
*Policy Results* → 13-field filter form → 50-row table. The headline number and the sentence
that qualifies it are separated by eight tiles.

**Recommended order:**

1. **Answer band** — status chip, one-sentence verdict built from values already in context,
   **with the score-derivation sentence inside the band, adjacent to the number it qualifies**.
2. **Basis line** — `Configuration verdicts · <scope> · evaluated <when> · <pack> v<version>`.
3. **Three priority facts** (New regressions / Fresh confirmed / Verify evidence first) —
   linked, not tiled.
4. **Seven status buckets as one row of linked chips**, each to its existing `?status=` filter.
   All seven survive: `explorer.py` documents why they are distinct.
5. **Filter chips + collapsed filters + the results table** — the instrument.
6. **Supporting detail** — heatmap, trend, themes, governance, packs.
7. **About** — the feature list, the recording-mechanism note, the design note.

**Two corrections the audit forced.** The four bucket-definition sentences ("The engine reached
Unknown and recorded WHICH evidence is missing", etc.) exist **only as `title=` tooltips** —
invisible on touch, unreachable by keyboard. They carry the exclusion semantics of the headline
denominator and must become visible text. And `p.author` / `p.categories` render nowhere except
the Installed Policy Packs card, so that card cannot be removed without moving them to
`technical_metadata` in the same commit.

**Budget:** ≤120 words above the results table. Page total stays near 3,349 — the bulk is
hostname-interpolated row labels inside collapsed menus, which is a shared-component question,
not a Policy question.

---

## 5. Changes redesign architecture

**Today, on the live estate:** eight tiles reading `Changes 0 · Topology 0 · Configuration 0 ·
Operational 0 · High severity 0 · Acknowledged 0 · Incident-linked 0 · Suppressed 0`, then
*Compare Two Runs*, then "0 change(s) match", and only at the very bottom the sentence that
explains all of it: *"Run a discovery at least twice for a profile to see what changed
overnight."*

Every network here has been discovered once. **Nothing was measured as zero — nothing was
compared.** The page has the right words; they are simply last.

**Recommended order:** basis line naming the two runs compared → one summary sentence
(`N difference(s) — M high severity, K unacknowledged`) → six linked filter chips replacing six
tiles → filter chips + collapsed filters → the table. *Compare Two Runs* moves to Supporting
detail: it compares any archived pair, while the everyday question is the last two runs.

**Blocker folded in:** `total`, `high`, `acknowledged`, `suppressed` and `incident_correlated`
are **cross-kind aggregates** over three reports. If configuration was not compared but topology
was, a bare integer silently omits a whole kind. No cross-kind number may render as a plain
integer unless all three kinds were measured; otherwise it carries its reason, and the basis
line names which kinds were compared.

**Budget:** ≤90 words above the table.

---

## 6. Timeline redesign architecture

**Today:** five tiles, a 47-word intro, then 649 events paginated 50 at a time — of which **42
of the first 50 are `annotation` rows**. Twenty-four distinct audit categories all render under
the single visible label "annotation", so the column cannot even distinguish them.

**Recommended:** basis line (`Newest event <when> · N events across 8 sources · <scope>`) → two
tiles, not five (Configuration changes, Discoveries — the other three are inventory, not
chronology, and belong to Configuration and Evidence) → **default view = operator-meaningful
events**, with system/audit events behind one counted disclosure → day grouping (`group_by_day`
already ships and `/configuration` already uses it) → column presets (Timeline is the only major
filtered table that has not adopted the shipped `data-columns` engine).

**Two blockers folded in.** (1) The proposed discriminator does not exist: `_event()` has **no
`source` parameter**, and `actor=` is passed in **exactly one** branch — the audit branch — so
`actor is None` for every configuration, discovery, incident and prediction event. Applied
literally, the "operator-meaningful" view would hide the entire chronology. The class must be
computed explicitly in the audit branch and carried on the record; never derived from an absent
key. (2) The honesty clause "N system events hidden" must be counted over the **same filtered
population** as the result line, or the two halves of the sentence describe different sets.

**Nothing is deleted.** `/audit` keeps the append-only record, every category, and CSV export.

**Budget:** ≤70 words above the table.

---

## 7. Evidence redesign architecture

Evidence is the product's strongest trust surface and must not be simplified into vagueness. Its
coverage number is **already honest** — `completeness_percent` returns `None`, never 0 or 100,
when it cannot be computed.

**Recommended:** basis line carrying **freshness** (which the page cannot state today) → the
coverage answer: completeness, gaps (`failed + unsupported`), and devices with no configuration
→ search + filters + the device table. The four ratio pairs render as ratios, not eight loose
numbers.

**Preserved without exception:** raw evidence, provenance, masking/redaction, export, saved
filters (server-rendered), bundles, per-device actions, the resolution centre's
coverage-with-denominators.

**Moved:** the 7-number "Enterprise Memory — System Details" storage drawer to its own deferred
surface — the single highest-value subtraction in the PR. **Blocker folded in:** freshness must
be computed from the unfiltered session records, not from the filtered device rows, because the
summary's pinned contract is *"The summary above always describes the whole discovery"*.

**Two inverse defects fix in the same pass:** a genuinely measured zero currently renders as an
em-dash (`{{ d.empty_responses or '—' }}`), and 51 bulk-export checkboxes render for users
without the export permission.

**Budget:** ≤80 words before the search box.

---

## 8. Configuration redesign architecture

The real job is **browse → inspect**. No verdict belongs here.

**Recommended:** basis line (`N devices remembered · M versions · oldest memory <when>`) → two
operational facts replacing six tiles (devices that have ever changed; devices still at
baseline) → the search box, with the **empty-FILTER state split from the empty-STORE state**
(today a zero-result search hides the search box itself) → the device table with `versions`
promoted into the simple column preset.

The Change Timeline — up to 60 separate `<table>` elements, one per calendar day — collapses to
one recency line plus a disclosure. **Blocker folded in:** that link must keep its
`?current=&previous=` version pair; `/timeline`'s configuration rows link to a bare device page,
so re-pointing it would silently destroy the one-click diff.

**Capability blocker:** configuration-memory statistics (`unique_configurations`,
`deduplicated_observations`, devices, versions) render **only** on `/configuration` and
`/timeline`. Deleting both tile rows removes them from the product entirely — they need the same
deferred-surface treatment as the Evidence drawer, landing in the same commit.

**Budget:** ≤60 words before the search box.

---

## 9. Investigate redesign architecture

PR-175's "essay before the tool" does not reproduce: the form is 56 words in and above the fold.
The real defects are **order and duplication inside the result**.

**Recommended:** no result → the 3-control form (source, destination, submit), advanced intent
fields staying in their existing disclosure. No devices → `empty_state` **replaces** the form;
today a fully enabled 9-control form that cannot possibly work renders first. With a result →
answer band whose headline is `investigation.failure_summary`, which today renders *fourth*
inside the card. Freshness, provenance and snapshot id are already loaded and rendered nowhere.

**Honesty fix:** `unknown` currently maps to a badge painted **red**, while the same page's hop
rows paint unknown slate. Unknown is not failure.

**Duplication:** the "Validate `<device>`" story steps repeat the hop table verbatim.

---

## 10. Home tile cleanup

Confirmed exactly: `Devices 85`, `Canonical devices 85`, `Observations 85` — **one number, three
labels, two of them internal vocabulary** — plus `Merged devices 0`.

- `Canonical devices` → drop (duplicate of Devices).
- `Observations` → drop from Home; it is an Evidence concept.
- `Merged devices 0` → this is a *measured* zero (identity resolution ran and merged nothing) and
  should say so, or move to the identity surface.
- Keep `Networks`, `Devices`, `Relationships`, `Configurations`.

No other Home change. Home is the reference implementation, not a target.

---

## 11. Misleading-zero remediation model

**One rule: every number is a measurement, or it is not rendered as a number.**

Atlas already owns the vocabulary — `health/model.py` distinguishes `unavailable` ("deliberate
absence — stated, never counted as a pass") from `unknown` ("tried and could not reach a
verdict"), and `dashboard.py` already maps both to the operator words **"Not enough evidence"**
with a tone that cannot render green.

| Case | Rendering |
|---|---|
| **Measured** | The number, plainly. A measured `0` prints as `0` — never an em-dash. |
| **Never measured** (`unavailable`) | "Not compared" / "Not measured" + the reason, in slate. Never the digit 0. |
| **Attempted, unjudgeable** (`unknown`) | "Not enough evidence" + the counts that explain it. |
| **Measured without a defensible denominator** | The shipped string `"{value} observed · denominator unavailable"`. |

**Blocker folded in:** Policy must branch on `overall.total == 0` **first**. With no evaluations
at all, "0 of 0 results could be judged" asserts an evaluation attempt that never happened —
the mirror-image dishonesty. Only when `total > 0 and judged == 0` is "Not enough evidence"
correct.

Applied to the four deferred defects, all verified live on a fresh workspace:

- **Policy** — `"No active failure or warning requires attention. Compliance score 0% …"`
  becomes *"Not scored — no configurations have been evaluated in this scope yet."* The
  reassurance sentence must not render when nothing was assessed.
- **Changes** — eight zeros become *"Not compared — change detection needs two collections in
  this scope."*
- **Timeline** — zero tiles become "Not measured" with their reason.
- **Paths / Predict** — `"0 canonical device(s) from 0 contributing profile(s)"` becomes the
  empty state that already exists further down the page.

Fix the **rendering**, not `posture_score` itself: its arithmetic is pinned by two suites on
`judged > 0` fixtures. If the engine's `score` is changed to `None`, `PolicyReport.score` and
`trend.record()` must both be made None-safe in the same commit or `/policy` will 500.

---

## 12. Shared Experience Language components

Six components, five of which already exist:

| Component | Status | Used by |
|---|---|---|
| `answer_band` | **Extract** from `advisor.html:140-192` + the shipped `.verdict-card` / `.verdict-chip` / `.verdict-answer` CSS (already dark-theme and mobile audited) | Policy, Investigate, Advisor |
| `_fmt.measure()` | **New macro in the existing `_fmt.html`** — the honest-number renderer of §11 | all six |
| `_fmt.basis()` | **New macro in the same file** — one provenance line per page | all six |
| `d.contextual_help()` | **Exists, zero call sites** — the sink for all C-class prose | all six |
| `d.empty_state()` | **Exists, one call site** — replaces the instrument, never follows it | Changes, Timeline, Paths, Configuration |
| `filter_chips()` | **Extract** the shipped markup from `evidence_index.html:128-141` | Policy, Changes, Timeline, Evidence, Configuration |

**Blocker folded in:** `answer_band`'s tone must **not** come from `readiness_for()`. That
function knows six *health* states and returns `("Not enough evidence", "unknown")` for anything
else — so Policy's `pass`/`fail` buckets would all render as "Not enough evidence". Tone comes
from the vocabulary that owns the verdict: the shipped `status-chip-*` mapping for Policy, the
`hop-badge-*` mapping for Investigate.

---

## 13. Progressive-disclosure model

**Four bands, fixed order on every page:**

1. **ANSWER** — always visible at every level, never inside a `<details>`. Either an
   `answer_band` (pages that judge) or `basis()` + one `page_summary` sentence.
2. **INSTRUMENT** — the page's own tool: search box, form, table, chronology. Its *filter bar*
   may collapse, with `filter_chips()` above it so collapsed never means hidden state.
3. **SUPPORTING** — one card of counted disclosures. Reference material: heatmaps, trends,
   packs, storage, compare tools, method prose.
4. **ABOUT** — one `contextual_help()` at the foot holding all C-class prose.

**Display level governs what OPENS, never what EXISTS.** The answer-first structure is identical
at simple, detailed and expert. This is non-negotiable: `migrations.py` stamps
`display_level_default: expert` on any workspace that had prior activity at upgrade, so tuning
only the `simple` branch would leave upgraded installations byte-identical. *(This particular
workspace has no `ux-defaults.json` and honestly reads `simple` — the stamp applies to upgraded
installations, not to it.)*

**Blocker folded in:** Band 3 must use disclosures that are **collapsed at every level**, not
`advanced_details`/`evidence_disclosure`/`technical_metadata` — all three open at Expert, which
is precisely the population that needs the calm. The count in each summary does the deciding.

**Two overrides outrank the bands:**

- **Never collapse a claim about what is on screen** — the score-derivation sentence, "An empty
  response is not a failure", masked-line and truncation notices, "N suppressed change(s)
  hidden", the configuration-vs-state note, and Timeline's new "N system events hidden".
- **Never collapse a POST action form.** Only GET filter forms sit behind a Filters summary.

---

## 14. Filter and action hierarchy

**Always visible:** the search input; the active-filter chips; the result-count line.
**Collapsed by default at Simple:** the full filter form (the pattern six templates already
carry, pinned character-for-character by `test_table_adoption`).
**Supporting:** bulk operations, governance controls, compare tools, saved-filter management.

**One `btn btn-primary` inside `<main>` per page, at every level.** The rule already exists and
is enforced on Home; extending it to the six is the smallest possible consistency win.

**Preserved:** every filter stays URL-addressable; saved filters keep working; `source` on
Evidence is a live URL-addressable filter and must be *routed into the form*, never removed.

---

## 15. Configuration-versus-state explanation

Today `/policy` is silent on this. "Compliant"/"Non-compliant" never appear; "Healthy"/"Degraded"
never appear; the card is headed "Operational priorities"; the Governance table has a column
headed "State" meaning Draft/Active/Retired; and "Failed" is a term in *both* canonical
vocabularies. The one sentence that draws the line renders only when telemetry facts exist.

**Recommendation:** one reusable sentence, stated unconditionally on every page that shows
either vocabulary, reusing the wording `validation.py` already carries — *configuration says
Compliant, state says Healthy, and neither implies the other*. One sentence, one place, six
pages.

**Rule:** the verdict palette (`pass`/`warning`/`failed`) belongs **only** to pages that judge.
Configuration change severity ranks consequence, not compliance, and must not borrow it.

---

## 16–18. Responsive, accessibility, performance

**Responsive.** No horizontal overflow at any width today; the changes are order and disclosure,
which do not disturb it. Policy at 375 px is 7.3 screens — collapsing Band 3 and adopting column
presets is the fix, not new breakpoints.

**Accessibility.** `<details>`/`<summary>` is keyboard-operable natively. Two genuine gains:
Policy's four bucket-definition sentences stop being tooltip-only, and Evidence's dead checkbox
column stops consuming ~19 % of the page's tab stops. Every count in a summary must be real
text. Nothing becomes hover-only.

**Performance.** Every opening value is already in the template context or is one comprehension
over an already-materialised list. Three genuine *subtractions* exist (a dead `summarize()` pass
on Policy, an unconditional telemetry query, an uncached enterprise-context build on Paths).
**A `<details>` is not a performance win** — only not computing is. This PR must not be reported
as a speed-up it did not deliver, and must not disturb PR-176's Policy budgets.

---

## 19. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Hiding a system event class that does not exist on the record blanks the Timeline | **Blocker** | Compute the class in the audit branch; never derive from an absent key |
| R2 | Cross-kind Changes counters render as whole truths when one kind was not compared | **Blocker** | No bare integer unless all three kinds measured |
| R3 | "Not enough evidence" asserted where nothing was ever evaluated | **Blocker** | Branch on `total == 0` first |
| R4 | Tone drawn from `readiness_for()` renders every Policy verdict as unknown | **Blocker** | Tone from the owning vocabulary |
| R5 | Storage statistics become unreachable when tiles are deleted | Major | Deferred surface lands in the same commit |
| R6 | Band 3 opens at Expert — the population that needs calm | Major | Collapsed at every level |
| R7 | Evidence freshness computed from filtered rows contradicts the pinned summary contract | Major | Compute from unfiltered session records |
| R8 | `{% import %}` without `with context` silently collapses a whole page | Medium | Test the `with context` form |
| R9 | Score returning `None` 500s the trend recorder | Medium | None-safe path in the same commit |
| R10 | Collapsing reported as a speed-up | Low | State it explicitly in the handover |

---

## 20. Test strategy

1. **Zero-evidence honesty** — no page renders `0%`, `0`, or an em-dash for a value never
   measured; and a genuinely measured zero still renders `0`. Both directions.
2. **Policy branches** — `total == 0` vs `total > 0 and judged == 0` produce different, honest
   strings; the score-derivation sentence is inside the answer band and never collapsed.
3. **One primary action** — exactly one `btn btn-primary` in `<main>` per page, at all three
   display levels.
4. **Structure is level-invariant** — the same sections exist at simple, detailed and expert;
   only `open` differs.
5. **Nothing unreachable** — every filter, bulk action, export, saved filter, raw-evidence path
   and governance control still reachable; every current route still 200.
6. **Timeline** — the operator view still renders non-audit events; the hidden count matches the
   filtered population; `/audit` still carries every category.
7. **Changes** — a partial comparison never renders a bare cross-kind integer.
8. **Evidence** — the summary still describes the whole discovery, not the filter.
9. **Configuration** — storage statistics reachable; the version-pair diff link intact.
10. **Vocabulary** — configuration and state words stay distinct; unknown is slate, never green,
    never red.
11. **Imports** — every `_disclosure.html` import uses `with context`.
12. **Home** — one estate number, one label.
13. **No horizontal overflow** at 375/768/1440/1920.
14. **Keyboard** — every disclosure operable; no meaning lives only in `title=`.
15. **Policy performance** stays inside PR-176 budgets; full suite green (3,018 baseline).

---

## 21. Browser-validation strategy

Per page, on both the populated estate and a fresh workspace, at all four widths: capture
visible words, words before first task, task depth, control count, tile count, and the first
viewport's content — before and after. Then run the six operator tasks from the brief ("Are my
configurations compliant?", "What changed on Mumbai?", "What happened yesterday?", "Show me
exactly what Atlas saw", "Find BGP configuration", "Why can't A reach B?") and confirm a
first-time operator can identify where to answer each. Metrics prove usability; they are not the
goal.

---

## 22. Recommended PR scope

**In scope:** the six components of §12; adoption of the four bands across the six pages; the
zero-state remediation of §11 including its three carried Python fixes (Policy score branch,
Changes per-kind flags, Timeline event class); the Home tile cleanup; the honesty fixes that
ride along (unknown-as-red on Paths, measured-zero-as-em-dash on Evidence, tooltip-only
semantics on Policy, unaudited config export, permission-gated export column); and the deferred
surfaces for Evidence and Configuration storage statistics.

**Sequenced separately, not absorbed:** the shared per-row action menu (~95 % of Policy's and
Changes' control counts) — it is a shared component used by many pages and deserves its own PR.

---

## 23. Non-goals

No navigation redesign; no change to PR-177's progressive navigation; no PR-179 failure-path or
PR-180 hygiene work; no merging of Discoveries and Timeline; no new networking, vendor, AI or
history capability; no packaging, licensing, updates or branding; no SPA; **no change to
reasoning semantics**; no change to `per_page` (shared by four surfaces).

---

## 24. Success criteria

All six pages lead with their answer or their tool; no misleading zero anywhere; explanatory
essays behind About; exactly one primary action per page; every capability still reachable; raw
evidence still reachable; unknown never green; configuration and state vocabularies distinct;
Policy still fast; responsive and accessibility strengths intact; no new backend computation.

---

## 25. Approved implementation plan

**Step 1 — Components, no page changes.** Add `_fmt.measure()` and `_fmt.basis()`; extract
`answer_band` from Advisor's markup verbatim; extract `filter_chips()` byte-compatibly from
Evidence. Unit-test each. Nothing user-visible changes yet.

**Step 2 — Zero-state honesty first, page by page.** Policy's two-branch score (with the
`PolicyReport.score` and `trend.record()` None-safe paths in the same commit); Changes' per-kind
measured flags; Timeline's explicit event class; Paths/Predict's empty state. Land tests 1, 2, 7
before any layout moves. *This is the trust fix and it ships even if the rest slips.*

**Step 3 — Policy.** Adopt the four bands. Promote the bucket sentences out of `title=`. Move
the packs card's `author`/`categories` into `technical_metadata` in the same commit.

**Step 4 — Investigate.** Reorder the result (failure summary first), replace the form with the
empty state when there are no devices, fix unknown-as-red, delete the duplicated story steps.

**Step 5 — Changes and Timeline.** Basis + summary + linked chips; day grouping; column presets;
the system/operator split with its honest hidden-count clause.

**Step 6 — Evidence and Configuration.** Coverage-then-search; split empty-filter from
empty-store; the two deferred storage surfaces, each landing with the tiles it replaces; the
export permission gate and audit fix.

**Step 7 — Home tiles**, then full validation: the suite, the four widths, both workspaces, the
six operator tasks, and a PR-176 performance re-check.

**Handover must state:** before/after measurements per page; that every capability remains
reachable (enumerated); which zeros changed and why each is honest; confirmation that structure
does not vary by display level; and an explicit statement that collapsing did not make anything
faster.

---

## Answers to the fourteen architectural questions

1. **Primary jobs** — §3.
2. **Which need a verdict** — Policy and Investigate only.
3. **Which lead with a tool/search** — Configuration and Evidence (search), Investigate when
   empty, Changes (basis + delta), Timeline (chronology).
4. **Permanently visible** — the answer/basis line, the instrument, active filter chips, result
   counts, and every claim about what is on screen.
5. **Progressively disclosed** — reference material, method prose, bulk/governance controls,
   storage statistics, system events, secondary columns.
6. **Reusable components** — six, five of which already exist (§12).
7. **Misleading zeros** — the four-case rule in §11.
8. **Configuration vs state** — one reusable sentence, stated unconditionally, reusing
   `validation.py`'s wording (§15).
9. **Prose removable from the initial path** — most of it, but the honest payoff is modest
   (Timeline's intro is 3.8 % of its words). The win is ordering and rows, not prose.
10. **Filter priority** — §14.
11. **Equal weight that should not be** — 12 Policy tiles equal to each other and to the verdict;
    two identically-labelled disclosures on Changes; "Discovery Wizard" vs "Run Discovery";
    every Timeline event class rendered as one badge.
12. **Achievable through presentation alone?** — Yes for layout. Three small Python changes are
    required for *honesty* (Policy branch, Changes per-kind flags, Timeline event class); each
    removes a falsehood rather than adding computation.
13. **Information that belongs elsewhere** — Timeline's audit rows (→ `/audit`, already exists);
    Home's `Observations` (→ Evidence); Timeline's inventory tiles (→ Configuration/Evidence).
    Move the information; do not merge the pages.
14. **C → B per page** — Policy: verdict-first + honest zero. Changes: basis-first + honest
    "not compared". Timeline: operator/system split + day grouping. Evidence: coverage-then-
    search + storage drawer deferred. Configuration: search-first + split empty states.
    Investigate: answer-first + empty state replacing the dead form.

---

*Evidence base: the running application at `eeb2e7e` on the live 865-device estate and a
pristine workspace, measured at four widths; a 12-agent read-only code audit whose synthesis was
put through an adversarial data-honesty pass that returned **broken** with six blockers — every
one of which is folded into this document as an amendment, and the three most load-bearing of
which I verified myself in the source. No repository file was modified.*
