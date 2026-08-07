# PR-174 — Topology renders a blank canvas — Root Cause Analysis & Implementation Plan

**Status:** IMPLEMENTED (all five steps plus development-mode viewer diagnostics; uncommitted).
Live results on the same estate: bounding box 78,783 → 5,427; site ring 39,253 → 3,403 max;
0 → 23 nodes in the viewport on the Logical layout; zero diagnostic violations under `?diag=1`.
**Base:** `71de3a4`. **Reproduced live** on the `19onlyAI` scope (66 devices / 69 links / 21 sites).

> **See also PR-174.1** (`PR-174.1_TOPOLOGY_WHEEL_ZOOM.md`): the coarse wheel zoom the fixed
> viewport made *observable* is an unrelated, older regression — `wheelSensitivity: 0.15`
> deleted by `096f630` — restored there. Adjacent symptoms, unrelated causes.

---

## Verdict first

**The layout is the only defect. Every stage downstream of it is behaving correctly over a
genuinely broken input.**

`renderSiteOvalsGrid()`'s Fruchterman–Reingold pass applies **repulsion between all 210 site pairs
and attraction only between site pairs joined by a cross-site link. This estate has zero cross-site
links, so the attraction term never executes once.** 260 iterations of unopposed mutual repulsion
inflate the seeded site ring from radius 3,150 to **39,253** — a 12.5× uniform expansion with the
seed circle's angles preserved exactly, which is the signature of pure radial repulsion.

The resulting bounding box is **78,783 × 78,384**. Everything after that is a correct response to
it: `cy.fit()` computes a fit-zoom of 8.1×10⁻³, the readable floor (0.86) overrides it, the camera
centres on the bounding-box centre — which is **the empty hole in the middle of the ring** — and at
0.86 zoom the viewport spans 1.87% of the bounding box, **38,732 units from the nearest node**.
Zero of 147 nodes are in frame. The minimap is a faithful thumbnail of the true extent, so the ring
of site ovals correctly renders as a speck.

**Not at fault, verified individually:** node coordinates are all finite (0 non-finite); the
intra-site layout is correct (~188-unit device spacing); `boundingBox()` is accurate; `cy.fit()` is
correct; the minimap/export `viewBox` maths is correct; there is **no viewport persistence** at all
(only the view/layout *selects* persist, and localStorage is empty).

**Interim workaround for the operator:** switch **Layout → Force**. Measured live: bounding box
3,678 × 2,743, nodes render normally. Only *Logical (sites & tiers)* is affected.

---

## 1. Evidence (all measured in the live page, not inferred)

### 1.1 The camera is pointed at empty space

| Measurement | Value |
|---|---|
| Nodes in viewport | **0 of 147** |
| Camera centre | (0, −238) |
| Distance to nearest node | **38,732** |
| Zoom | 0.86 (= `READABLE_DEVICE_ZOOM`) |
| Zoom `fit()` actually wanted | 8.10 × 10⁻³ |
| Viewport coverage of bbox | **1.87%** |
| Bounding box | 78,783 × 78,384 |
| Non-finite coordinates | **0** |

### 1.2 Node composition and geometry

147 nodes = 66 `discovered` + 60 `observed` (the unresolved BGP peers) + 21 `sitehull`.
**Every node lies 10k–40k from the origin; none is within 10k.** The 21 hulls sit on a perfect
circle of radius ≈39,251 at exactly 360/21 = 17.14° spacing:

```
ahmedabad   (     0, -39253)   coimbatore (39143,  -2933)
bengaluru   ( 11570, -37509)   delhi      (38269,   8735)
bhubaneswar ( 22112, -32432)   guwahati   (33994,  19626)
chandigarh  ( 30689, -24474)   …21 sites, angles exactly preserved
```

Local device spacing inside each oval is ~188 units — **the intra-site layout is healthy.** Only
the ring is wrong.

### 1.3 The force pass, measured

| Quantity | Value | Source |
|---|---|---|
| Sites (`n`) | 21 | live |
| Seed radius `R0 = max(700, 150n)` | **3,150** | `topology.html:2437` |
| Average oval max-radius | 337 | live |
| `k` = avg × 2.4 | **810** | `:2471–2472` |
| `temp0` = k × 2.2 | **1,781** | `:2473` |
| Cumulative drift the schedule permits (Σ temp over 260 iters @ ×0.972) | **63,578** | computed |
| Observed ring radius | **39,253** | live |
| Inflation | **12.5×** (drift 36,103 ≈ 57% of the ceiling) | computed |

### 1.4 The decisive measurement — attraction never fires

Using the page's **real** `siteView.membership` (not a reconstruction):

| Measurement | Value |
|---|---|
| Site groups | 21 |
| `__none__` group present | **no** — every node has a site |
| Total site pairs | 210 |
| **Pairs with a cross-site link (`W[i][j] > 0`)** | **0** |
| **Cross-site edges** | **0 of 69** |

All 69 BGP links are **intra-site**: each unresolved peer node is a member of the same site as the
device that peers with it. So in the inner loop at `topology.html:2483`:

```js
const w = W[i][blocks[j].idx] || 0;
if (w) { /* attraction — NEVER ENTERED */ }
```

…the guard is false for all 210 pairs, on every one of the 260 iterations. What remains is:

```js
const rep = (k * k) / d;    // applied to all 210 pairs, unopposed
```

Classic Fruchterman–Reingold confines the layout to an explicit `W × L` frame and clamps every
position into it each iteration. **This implementation has no frame and no gravity** — the cooling
schedule is the only thing bounding the drift, and it permits 63,578 units of it.

### 1.5 Why "after the latest discovery"

The explosion scales with site count: more sites → more repelling pairs → each oval saturates the
per-iteration `temp` cap for more of the run, and the seed ring `150n` starts wider. At 21 resolved
sites the drift saturates. This is a threshold that the estate has now crossed, not a regression in
new code — **the defect has been latent in `renderSiteOvalsGrid()` and is exposed by any estate
whose sites have no cross-site links**.

### 1.6 Components cleared by direct measurement

| Component | Verdict | Evidence |
|---|---|---|
| Layout output — intra-site | **Correct** | ~188-unit spacing, coherent blocks |
| Layout output — site ring | **ROOT CAUSE** | §1.3, §1.4 |
| Node coordinates | Correct | 0 non-finite of 147 |
| Bounding-box calculation | Correct | matches node extremes exactly |
| `cy.fit()` | Correct | computes 8.1e-3 for a 78k box in a 1.4k viewport |
| Camera transform | Correct **given its input** | but see D2 below |
| Viewport persistence | **Not involved** | no pan/zoom persistence exists; localStorage empty |
| Minimap / export scaling | Correct | `viewBox` = true bbox; speck is faithful |

---

## 2. Root cause

> **D1 (root cause).** In `renderSiteOvalsGrid()` the Fruchterman–Reingold pass has **no bounding
> frame and no gravity term**. Its only inward force is pairwise attraction gated on a cross-site
> link count that is **zero for every pair in this estate**, so 260 iterations of unopposed
> repulsion inflate the site ring 12.5× to a 78,783-unit bounding box.

There is a second, independent defect that the same screenshot would have hidden:

> **D2 (latent, must also be fixed).** `applyReadableViewport()` responds to *fit-zoom < readable
> floor* by `cy.zoom(floor)` + `cy.center(elements)`. Centring on the **bounding-box centre** of a
> ring-shaped layout aims the camera at the hole in the middle. Fixing D1 shrinks the ring but does
> **not** eliminate this: any layout that leaves the centroid empty can still land the operator on
> a blank canvas. **The viewport must never come to rest with zero nodes in frame.**

---

## 3. Approved implementation plan

**Scope:** `src/founderos_atlas/visualization/templates/topology.html` only. No Python, no
collectors, no graph construction, no other layout.

### Step 1 — Bound the force pass (fixes D1)

In `renderSiteOvalsGrid()`, before the iteration loop, compute an explicit frame from the ovals'
own geometry — the area they actually need, not an arbitrary constant:

```
area  = Σ (2·rx_i · 2·ry_i) · SPREAD        // SPREAD ≈ 4, room to breathe
half  = sqrt(area) / 2                       // half-width of a square frame
```

Then, inside the loop, after applying the displacement to each block:

1. **Gravity** — pull each block toward the centroid with a force proportional to its distance
   (`grav = GRAVITY * d_centroid / k`, `GRAVITY ≈ 0.06`). This is what makes an *unconnected*
   site graph settle instead of expand, and it is the minimum change that makes the physics
   correct rather than accidentally bounded.
2. **Frame clamp** — `cx = clamp(cx, -half, +half)`, same for `cy`. The hard guarantee, exactly
   as classic Fruchterman–Reingold specifies.

Both are additive; the existing repulsion, attraction, cooling and the overlap-resolution pass are
untouched, so connected estates keep today's clustering.

**Acceptance:** with 21 sites and zero cross-site links, the site-ring radius must fall from 39,253
to within the frame (expected ≈3,000–4,000; bbox ≈6,000–8,000).

### Step 2 — Guarantee a non-empty viewport (fixes D2)

In `applyReadableViewport()`, after the `needsPan` branch sets the readable zoom and centres, add a
**verification-and-correction** step, not a second heuristic:

- Count nodes whose position lies within `cy.extent()`.
- If **zero**, re-centre on the **densest cluster** rather than the bounding-box centre: pick the
  node nearest the centroid *of node positions* (not of the bounding box) and `cy.center()` on it.
- Keep the readable zoom; only the centre moves.

This is a safety net with a measurable post-condition, and it is what makes "blank canvas"
structurally impossible regardless of which layout runs or what an estate's shape turns out to be.

### Step 3 — Honest hint text

When Step 2's correction fires, the existing `viewportHint` should say so rather than claim
everything is fine — e.g. *"Showing the largest cluster — zoom out to see the whole estate"*. The
operator must never be shown a corrected camera without being told the view is partial.

### Step 4 — Regression tests

The viewer is a self-contained HTML artifact, so the tests are Python-side over the rendered
artifact plus a small headless assertion of the layout maths:

1. **The physics test (the headline):** run the force pass over 21 synthetic ovals with an **empty**
   `W` matrix and assert the final ring radius stays inside the frame. This is the test that would
   have caught D1 the day it was written.
2. **Non-empty viewport:** after `applyReadableViewport`, assert ≥1 node lies within `cy.extent()`
   for (a) the exploded-ring case, (b) a ring with an empty centre, (c) a normal estate.
3. **No regression for connected estates:** a synthetic estate *with* cross-site links keeps its
   clustering (connected pairs end nearer than unconnected ones).
4. **Bounding-box sanity:** assert the rendered artifact's bbox is within an order of magnitude of
   `n × avg-oval-size` — a cheap invariant that catches any future layout explosion.

### Step 5 — Documentation

Record in the viewer's own comments (where the force pass lives) **why** the frame and gravity
exist — that the attraction term is conditional and an estate with no cross-site links has no
inward force at all. That comment is what stops the frame being "simplified away" later.

### Non-goals

- Do not change the readable-zoom floors (0.86 / 0.84) — they are working as designed.
- Do not change `cy.fit()`, the minimap, the export `viewBox`, or the bounding-box maths — all
  verified correct.
- Do not touch the intra-site layout (`computeIntraLayout`) — verified correct.
- Do not add viewport persistence.
- Do not change the Force/COSE layouts — verified unaffected.
- Do not commit.

### Success criteria

1. `Logical (sites & tiers)` on the 19onlyAI estate renders **nodes in the viewport on load**.
2. Site-ring radius bounded by the computed frame; bbox falls from ~78,000 to single-digit
   thousands.
3. **Zero nodes in viewport is impossible** after `applyReadableViewport`, for every layout.
4. Estates *with* cross-site links keep today's clustering (no visual regression).
5. The minimap shows a legible estate, because the extent it renders is now sane.
6. Full regression suite green (baseline 2,948 / 2 skipped / 897 subtests).
