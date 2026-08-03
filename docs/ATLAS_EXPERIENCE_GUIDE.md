# The Atlas Experience Guide

**The official UX standard for Atlas.** Established by PR-168, with the Advisor as the reference
implementation. Every Atlas page should evolve toward this.

This is an **information architecture** standard, not a visual style. The colours and spacing here
matter far less than the order.

This guide governs what a **page** says. Its companion, the
[Atlas Workspace Guide](ATLAS_WORKSPACE_GUIDE.md), governs how an operator **moves between** pages —
breadcrumbs, context, related objects, recents, favourites and the command palette.

---

## 1. The premise

Operators open Atlas because they need an answer. Not a report, not a log, not a description of how
Atlas works.

Every page answers three questions, in this order:

1. **What happened?**
2. **Should I worry?**
3. **What should I do next?**

Everything else supports those three answers. Never the reverse.

The measure of success is simple and testable: **a first-time operator understands the answer within
three seconds.** If they must read a plan, expand a section, or decode an engine name first, the
page has failed regardless of how correct it is.

---

## 2. The standard page hierarchy

```
Question           what the operator asked, quoted back once
   ↓
VERDICT            status + the answer + confidence          ← one card
   ↓
KEY FINDINGS       short, scannable, one concept per line    ← one card
   ↓
NEXT ACTIONS       where to go, and why                      ← one card
   ↓
SUPPORTING DETAIL  collapsed <details>, in this order:
     Investigation detail  (plan, entities, per-step outcome)
     Full summary + checks performed
     Why Atlas reached this conclusion  (incl. how it routed)
     Evidence              (citations + freshness)
     Limitations           (open by default — see §6)
     Devices               (actionable objects in the answer)
   ↓
PRISM              presentation, clearly separated from evidence
   ↓
Raw / feedback
```

A page may omit a level. **A page may not reorder one.**

### Why the order is the design

Before PR-168 the Advisor rendered: summary → findings → checks → reasoning → evidence → confidence
→ freshness → recommendations. Every element was correct and the most important one was eighth. The
operator's first screen was a routing chip and a wall of `<h2>`s.

The redesign moved nothing into or out of the page. It changed only what comes first.

---

## 3. The verdict

> Every investigation begins with a verdict. Not evidence. Not engines. Not execution plans.

The verdict card carries exactly four things:

| Element | Source | Rule |
|---|---|---|
| **Status** | a determination Atlas already made | one of the words in §4 — never an internal key |
| **The answer** | the engine's own first sentence | quoted, not paraphrased |
| **Confidence** | the answer's own confidence | shown **once on the page**, here |
| **Framing** | investigation / protocol / scope | operator vocabulary (§5) |

### The honesty rule

**A verdict may only restate a determination Atlas has already made.** The Advisor's status is
derived from the engine's own summary by high-precision keyword match, with negated forms stripped
first, falling back to neutral when the words do not clearly support a judgement.

A page must never compute a health verdict in its presentation layer. If the engine did not
determine health, the honest status is *"Not enough evidence"* or *"Informational"* — and both are
real answers, said plainly.

---

## 4. Status language

Use operational words. These are the sanctioned set:

| Status | Colour | Meaning |
|---|---|---|
| **Healthy** | green | Atlas checked and found no problem |
| **Warning** | amber | a problem is developing |
| **Attention required** | red | a problem exists now |
| **Investigating** | — | work is in progress |
| **Not enough evidence** | grey | Atlas cannot answer — a real answer, not a failure |
| **Informational** | blue | evidence presented, no health judgement made |

**Do not flatten a distinction the engine makes.** The enterprise health engine separates Warning
from Critical; a page that maps both to one status — or worse, lets Warning fall through to
Informational — silently withdraws a signal the operator was given. Before shipping a status
mapping, enumerate every state the engine can emit and check each one lands somewhere deliberate.

**Retired**, because they describe Atlas's bookkeeping rather than the operator's network:

- ~~"Unavailable"~~ · ~~"Not evaluated yet"~~ · ~~"Count only"~~ · ~~"Understood as: …"~~

Replace with the fact: a tile with no health state says **"No health state assessed"**; a tile with
no timestamp says nothing at all rather than filling the space.

### Status must never rest on colour alone

Every status carries a **word**. The coloured dot repeats the state in a second channel; it never
carries it alone.

---

## 5. Operator vocabulary

Atlas's internals are not the operator's problem.

| Don't show | Show |
|---|---|
| "Understood as: Site Health" | **Investigation** · Site health investigation |
| "5 engine(s) · 4 ms" | **Atlas investigated** ✓ Chennai ✓ OSPF ✓ Routing — completed in 4 ms |
| `graph`, `routing`, `path`, `changes` | Devices & interfaces · Routing · Path · Recent changes |
| "intent classification" | (collapsed, under *Why Atlas reached this conclusion*) |

Router decisions, engine names and plan template ids are **audit information**. They belong in the
collapsed detail, where an operator who doubts an answer can check them — not in the headline, where
they compete with the answer.

### Show investigations, not engines

Operators trust visible work — but *"5 engines"* is not visible work, it is an implementation count.
Name the **subjects**: the scope that resolved, the protocol, and what each engine actually examined.

**Every ✓ must correspond to work that happened.** Three ways this row goes wrong, all found in
review of the reference implementation:

- an entity Atlas could **not resolve** listed as if it were examined;
- the **protocol from the question** shown as investigated when no engine read it (asking about
  HSRP does not mean Atlas checked HSRP);
- a plan step that was **skipped or blocked** rendered with a ✓ under "checks performed".

A row that inflates the work is worse than no row: it converts a trust signal into a lie.

### Show identifiers exactly as Atlas holds them

Capitalise a plain site word for reading ("mumbai" → "Mumbai"). Leave anything with a dot, digit or
hyphen alone — title-casing turned `core1.example.net` into `Core1.Example.Net`, a string that
matches no device and cannot be pasted into search or a CLI.

This applies to **every** operator surface, not just the answer. The history list was tagging each
stored conversation with the raw router key, including `unknown` for a question Atlas could not
route.

---

## 6. Details on demand

Supporting information is **collapsed, not deleted**. It stays in the DOM, keyboard-reachable, and
findable by search.

- Collapse: evidence, investigation plans, execution steps, reasoning, raw output, PRISM.
- **Limitations open by default.** An unstated limitation is indistinguishable from a claim. It is
  the one detail block that changes how the answer above should be read.
- A `<summary>` states what is inside *and how much*: "Evidence — 2 artifact(s) cited". A count in
  the summary is often all the operator needed.

**Collapsing is not hiding.** If a page can only be understood by expanding things, the hierarchy is
wrong — fix the hierarchy, do not un-collapse the detail.

### A disclosure must look like one

`<summary>` draws its triangle from `display: list-item`. **Setting `display: flex` on a summary
silently deletes the only affordance telling an operator the section opens** — and any `::marker`
rule you write becomes dead CSS. Use `display: list-item` with `list-style-position: outside` and
space the inner spans with margin. Give it a `:focus-visible` outline; it is a control.

### A summary must promise only what it holds

A disclosure labelled "the full summary" that contains the same sentences already on screen wastes
the one action the operator took. Before writing a `<summary>` label, ask what is inside that is
**not** above it. If the answer is nothing, delete the block or retitle it after its unique content.

---

## 7. Cards

**One card answers one question.** Do not mix concepts.

| Card | Answers |
|---|---|
| Verdict | What happened? Should I worry? |
| Key findings | What specifically? |
| Actions | What next? |
| Supporting detail | Why should I believe this? |

A card that needs two `<h2>`s is two cards.

### Never render the same fact twice

Repetition is the most common failure. Before PR-168 the Advisor showed confidence in two places,
the scope in two, and "Key findings" was a strictly lossy copy of "Evidence" — the same list with
the links and detail removed.

Rules:
- Confidence appears **once**, in the verdict.
- A timestamp appears **once**.
- A summary list and its full form never both render expanded; the summary is promoted, the full
  form is collapsed, and it repeats only when the summary had to truncate.

---

## 8. Visual language

Whitespace separates; borders do not. The only strong border in an answer is the verdict's status
edge — that border is **information** (green / amber / blue / grey), not decoration.

| Concern | Rule |
|---|---|
| Type scale | answer 19px (17px ≤640px) · headings 15px · body inherit · meta 12px · labels 10px uppercase |
| Card padding | 18–20px desktop, 14–15px mobile |
| Rhythm | 6–10px within a group, 14–18px between groups |
| Colour | **tokens only** — `--green`, `--amber-fill`, `--accent`, `--slate` and their `-soft` fills |
| Borders | one 4px status edge per answer; `1px var(--line)` separators inside supporting detail |
| Radius | `999px` for chips, `var(--radius)` for everything else |

### Both themes, always

Atlas ships light, dark and system. The dark theme overrides **backgrounds**, not status
foregrounds — so `color: var(--green)` on a dark soft fill is dark-on-dark. Any component with a
coloured foreground needs an explicit dark override **and** a `body[data-theme="system"]` twin
inside `@media (prefers-color-scheme: dark)`.

Every text/background pair must reach **4.5:1 in both themes**. Measure it; do not assume it. PR-168
had a status chip at 2.84:1 in dark before measurement caught it — on the single most important
element of the page — and a stale-evidence warning at 3.41:1 that a *second* pass caught. When you
add one coloured foreground, grep for **every** rule using that token on a dark surface; they fail
as a family, not one at a time.

**Do not inherit a border you did not choose.** A card carrying an old class can wear a heavier rule
than the verdict beside it. After any restructure, compare computed `border-left-width` across the
page: the strongest rule must be on the most important card.

---

## 9. Interaction rules

- **No inline handlers.** CSP forbids them; behaviour binds by id or class in `atlas.js`.
- **Never imply an action the RBAC would refuse.** A control the user cannot use is not rendered as
  a link.
- **Nothing connects, opens, or changes on render.** Atlas acts when the operator clicks, never
  before.
- **Model output is never markup.** Build text nodes, not `innerHTML`.
- Keep the heading ladder unbroken: `h1 → h2 → h3`, no skipped levels.
- Decorative marks (`✓`, status dots) are `aria-hidden`; the meaning is in the adjacent text.

---

## 9b. Dashboards — the Operational Dashboard Standard

> **Answer first. Context second. Evidence third.**
> A dashboard supports an operator. It does not compete with an answer.

An operator who asks Atlas a question came for an answer. Enterprise context helps them judge that
answer — *is discovery stale? are there open incidents?* — but the moment it occupies more of the
page than the answer, the page has changed subject.

**The measurable rule: the answer must be the tallest element on the page.** Compute it; do not
eyeball it. On the reference implementation the verdict is ~2.4× the dashboard at every breakpoint.

### The Enterprise Summary pattern

One card, not a grid. It carries four things and nothing else:

```
Enterprise status   [🟡 Warning]   Enterprise        updated 02-Aug-2026 21:33 IST
  Discovery 85   Incidents 0   Policy 53%   Identity 85   Routing 119
  ▸ Operational readiness — 1 dimension(s) need attention
```

| Element | Rule |
|---|---|
| Heading | 14px — smaller than the answer's 19px. The weight ordering *is* the design |
| Readiness | one status word from §4, **reused** from the page's existing health determination |
| Scope + updated | once each, on the header row |
| Chips | one per dimension, for scanning |
| Detail | a disclosure (see the progressive pattern below) |

### The Operational Readiness pattern

The readiness word is **read, never computed**. A dashboard maps the health model's states onto the
§4 status words and stops there:

| Health state | Status word |
|---|---|
| `healthy` | Healthy |
| `degraded`, `stale` | Warning |
| `critical` | Attention required |
| `unavailable`, `unknown` | Not enough evidence |

`stale` is a Warning rather than "not enough evidence" because Atlas *can* see the estate — it is
seeing an older version of it, which is a developing operational risk.

**Enumerate every state the model can emit and check each lands somewhere deliberate.** A state with
no mapping falls through to the safest label and silently withdraws a signal — that is exactly how
PR-168 lost the engine's Warning. A test asserts the mapping is total.

Beneath the word, supporting observations in Atlas's own sentences:

```
⚠ Discovery   the last discovery is older than 24h
·  Incidents  no operational-state report exists yet
✓ Identity    healthy across 1 network(s)
```

A **✓ means "checked and fine"**. A dimension Atlas could not assess gets a neutral dot, never a
tick. The overall card is the verdict and is not an observation about itself.

### The Status Chip pattern

Chips are for **scanning**; cards are for reading. A chip is `label · value` on one line, wrapping,
with no fixed height:

- The value is the **shortest honest form**: a percentage from a ratio the model already recorded, a
  count, or `—`. Compute it from the model's own numerator and denominator — never by parsing the
  display text back apart.
- Each chip **links** to the page that owns that dimension.
- State shows on the chip's **edge**, and the value text carries the same fact — colour is never the
  only channel. Border colours must reach **3:1** against the chip surface in both themes (use
  `--amber`, not `--amber-fill`, which is a fill token and measured 2.81:1).
- A dimension with **no verdict gets no colour** — not even the neutral "unknown" styling, which
  reads as "Atlas tried and failed".
- **Never chip a fact the readiness word already states.** "Health · Stale" beside "Warning" is one
  fact, twice, in two vocabularies.

### The Progressive Dashboard pattern

The detail opens **only while there is nothing to compete with**:

```jinja
<details class="ops-detail"{% if not answer %} open{% endif %}>
```

Server-rendered, so it needs no JavaScript and holds with scripting off. The `<summary>` states
whether opening it is worth the operator's time — *"1 dimension(s) need attention"* / *"nothing
flagged"*.

The same reasoning applies to **generic starting actions**: useful on an empty page, competing noise
once the answer has its own "what to do next". They step back into a disclosure rather than
disappearing.

**Collapsing is not removing.** Every metric the cards showed still renders, one compact row each,
inside the disclosure. A test asserts it.

### Adopting this on another page

The presenter is page-agnostic — `founderos_atlas.web.dashboard.summarise()` takes plain card dicts
(`title`, `state`, `chip`, `detail`, `href`) and returns readiness, chips and observations. Import
it; do not re-implement it. Order the cards with the overall assessment first.

## 10. Migration strategy

Advisor is the reference implementation. Other pages adopt this incrementally — a page is not
required to change until it is touched.

**Order of adoption**, easiest and highest-value first:

| Wave | Pages | Why first |
|---|---|---|
| 1 | Advisor ✅, Investigation, Incidents | already produce a verdict-shaped answer |
| 2 | Policy, Prediction, Compass | produce a judgement that is currently buried under method |
| 3 | Signals, Topology, Configuration | dense, exploratory; the verdict is "what changed / what is wrong here" |
| 4 | Evidence, PRISM, Administration | reference surfaces; hierarchy matters least |

**Per-page checklist:**

0. If the page carries a dashboard, apply §9b first — a page whose context outweighs its answer
   cannot be fixed by reordering the answer alone.
1. Identify the page's verdict. If it has none, say so in the sanctioned status words — do not
   invent one.
2. Promote the answer above the method.
3. Move plans, steps, engines and raw output into `<details>`.
4. Add a "what to do next" card with real deep links.
5. Delete every repeated fact.
6. Replace implementation vocabulary using §5.
7. Measure contrast in both themes; add the dark **and** system twins.
8. Pin the new order in a test — as an **order**, not a bag of headings.

**Do not** rewrite a page's engine to fit this guide. If the hierarchy exposes that a page has no
verdict to give, that is a finding about the page, and the honest interim answer is
*"Not enough evidence"*.

---

## 11. What this standard does not permit

- Inventing a status the underlying engine did not determine.
- Removing a capability to make a page tidier. Collapse it instead.
- Hiding a limitation to make an answer look stronger.
- Colour as the only carrier of meaning.
- A "simplification" that costs an operator information they previously had.

---

## Reference implementation

`src/founderos_atlas/web/templates/advisor.html` — hierarchy
`src/founderos_atlas/advisor/presentation.py` — status words, operator vocabulary, findings, context
`src/founderos_atlas/web/dashboard.py` — the operational summary, page-agnostic (§9b)
`src/founderos_atlas/web/static/atlas.css` — the component classes (`verdict-*`, `findings-*`,
`actions-*`, `advisor-detail`, `ops-*`)
`tests/test_advisor.py::test_ask_renders_the_answer_hierarchy` — the order, pinned
`tests/test_advisor.py::test_the_dashboard_is_context_not_the_answer` — the progressive behaviour
`tests/test_operational_summary.py` — the readiness mapping, chips and observations
