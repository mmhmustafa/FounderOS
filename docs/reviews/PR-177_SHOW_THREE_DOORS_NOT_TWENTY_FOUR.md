# PR-177 — First Run: Show Three Doors, Not Twenty-Four

**Progressive Navigation & External-Beta Onboarding**
*Architecture and product design. No code was modified. Nothing was committed.*

Prepared against the real repository at `122a891` and two running Atlas instances: a
pristine temporary workspace and the live 16-profile / 865-device estate.

---

## 1. Executive diagnosis

**The premise needs correcting before the fix is designed.** PR-175 reported that a fresh
workspace "exposes 24 destinations before the user has any data." The DOM does contain 24
links, but the sidebar is a native `<details>`/`<summary>` accordion in which only the
active group is expanded. Measured in the browser on a pristine workspace, exactly **three**
navigation links are visible and keyboard-focusable — Overview, Action Center, Incidents —
and the other 21 sit inside closed `<details>`, correctly outside both the tab order and the
accessibility tree.

```
first-run sidebar, measured: 24 links in the DOM
                              3 pass checkVisibility() and accept focus
                             21 inside details:not([open])
                              5 group summaries always visible
```

So Atlas does not greet a new user with a wall of links. What it greets them with is
**five workflow areas — Home, Network, Operations, Analyze, Administration — four of which
are empty until a discovery runs**, and a sidebar that is byte-identical whether Atlas knows
about 865 devices or nothing at all. I verified that equivalence directly: the same five
groups and the same three visible links render on the fresh workspace and on the live estate.

That is the real defect, and it is sharper than "too many doors":

> **Atlas's navigation is context-blind. It advertises the same five workflows to an
> operator who has evidence and to one who has none, and it puts the single action that
> matters on first run — Discover — sixteenth of twenty-four, inside a collapsed group
> labelled "Administration".**

Three consequences follow, all confirmed first-hand:

1. **The first-run path is real but undersold.** Home already renders a dedicated first-run
   branch: *"Network state is unknown — no discovery has run yet"*, *"Atlas reports only what
   evidence proves. Run a discovery to give it something to reason about"*, and a
   `Run your first discovery` primary button (`mission.html:29-36, 91-99`). One click reaches
   `/discovery`. The honest-unknown work is done; the framing and the sequencing are not.
2. **The Discovery page inverts its own hierarchy.** On a fresh workspace the mandatory first
   step — *"Add a profile"* — is an unstyled inline link inside a `.muted` paragraph
   (`discovery.html:66`), while `Execution Console (sample)` — a button leading to a wholly
   fabricated demo of a network called "Delhi Lab" — renders as the *first* control in the
   page head, visually left of the primary action (`discovery.html:7-9`).
3. **The escape hatch that would justify hiding anything is already broken.** The design's
   safety net is "hidden pages stay findable via Ctrl+K". I tested it in the browser: search
   for `topology`, `evidence`, `settings` or `policy` and Atlas renders
   `Pages & commands (undefined)`, zero results, and the message
   **"Search unavailable — is the Atlas server still running?"** while the server is healthy
   and returned HTTP 200. This is a pre-existing, 100 %-reproducible defect (details in §10).

The good news is that the fix is small, because **Atlas already owns every piece it needs**:
an authoritative readiness signal that is already correct, a single RBAC nav builder whose
"display fails open, access stays closed" doctrine is exactly the right shape for guidance,
and 25 of 25 routes that already render safe empty states on an empty workspace.

---

## 2. Current first-run state model

There is **no first-run state** in Atlas today. No route, template, or context inspects
"has a discovery run" to decide what to show in the chrome. The only data-shaped branching is
per-page empty-state rendering, which is generally good.

| Surface | Fresh workspace behaviour | Verdict |
|---|---|---|
| Sidebar | 5 groups, 3 visible links, identical to a populated estate | context-blind |
| Home (`/` → `mission.html`) | Correct first-run branch: honest-unknown callout, one framing sentence, `Run your first discovery` CTA, all stat tiles suppressed | good, under-framed |
| Home (`/?scope=default` → `dashboard.html`) | No first-run treatment; em-dash tiles and an unconditional Unknown health banner | still deep-linkable |
| `/discovery` | Wizard is primary; "Add a profile" is the weakest control; `Execution Console (sample)` renders first | inverted |
| 14 advanced pages | All HTTP 200 with real empty states; 4 print misleading zeros | safe, imperfect |
| Ctrl+K palette | Broken for page queries (§10) | broken |

Measured cold render times on the fresh workspace ranged 26–430 ms; no page was slow, and
none 500'd or redirected.

**Four pages print misleading zeros before any evidence exists** — `/policy`
("Compliance score 0%", from `policy/explorer.py:382-389` returning `0` when `judged == 0`),
`/changes` (an 8-tile all-zero strip above the explainer), `/timeline` (five zero tiles plus
one genuine but bewildering event: an internal `workspace-schema:v2` migration audit record),
and `/paths` + `/predict` ("0 canonical device(s) from 0 contributing profile(s)"). These are
copy/logic defects that navigation gating cannot fix; they are named here and assigned to
PR-178, not absorbed.

---

## 3. Recommended first-run state model

Two states, not three. A `DISCOVERING` state was considered and rejected (§12).

**STATE A — SETUP** (no usable discovery anywhere in the workspace)

```
Home
  Overview
Administration
  Discover
  Settings
```

Three destinations in two groups, both expanded. `Network`, `Operations` and `Analyze`
disappear entirely, for free: `visible_nav_groups` already drops any group left with zero
items (`models.py:502-503`). One line in the existing `.sidebar-note` slot explains the
state — *"More appears after your first discovery."* — because three links with no
explanation reads as a broken install, and that will be the first beta report filed.

**STATE B — OPERATIONAL** (the workspace holds usable evidence)

Today's full navigation, unchanged. No taxonomy change, no regrouping, no renaming — those
are explicit non-goals.

The transition is one-way within a session and derived from disk, never from the browser.

---

## 4. Authoritative discovery-readiness signal

**Atlas already has it, it is already correct, and it is already used on Home.**
`DiscoveryScope.has_data()` (`workspace/scopes.py:63-69`) is true when a scope holds a
`topology_snapshot.json` **or** any history subdirectory; `active_scopes()`
(`scopes.py:114-132`) reduces that across the estate; `routes.py:1125` already passes
`has_any_data=bool(aggregated)` into Home's recommendations.

I ran every first-run state through it on throwaway workspaces using the suite's own
discovery harness:

| State | `has_any_data` | Correct? |
|---|---|---|
| Empty workspace | `False` | ✓ |
| Profile created, never run | `False` | ✓ |
| **Discovery failed, nothing answered** | **`False`** | ✓ |
| Discovery succeeded | `True` | ✓ |
| Old success + new failed run | `True` | ✓ stays unlocked, no special case |
| Enterprise Memory deleted, snapshot kept | `True` | defensible — a snapshot *is* data |

**A widely-assumed failure mode does not exist.** It is natural to worry that "any history
directory" includes a failed run. It does not, and this was established twice independently:
empirically (a failed run wrote *only* `sessions.json`; no history directory, no snapshot),
and by call-chain proof — `allocate_record_dir` (`history/storage.py:27-37`) is the only
mkdir of a record directory, reachable solely via `save_discovery` (`repository.py:67`) from
`commands.py:1588`, which runs *after* `_build_reports`; a run whose seeds all fail raises and
is converted to `CliError` at `commands.py:514-517` before anything is written. **No
device-count parsing is needed**, which matters because it is the difference between a stat
and a per-request JSON parse.

**Rejected alternatives, each for a concrete reason:**

| Candidate | Why rejected |
|---|---|
| Enterprise Memory `DiscoverySession` exists | **The trap.** A failed run *does* create a session — my probe measured `sessions=1, devices=0`. This would unlock the whole product after a total failure. |
| `SESSION_FAILED` / `SESSION_INTERRUPTED` status | Defined at `enterprise_memory/models.py:71-74` but **no producer ever assigns them**; a dead run reads "running" forever. |
| `profile.last_discovery` | `profiles.json` is inside the backup manifest (`backup.py:58-83`) while the output directory is not — a restored workspace would claim a discovery with zero data behind it. Also survives an evidence reset (measured). |
| `.atlas/jobs.json` | A 20-entry rolling window (`jobs.py:65, 515-517`) whose latest entry flips to `failed` — the nav would collapse on an estate full of good data. |
| `statistics()` / `device_ids()` | **Cost.** Measured on the live estate: 151 ms and 125 ms respectively, *per render*. This is precisely the per-request full parse PR-176 just removed. |
| `enterprise_world()` | Categorically unusable: it **writes three files** (`federation/service.py:318-370`) and would run from a context processor that also fires on 404 and 500 pages. |
| `display_level` preference | Its documented contract (`_disclosure.html:10-16`) is that content is *never removed*. |

**Cost, measured on the live 17-scope estate:** `active_scopes()` = **0.71 ms**;
short-circuited = **0.08 ms**. Against a 400–700 ms page render this is free.

### The amended rule, in full

```
revealed(app) :=
    # 0. Guidance applies only to a principal who could act on it.
    (g.principal is not None and DISCOVERY_RUN not in g.principal.permissions)
 OR # 1. Monotone in-process latch — only ever assigned True.
    bool(app.extensions.get("atlas_nav_revealed"))
 OR # 2. Durable per-workspace marker (one is_file()).
    (ATLAS_OUTPUT_DIR / ".atlas" / "nav-revealed").is_file()
 OR # 3. The live filesystem signal.
    bool(active_scopes(default_scope(OUT, HIST), profile_scopes(OUT, profiles)))
```

Term 0 is a **blocker fix**: `ROLE_GRANTS` (`access/models.py:58-74`) grants `DISCOVERY_RUN`
to only two of seven roles. A viewer on a fresh workspace passes the RBAC filter for all three
SETUP destinations but cannot run a discovery (`discovery.html:41-44` gates the form on
`can('discovery.run')`), so without term 0 they would be locked into three dead ends **forever**,
with no action that could ever release them.

Term 2 is a **major fix**: deleting or archiving the only profile is a supported one-click
action that leaves the scope directory on disk; after a restart, `profile_scopes()` would be
empty and a workspace full of evidence would silently re-lock. The marker lives in the output
directory, which `backup.py:58-83` does *not* carry, so restore-onto-a-clean-machine still
correctly reads `False`.

Evaluation order is load-bearing: RBAC escape → latch → per-request memo → marker →
short-circuit → full check. **Negative answers must be memoised against a cheap stamp**
(`profiles.json` mtime/size plus the profiles-dir mtime), because an attempted-but-failed run
*does* create `.atlas/profiles/<id>/enterprise-memory/` (confirmed in my probe: `sessions.json`
was written there), so the "profiles dir absent" short-circuit will not fire on a workspace
whose discoveries all fail — and that workspace would otherwise pay a full `profiles.json`
parse plus N stat+iterdir on **every** render, forever. Positive answers are never invalidated.

Finally, the exception handler must be **broad**: `WorkspaceCorruptedError` derives from
`AtlasWorkspaceError(Exception)` (`workspace/exceptions.py:4,20`) and is raised by
`ProfileRepository.load()` at `repository.py:80/85`, so a narrow tuple lets it escape a context
processor that runs on the error page itself. Log at debug, **return `True`** (display fails
open, the doctrine `allowed_nav_path` already states at `models.py:456-459`), and critically
**do not latch on the fail-open path** — the latch is write-once, so one transient error
latched `True` would reveal the nav permanently and silently.

---

## 5. Progressive navigation architecture

**Compose a new pure filter over the existing builder; do not modify the existing builder.**

```
render_nav_groups(app) = guided_nav_groups(visible_nav_groups(app),
                                           revealed=workspace_has_discovery(app))
```

- `visible_nav_groups` (`models.py:488-504`) and `allowed_nav_path` (`models.py:451-485`)
  are **not touched**. Their docstrings are explicitly about RBAC parity with the command
  palette; putting guidance inside them would make the function's meaning depend on which
  caller invoked it, and would re-arm the PR-172 "two filters disagreed" bug.
- `guided_nav_groups(groups, *, revealed)` is **pure** — tuple in, tuple out, no Flask import,
  unit-testable with no app. It drops items marked `sidebar=False` always, and when
  `revealed` is `False` also drops items whose key is not in
  `PRE_DISCOVERY_ITEM_KEYS = {"dashboard", "discovery", "settings"}`.
- Item keys, not hrefs or group keys: keys are frozen by contract (`models.py:61-64`) and are
  what routes already pass as `active`. The target spans two groups, so it must be item-level.

**There are two render sites, and both must be changed** — this is the single easiest thing to
get wrong. `routes.py:474` (`base_context`) covers most pages, but the app-wide context
processor at `app.py:354` supplies `nav_groups` to every `render_template`, including
`/users`, `/inbox` and `/system/integrity`, whose routes never call `base_context`. Miss it and
those three pages keep rendering the full sidebar.

**The third call site — `routes.py:7405`, the Ctrl+K pages filter — must deliberately stay
unchanged.** That zero-line diff is what makes "guidance, not access control" true in code
rather than merely asserted. Its docstring currently claims *"the palette can never offer a
page the sidebar would hide"*; that sentence becomes false the moment this PR lands and must
be rewritten to state the new invariant, or a future reviewer will recognise the shape of the
PR-172 bug and "fix" guidance back into access control.

**The template fix that is easy to miss.** `base.html:100` emits `open` only when
`group.key == active_group`. On a fresh workspace at `/`, `active_group` is `home`, so a
filtered sidebar would render Home expanded (one link, "Overview") and Administration
**collapsed** — the user would not see three doors, they would see one. Worse, a deep link to
a hidden page makes `nav_group_for` return a group absent from the DOM, so **nothing** opens
and the sidebar shows zero links. Change to:

```jinja
<details class="nav-details" {{ 'open' if (group.key == active_group or not nav_revealed) else '' }}>
```

This is safe against the accordion enhancement (`atlas.js:1173-1186`), which binds a
capture-phase `toggle` listener and therefore does not run at page load.

**What does *not* need changing, and why.** `workspace.py:38` imports `NAV_GROUPS` directly
and flattens it into a module-level `_PAGES` at import time, so breadcrumbs, `pages()` and
`palette_index()` are request-agnostic and **structurally immune** to this filter. That
immunity is the accessibility mitigation (§13) and it comes free.

---

## 6. Discovery-page hierarchy

State-driven, three states, one dominant action each.

| State | Dominant action | Supporting |
|---|---|---|
| **No profile** | `Add discovery profile` (primary) — "A profile tells Atlas where to connect and how." | Discovery Wizard offered as the guided alternative |
| **Profile exists, never run** | `Run Discovery` (primary) | profile selector, wizard link |
| **Run in progress** | the live job panel | everything else de-emphasised |

Changes required, all citable:

1. **`Execution Console (sample)` leaves the page head.** It is a static demo fed by
   `/api/discovery/execution/demo`, which fabricates a network called "Delhi Lab" over
   `172.20.20.11-26` (`routes.py:9531-9560`) and whose Resume/Pause/Stop buttons only print
   *"Sample console — does not act on a live run"*. It is linked from exactly one place in the
   codebase. It must not be the first control an evaluator sees. Note `test_discovery_execution.py:481-485`
   pins the link and will need updating.
2. **"Add a profile" becomes a real primary control** in the no-profile state, not an inline
   link in a `.muted` sentence.
3. **Resolve the competing primaries.** On a populated estate both `Discovery Wizard` and
   `Run Discovery` render as `btn-primary`; and Home shows both a topbar `Run Discovery` and
   the in-page `Run your first discovery`. One primary per state.
4. **Suppress the empty result scaffold.** "Discovery result" renders a full list of dashes
   before any run — including on the live estate, since it only fills via JS after a run in
   that page session.
5. **Fix the dead `?profile=` parameter** (`routes.py:1793-1795`): the Profiles page "Run"
   button passes it and nothing reads it; `?scope=` is the parameter that works.

`profiles` deliberately stays **out** of the SETUP allowlist: `discovery_wizard_start` creates
the profile itself (`routes.py:2056-2091`), so the wizard is a complete zero-to-discovery path,
and `/profiles/new` remains reachable from the Discovery page and by URL. Adding it later is a
one-token change if the product call goes the other way.

---

## 7. First-run Home framing

The existing first-run branch (`mission.html:29-36`) is the right place; it needs one
sentence of product framing above what it already says, and the noise below it suppressed.

Recommended copy — operator vocabulary, no marketing, no architecture terms:

> **Atlas explains your network from evidence it collects itself.**
> Point it at one device and it discovers the rest, records exactly what each device
> reported, and reasons only from that. Nothing is inferred, nothing is guessed.
>
> **To begin, Atlas needs one network to look at.**
> `[ Run your first discovery ]`
> *Atlas connects read-only. It never changes a device.*

The read-only line earns its place: the audience is network engineers being asked to point an
unfamiliar tool at production infrastructure, and it is the first question they will ask.

Also suppress, pre-discovery, the sections that offer work that cannot be done yet — the
"Continue Working" starting points (*"Routing issue — why can't A reach B?"*, *"search the SVI
VLAN20"*, *"plan it with Compass"*) and the six-item "All workflows" grid. And note
`.mission-primary` has **no CSS rule anywhere** (`mission.html:91` is its only occurrence), so
the "one visually dominant primary action" its own comment promises is not currently delivered.

---

## 8. PRISM / Playground placement

**Keep the `NavItem`, hide it from the sidebar, and give it a front door in Settings.**

```python
NavItem("prism-playground", "PRISM Playground", "/prism/playground", sidebar=False)
```

Deleting the entry outright is the tempting move and it is wrong: `workspace._PAGES` is built
from `NAV_GROUPS`, so deletion would silently also remove the page's **breadcrumb bar**
(`base.html:148` hides the whole bar at trail length 1), its **Pin button**
(`workspace_here` becomes `{}`), and its **palette entry** — three losses no test catches.

The front door is **mandatory, not optional**: no template in the repository links to
`/prism/playground`, so removing it from the sidebar without adding one makes it URL-only,
while the Playground itself links back to `/settings/ai` — a one-way door away from the
administrators it was built for. Add one permission-gated card inside the existing
`{% if can('system.admin') %}` block at `settings_ai.html:167`, relabelled in operator
vocabulary ("Try PRISM on sample evidence").

Two facts sharpen this. The Playground makes **real, billable provider calls** — up to six per
"Compare all audiences" click, doubling with translation — and writes them into the *same*
`prism-usage.jsonl` ledger whose cost totals `/settings/ai` displays, so demo spend is
indistinguishable from production spend. And it is inert until PRISM is configured
(`enabled=False` by default), so on a fresh workspace it renders only a "PRISM is not ready
yet" card. It should therefore **not** be gated on the discovery reveal — its real
precondition is "PRISM is configured", which is a Settings concern.

No test asserts the Playground is in navigation, so this breaks nothing.

---

## 9. Post-discovery transition

Atlas currently tells the operator almost nothing at the moment that matters. There is **no
redirect, no flash, and no server-side success hook** — `DiscoveryJobManager` exposes exactly
one completion callback and it is failure-only (`jobs.py:226, 410-431`). The browser learns the
run finished by polling every 1.5 s, then renders a 12-row summary and four equal-weight links
in place. The flash the operator *does* see fires at **start**, never at completion.

**Recommendation: keep the operator on `/discovery`, upgrade the panel, and reveal the nav
in the same moment.**

> **Atlas is ready.**
> 85 devices · 119 relationships · 42 configurations collected
> `[ View the topology ]` `[ Review network health ]` `[ Ask Atlas ]`

Everything above is already in `job.summary`, computed once in the worker thread and free at
poll time (`routes.py:9790-9834`). Two constraints:

- **No site count.** Sites are derived at render time and never persisted; obtaining one costs
  a renderer pass or a federated-graph build. Use relationships or configurations instead.
- **No health verdict.** Including "N items need attention" pays a cold policy evaluation
  (~4.4 s pre-PR-176). Link to health; do not compute it inline.

**The reveal must happen in the same JS moment**, or the operator finishes their first
discovery and keeps the three-item nav until they happen to navigate — the exact opposite of
the payoff. `refreshNetworksTable` (`atlas.js:230-248`) already re-fetches and parses the
current page; swap `#atlas-sidebar`'s **innerHTML** from that same parsed document (zero extra
requests). Never replace the element itself — the accordion and drawer handlers are delegated
on it. And do **not** skip the swap when focus is inside the sidebar: the terminal poll branch
fires exactly once and never retries, so skipping is a permanent cancellation reachable by
pressing Tab. Capture the focused link's `href`, swap, then restore focus to the matching
anchor.

Add the `on_success` hook to `DiscoveryJobManager` mirroring `on_failure`, invoked at the end
of `_finish_completed`; it never lies, because the snapshot and history record are both on disk
before the runner returns.

---

## 10. Deep-link behaviour

**Every hidden page stays fully reachable by URL. Progressive navigation is guidance, never
access control.** No route changes, no redirects, no gates.

This is affordable because it is already true: I fetched all 25 first-run-reachable routes on
a pristine workspace and **every one returned HTTP 200** with a real empty state — no 500s, no
redirects, 26–430 ms. A deep-linked `/topology` on a fresh workspace still renders
"Home › Network › Topology" with `aria-current="page"` on the final crumb
(`_breadcrumbs.html:12`), because breadcrumbs come from the unfiltered `_PAGES`.

**Two wayfinding gaps must be closed.** `/inbox` (`ops.py:158`) and `/telemetry`
(`telemetry_routes.py:102-110`) render without `base_context`, so `base.html:148` suppresses
their workspace bar entirely. Hidden from the nav, they would be the only two of the 24
destinations with **neither** a nav entry **nor** a breadcrumb. Route both through
`base_context`. This is load-bearing, not polish.

### The Ctrl+K palette is broken today — verified in the browser

The "still findable via search" defence does not currently hold. `_palette_pages_group`
(`routes.py:7418-7431`) emits `total` / `label` / `detail`, while the canonical `SearchGroup`
emits `count` with hits keyed `title` / `subtitle` (`search/models.py:113-141`), and
`atlas.js` reads `count` (601), `title` (609) and `subtitle` (612) with an unguarded
`text.toLowerCase()` in `highlight()`.

Measured on the live estate:

| Query | API returns | Browser renders |
|---|---|---|
| `topology` | `pages` group, `total: 1` | `Pages & commands (undefined)`, 0 results, *"Search unavailable — is the Atlas server still running?"* |
| `evidence` | `pages` group, `total: 2` | same |
| `settings` | `pages` group, `total: 2` | same |
| `core` | 9 entity groups, all `count` | renders correctly — 844 results, 56 items |

Entity search is healthy; **only the pages group is malformed**, and it fails closed with a
message accusing the server of being down. Since typing a page name is a primary way to
navigate, this must be fixed **in this PR or immediately before it**: emit `count` /
`title` / `subtitle`, and null-guard `highlight()`. Without it, "hidden pages remain findable"
is false, and anyone validating PR-177 will observe a failure that predates it and
misattribute it.

---

## 11. Restart / refresh behaviour

Nav state derives from disk plus a process latch, never from the browser. No `localStorage`,
no `sessionStorage`, no cookie, no per-user flag.

| Event | Behaviour |
|---|---|
| Browser refresh / new tab | Recomputed server-side; unchanged |
| New session / different browser / different user | Same answer — the signal is per **workspace**, not per user |
| Application restart | Marker file and filesystem signal both survive; latch rebuilds on first request |
| New profile added post-discovery | Cannot regress — `active_scopes` is an OR across scopes |
| Scope switched to an empty profile | **Nav does not change.** Workspace-wide, deliberately: the sidebar must never disagree with Home, and a nav that changes shape on scope switch is more surprising than one that does not |
| Evidence deleted mid-session | Latch holds until restart — a nav that re-hides itself mid-session is worse than one that outlives its data by one process lifetime. Named, not hidden |
| Workspace restored from backup onto a clean machine | Correctly reads `False`: the output directory is not in the backup manifest |

---

## 12. Failure-state behaviour relevant to navigation

**A failed discovery does not unlock anything**, and this needs no special-casing: a failed
run writes no snapshot and no history record, so the signal is simply still `False`.
Confirmed empirically and by call-chain proof (§4).

**An old success followed by a new failure keeps the workspace unlocked.** A failure writes
nothing and deletes nothing, so the earlier evidence still answers. This is the correct product
rule and it falls out of the design rather than being coded.

**Partial success unlocks.** The rule is deliberately *not* keyed on `failures == []` or
`network_status == "Healthy"` — the live estate's newest run is 85 devices with 169 failures,
status "Attention Required", and is entirely usable. If Atlas has evidence about one device,
there is something worth looking at.

**A `DISCOVERING` state is rejected.** It is derived from the in-process job manager, so it
resets after a restart mid-run; and polling only activates where `#job-panel` exists
(`atlas.js:155-157`), so on the other 23 pages it would make a promise nothing visibly
fulfils. SETUP simply persists until evidence lands.

One consequence to fix: `base.html:103` renders the unread badge on the *Home group*
independently of whether the `inbox` item survived filtering, so a failed first discovery would
show a badge reading "1" on a group containing only "Overview", announced to screen readers as
"1 unread notifications". Gate the badge on the item's presence, or add `inbox` to the
allowlist.

---

## 13. Accessibility implications

The mechanism is **server-side omission**, never CSS hiding — hidden items are absent from the
DOM, so they cannot be focused, announced, or reached by a screen-reader rotor. This is
strictly better than today, where 21 links sit in closed `<details>`.

- **Focus order** shrinks to what is actionable; no keyboard trap is possible.
- **Landmarks** are untouched: `<nav aria-label="Workflows">`, `<nav aria-label="Breadcrumb">`,
  `<main>`, `<header>`, the skip link, and the search `role="dialog"` all remain.
- **`aria-current="page"`** is *not* lost on deep-linked hidden pages — `_breadcrumbs.html:12`
  already emits it on the final crumb, and breadcrumbs are immune to the filter. This is to be
  **verified by test, not built**.
- **Do not** reveal the owning group of a deep-linked hidden page: the `app.py:354` context
  processor does not know `active` (it supplies `"active": ""`), so the two render sites would
  compute different navigation — re-arming exactly the bug `models.py:489-492` exists to prevent.
- The **nav swap on completion** must restore focus to the equivalent anchor, never leave it on
  `<body>`.
- The `.sidebar-note` explanatory line is real text in an existing element, announced normally.

---

## 14. Responsive implications

Verified at 375, 768 and 1280+ px on the real application:

- **375 px** — off-canvas drawer, `visibility: hidden` when closed (so already correctly out of
  the tab order), `.nav-toggle` with `aria-expanded` / `aria-controls="atlas-sidebar"`. All 24
  links fit within 812 px without scrolling today; at three links the drawer becomes trivial.
- **768 px** — same drawer behaviour.
- **1280 / 1920 px** — persistent sidebar.

No new breakpoints, no mobile-specific product semantics, no CSS required. The drawer's
link-close handler is delegated on `#atlas-sidebar`, which is why the completion swap must
replace `innerHTML` rather than the element.

---

## 15. Test plan

New `tests/test_progressive_navigation.py`:

1. **Pure filter** — `guided_nav_groups` with `revealed` True/False; `sidebar=False` dropped in
   both; emptied groups dropped. No Flask.
2. **Signal case table** — fresh / snapshot-only / history-only / profiles-dir-absent
   short-circuit / latch-survives-deleted-data / marker-file-only. No render.
3. **G2** — fresh workspace sidebar contains exactly `href="/"`, `href="/discovery"`,
   `href="/settings"`, and exactly two `<details class="nav-details">`, **both carrying `open`**
   (the `base.html:100` regression guard).
4. **Two-call-site parity (non-optional)** — GET `/users`, `/inbox` and `/system/integrity`
   (which reach nav *only* via the `app.py:354` context processor) on a fresh workspace and
   assert the same item set as a `base_context` page. This is the only guard against the PR-172
   failure mode this design re-arms.
5. **Deep links** — all 24 hrefs return 200 on a fresh workspace; a hidden one renders a
   3-level breadcrumb containing `aria-current="page"`.
6. **Ctrl+K unnarrowed** — search still finds "Policy" on a fresh workspace, and the pages group
   emits `count` / `title` / `subtitle`.
7. **Reveal** — `build_world(tmp, discover=False)` → 3 items; run a discovery → re-GET → full nav.
8. **Failed discovery does not reveal**; **old success + new failure stays revealed**.
9. **RBAC escape** — a viewer on a fresh workspace is *not* guided (term 0), and RBAC still
   hides `/users` from a viewer after the reveal.
10. **PRISM Playground** absent from the sidebar, present in `palette_index()`, URL 200,
    reachable from `/settings/ai`.
11. **Discovery hierarchy** — no profile ⇒ "Add profile" is the only primary; profile present ⇒
    "Run Discovery" is; `(sample)` and "Execution Console" absent from operator UI.

**Tests that will break** (a monkeypatched simulation across all 71 app-building test files
found exactly five, all expected): `test_product_focus.py:118-127` and `:129-141` assert the
full sidebar on an empty workspace — rewrite as post-reveal assertions and replace the
docstring "Mission is the front door, never a gate" so the reversed product decision is
*recorded*, not silently dropped. `test_navigation_areas.py:61-70, :72-80` build an empty
workspace to test RBAC — seed a discovery so they keep testing RBAC rather than silently
becoming progressive-nav tests. `test_discovery_execution.py:481-485` pins the console link.

**Tripwires that must stay green untouched**: `test_workspace_experience.py:362-369` (palette
finds Policy on a fresh workspace — if this goes red the filter reached the wrong site),
`:253-263` (breadcrumbs), `:210-219` (every `NAV_GROUPS` label in `palette_index()`, called
with no app at all — the hard pin against pushing the filter into `workspace.py`), and
`test_product_focus.py:53-66` (NAV_GROUPS structure).

---

## 16. Browser-validation plan

Primary walkthrough on a pristine workspace: Home → read the framing → `Run your first
discovery` → `/discovery` with no profile → create a profile → run → watch progress →
completion summary → **nav reveals in place** → full workspace.

Also validate: browser refresh at each step; application restart before and after the reveal;
a **failed** discovery (nav stays at three, and the failure is explained); an old success plus
a new failure; deep links to `/topology`, `/policy`, `/evidence` before discovery (200 + empty
state + breadcrumb + `aria-current`); **Ctrl+K for "policy" before and after the fix**;
375/768/1440/1920 px; keyboard-only traversal with focus visible throughout; and the reveal
occurring while focus sits on a sidebar link.

---

## 17. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Two render sites drift apart — the PR-172 bug, re-armed | **High** | One `render_nav_groups` builder; parity test #4 is non-optional |
| R2 | A reviewer "fixes" the sidebar/palette divergence into access control | **High** | Rewrite the `routes.py:7387` docstring to state the new invariant; tripwire test 6 |
| R3 | Per-render cost on a workspace whose runs all fail | Medium | Stamp-keyed negative memo; positive never invalidated (§4) |
| R4 | A viewer is permanently stranded in SETUP | **High** | Term 0 — guidance applies only to principals holding `DISCOVERY_RUN` |
| R5 | Deleting the only profile re-locks a workspace with data | Medium | Durable `.atlas/nav-revealed` marker, outside the backup manifest |
| R6 | Fail-open path latches `True` on a transient error | Medium | Broad `except`, return `True`, **write no cache** |
| R7 | Three links with no explanation reads as a broken install | Medium | The `.sidebar-note` line is mandatory, not optional |
| R8 | The reveal does not happen until the user navigates | Medium | Sidebar swap in the terminal poll branch, with focus restoration |
| R9 | Hidden pages become genuinely unfindable | Medium | Ctrl+K fix (§10) ships with or before this PR |
| R10 | Misleading zeros on deep-linked pages undercut the first impression | Low | Named and assigned to PR-178, not absorbed |

---

## 18. Recommended PR scope

**In scope:** `NavItem.sidebar` field + `PRE_DISCOVERY_ITEM_KEYS` + `workspace_has_discovery` +
`guided_nav_groups` + `render_nav_groups` (`models.py`); the two render-site swaps
(`app.py:354`, `routes.py:474`) plus `nav_revealed` in both contexts; the `base.html:100`
accordion fix and the `.sidebar-note` line; the `base.html:103` badge fix; `on_success` on
`DiscoveryJobManager` + the `atlas.js` sidebar swap with focus restoration; the Ctrl+K pages
group shape fix + `highlight()` null-guard + docstring rewrite; routing `/inbox` and
`/telemetry` through `base_context`; the Discovery-page hierarchy and removal of
`Execution Console (sample)` from the page head; the Home framing paragraph and pre-discovery
noise suppression; the PRISM front door in `settings_ai.html`; the conditional
`profile_create` redirect; and the tests in §15.

**Explicitly out of scope:** the misleading zeros on `/policy`, `/changes`, `/timeline`,
`/paths`, `/predict`; any navigation taxonomy change; merging Discoveries with Timeline; the
PR-178 experience-language work; PR-179 failure paths; PR-180 version/beta hygiene; the
`/api/discovery/execution/demo` endpoint's existence and its `PAGES_VIEW` authorisation
(flagged for PR-179); and the JS-off wizard gap.

---

## 19. Success criteria

| Gate | Target | How it is met |
|---|---|---|
| **G2** | ≤5 destinations pre-discovery, target 3 | Exactly 3: Overview, Discover, Settings — test #3 |
| **G3** | Zero operator-facing developer artifacts | `(sample)` and "Execution Console" leave the Discover page head; "PRISM Playground" leaves the sidebar — test #11, #10 |
| **G4** | The required next action is the most prominent control | State-driven Discovery hierarchy — test #11 |
| **G5** | Product framing visible on first launch | Home framing paragraph — §7 |
| — | All deep links preserved | All 24 return 200 — test #5 |
| — | No successful workflow loses capability | Nav filter only; RBAC and routes untouched — test #9 |
| — | No first-run state in browser storage | Filesystem + process latch only — §11 |
| — | Unlock derives from authoritative backend state | `active_scopes()` — §4 |

---

## 20. Approved implementation plan

**Step 1 — Fix the escape hatch first.** Correct the Ctrl+K pages group to emit
`count`/`title`/`subtitle`, null-guard `highlight()`, and rewrite the `routes.py:7387`
docstring to the new invariant. Prove in a browser that searching "policy" returns results.
*Nothing else may land until hidden pages are genuinely findable.*

**Step 2 — Build the signal, with its case table, before any UI changes.** Add
`workspace_has_discovery` with the full amended rule (§4): RBAC escape, latch, request memo,
marker, short-circuit, stamp-keyed negative memo, broad `except` that returns `True` without
caching. Land tests 1, 2, 8 and 9 first. Do not proceed until the failed-discovery and
viewer-role cases are green.

**Step 3 — Apply the filter at both render sites.** Add `NavItem.sidebar`,
`PRE_DISCOVERY_ITEM_KEYS`, `guided_nav_groups`, `render_nav_groups`; swap `app.py:354` and
`routes.py:474`; publish `nav_revealed`; fix `base.html:100`, `:103`, and add the
`.sidebar-note` line. Leave `visible_nav_groups`, `allowed_nav_path` and `routes.py:7405`
untouched. Land tests 3, 4, 5, 6.

**Step 4 — Close the wayfinding gaps.** Route `/inbox` and `/telemetry` through
`base_context`. Add the PRISM front door to `settings_ai.html` and set `sidebar=False`. Land
test 10.

**Step 5 — The reveal moment.** Add `on_success` to `DiscoveryJobManager`; restructure
`refreshNetworksTable` into `refreshAfterDiscovery` so each swap applies independently; swap
`#atlas-sidebar`'s innerHTML from the already-parsed document with focus restoration. Land
test 7. Verify in a browser that the nav expands without a page load.

**Step 6 — Discovery and Home.** State-driven Discovery hierarchy; remove
`Execution Console (sample)` from the page head; make "Add a profile" primary in the
no-profile state; resolve the competing primaries; suppress the empty result scaffold; fix the
dead `?profile=`; make `profile_create` redirect conditional. Add the Home framing paragraph
and suppress pre-discovery noise. Land test 11.

**Step 7 — Validate.** Full regression suite; the §16 browser walkthroughs; confirm G2–G5;
re-run the PR-175 cold sweep to confirm no performance regression from the per-render signal.

**Handover must state:** the measured pre-discovery destination count; confirmation that all
24 deep links return 200; the failed-discovery and viewer-role case results; whether the
Ctrl+K fix shipped here or separately; and the measured per-render cost of the readiness check
on the live estate.

---

## Answers to the twelve architectural questions

1. **What is "first run"?** A workspace holding no usable discovery evidence — not a
   time-bounded onboarding session, and not a per-user flag. A five-year-old installation
   whose data was deleted is in first run again.
2. **What signal determines a usable successful discovery?** `active_scopes()` over
   `DiscoveryScope.has_data()` — already authoritative, already used by Home, correct on every
   state tested, 0.71 ms on the live estate.
3. **Should an old success keep Atlas unlocked after a new failure?** Yes, and it does so
   without special-casing: a failure writes nothing and deletes nothing.
4. **What happens after evidence is deleted/reset?** The live signal returns `False`, but the
   process latch holds the reveal until restart, after which SETUP returns. A nav that
   re-hides itself mid-session is worse than one that outlives its data by one process
   lifetime. Deleting *only* Enterprise Memory while keeping the topology snapshot stays
   revealed — the snapshot is still data.
5. **Should hidden destinations stay directly reachable?** Yes, unconditionally. All 25 tested
   routes already return 200 with real empty states; navigation is guidance, and RBAC remains
   the only access control.
6. **Where should PRISM and the Playground live?** PRISM stays at `/settings/ai` in
   Administration. The Playground keeps its `NavItem` with `sidebar=False`, keeps its URL, and
   gains a permission-gated front door inside `/settings/ai`.
7. **Minimum first-run Home copy?** One positioning sentence, one workflow sentence, one
   dominant CTA, one read-only reassurance — §7.
8. **Correct Discovery action hierarchy?** No profile ⇒ "Add discovery profile"; profile ⇒
   "Run Discovery"; running ⇒ the job panel. One primary per state.
9. **Right post-discovery transition?** Stay on `/discovery`; upgrade the panel to
   "Atlas is ready" with three counts and three next actions; reveal the nav in the same JS
   moment with focus restored.
10. **Behaviour across restart/refresh?** Derived from the filesystem plus a durable marker;
    no browser storage; identical for every user of the workspace.
11. **Can this avoid duplicating state or adding route-level access control?** Yes. No new
    source of truth (the signal already exists), no route changes, no redirects, no gates —
    one pure filter composed over the existing builder.
12. **Smallest implementation that makes G2–G5 pass?** One dataclass field, one key set, two
    small functions, two one-line render-site swaps, three template lines, and the Discovery /
    Home copy work. `visible_nav_groups`, `allowed_nav_path`, every route and every URL remain
    untouched.

---

*Evidence base: the repository at `122a891`; a pristine temporary workspace and the live
16-profile / 865-device estate, both driven through a real browser; six discovery states
reproduced on throwaway workspaces with the suite's own harness; and a 13-agent read-only
investigation whose unlock rule was put through fifteen adversarial scenarios. No repository
file was modified.*
