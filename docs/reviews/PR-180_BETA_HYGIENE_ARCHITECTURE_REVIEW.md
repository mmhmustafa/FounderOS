# PR-180 — BETA HYGIENE ARCHITECTURE REVIEW

**Make Atlas safe, legible and supportable in someone else's hands.**

*Audit + beta-hygiene review + architecture. Nothing implemented, no code modified, no commit.
Source of truth: HEAD `bd50303`, the running application (four scratch worlds, three roles, four
widths), the repository, PR-175's External Beta Readiness Review, and the shipped state of
PR-176…PR-179.*

---

## 1. Executive diagnosis

**Atlas is closer to beta-supportable than the PR-175 backlog implies, and the residual gaps are
not the ones that were predicted.** Of 104 measured findings, **39 are NO CHANGE REQUIRED** —
including four of the five items PR-175 assigned to PR-180, which later PRs closed incidentally.
There are **no BLOCKERs**: this build can go to an external tester today. What it cannot yet do is
*support* that tester well.

The predicted work has largely evaporated:

- **A diagnostics export already exists.** `GET /settings/diagnostics.json` returns 25+ runtime
  facts as an attachment, Settings offers both **Download diagnostics** and a one-click **Copy
  diagnostics** clipboard button (`settings.html:83`, `atlas.js:967-981`), and the download is
  audited. The Copy-Diagnostics question is therefore not "build it" but "trust it".
- **The zoom regression did not return.** `wheelSensitivity: 0.15`, `minZoom 0.05`, `maxZoom 3` —
  one wheel notch is **1.148×**, ~30 notches across the range, with a code comment that argues the
  arithmetic and a test pinning the value to `[0.05, 0.35]`.
- **Focus visibility is solved globally.** One `:focus-visible` rule covers
  `a, button, input, select, textarea, summary, [tabindex]`; measured live with a real Tab press:
  `2px solid #2563eb`, `:focus-visible` matching.
- **A topology legend exists** (Physical / Verified routed / Routing adjacency / BGP peering /
  device roles incl. *Unresolved peer*), with an accessible name.
- **Ctrl+K is exemplary**: opens, focuses the input, `role="dialog"` + `aria-modal`, Escape closes
  **and restores focus to the invoking element with a visible ring**.
- **Touch targets are mostly right**: `--touch-target: 44px` and an `@media (pointer: coarse)`
  block already lift the whole `.btn` family to 44px.
- **Row menus, accessible names, colour-plus-text status, landmarks and skip-links** all pass.

What remains is a coherent theme, and it is not cosmetic: **Atlas can fail in ways it cannot help
you report.** The six HIGH findings are all of that shape — a notification whose job id the route
ignores; a bulk failure that produces no id, no log line and no audit event; a restore that never
says what it replaces; a first screen dominated by a framework's red warning; a recovery
instruction that tells the tester to type a command that does not exist; and no log file anywhere,
so the correlation ids PR-179 built point at lines that live only in a terminal scrollback.

Against that, the second theme is **identity**: the product knows exactly which build it is and
tells almost nobody. Version renders on two admin-only surfaces. A non-admin tester — measured
across 14 pages — can reach **no** build identity anywhere, and the Settings page shows them a
"System information" jump link whose anchor they never receive.

The governing constraint on all of it comes from the adversarial pass, and it is stricter than the
brief's: **no PR-180 change may add a filesystem path, a user account name, a hostname, a device or
management address, or an operator-authored network/site/profile name to any artifact that can
leave the machine.** Support identity is carried by non-reversible fingerprints and correlation ids
only.

---

## 2. Current PR-180 audit matrix

Re-audited at HEAD. Severity is beta-facing: **BLOCKER** = do not hand this build over.

| # | Area | Measured state at HEAD | Sev |
|---|---|---|---|
| 1 | Version visibility | Two surfaces, both `system.admin`. Non-admin roles: nothing, on 14 measured pages | MED |
| 2 | `build_commit()` cost | Uncached `git rev-parse` subprocess, **twice per `/settings` render**; 39–47 ms/call measured, 5 s timeout each | MED |
| 3 | Build-identity trust | Hash printed for a **dirty tree** and for a **foreign parent repo**; describes bytes the process may never have run | HIGH |
| 4 | Beta/channel label | Zero occurrences product-wide; `0.3.0a1` rendered raw | MED |
| 5 | Diagnostics payload shape | `{**system_info, …, "preferences": preferences.__dict__}` — spread, not allowlist | HIGH |
| 6 | Diagnostics content | No workspace identity, no scope, no discovery state — cannot answer "topology is wrong" | MED |
| 7 | Diagnostics notice | No in-artifact statement of what it contains; Settings copy describes the *backup*, not this file | HIGH |
| 8 | `/discovery?job=` | Notification emits it; the route reads only `?profile=` — dead parameter | HIGH |
| 9 | Bulk internal failure | No id, no `logger.exception`, no audit event; 302 hides it from the 500 handler | HIGH |
| 10 | Restore metadata | Never says it replaces accounts, audit log, annotations, incidents, profiles | HIGH |
| 11 | Startup first screen | Framework's bold-red "development server" warning is the most prominent text | HIGH¹ |
| 12 | Port-in-use recovery | Tells the tester to run `atlas web --port N`; the only console script is `founderos` | HIGH |
| 13 | Log file | None anywhere; stderr only, `propagate = False` | HIGH¹ |
| 14 | Grid checkboxes | 13×13 native, no coarse rule, no enlarged hit area — the bulk-triage entry point | LOW² |
| 15 | `.chip-remove` | 16×17 px and destructive | LOW² |
| 16 | Topology legend | Exists, but `display:none` at `level=simple` — the level a fresh workspace gets | MED |
| 17 | Unresolved peers | Header counts them; the layer that draws them ships **off**; definition only behind `?support=1` | MED |
| 18 | Topology tile definitions | Canonical count definitions live only in `title=` on a non-focusable div; copy says "hover any tile" | MED |
| 19 | `_device_actions.html` | Unavailability reasons + certificate warning in `title=` on a `disabled` button — unreachable by keyboard | MED |
| 20 | Ctrl+K selection | Arrow-key selection is a 1.12:1 tint and nothing else | MED |
| 21 | "Local development mode" | On every page, in the default posture — build vocabulary for a security fact | MED |
| 22 | Provider class name | Credentials page prints `type(provider).__name__` while Settings prints a friendly label | MED |
| 23 | Retention copy | Settings says retention never deletes; another card ships the feature that does | MED |
| 24 | Backup blurb | Lists exclusions; never says user accounts **with password hashes** are included | MED |
| 25 | Console "Disconnect" | Ends another named operator's live SSH session, one unconfirmed click | MED³ |
| 26 | Integrity link 403 | Five degraded banners offer "Check System Integrity"; the route is `system.admin` | MED |
| 27 | Sample console | `/discovery/console` reachable, unlinked, **self-labelled** "Sample walkthrough… not one of your networks" | LOW |
| 28 | Zoom/wheel | 1.148× per notch, bounded 0.05–3, test-pinned | **NONE** |
| 29 | Focus ring | One global `:focus-visible`, verified live | **NONE** |
| 30 | Ctrl+K a11y | dialog + modal + label + focus restore | **NONE** |
| 31 | Landmarks/skip-link | Present and correct | **NONE** |
| 32 | Paths on normal pages | Zero across 12 pages for a non-admin | **NONE** |
| 33 | Credential redisplay | No `value=` on any password input; PRISM key is a boolean on the wire | **NONE** |
| 34 | Confirm substrate | `web/confirmation.py` — server-verified, signed, path-bound, JS-free; no `confirm(` in any template | **NONE** |
| 35 | Already-running defence | TCP probe + OS instance lock, two layers | **NONE** |

¹ Reclassified by the adversarial pass — see §25/§26. ² Reclassified from MEDIUM. ³ Split: copy in
PR-180, the missing ownership check filed separately.

**PR-175's five PR-180 assignments, re-audited:** version+build in header/footer → *still open,
reshaped*; explain "unresolved peer identities" → *partly solved (legend exists), gap is the
hidden layer*; sub-32px touch targets → *solved except two controls*; focus parity for 27
hover-only rules → *solved globally; three template residues remain*; skip-links/landmarks on
dense pages → **solved, no action**.

---

## 3. Version / build architecture

**Authoritative source:** `release.py:22` — `VERSION = "0.3.0a1"`, a single literal, wired into
`pyproject.toml` dynamically, consumed by the CLI, backups, evidence records, enterprise memory
and startup logs. **No duplicate literal exists anywhere.** This is already right; do not touch it.

**The build identifier is the problem, and the fix is a rule, not a widget.** Reproduced by the
adversarial pass: `build_commit()` resolves `Path(__file__).parents[2]`, so an Atlas installed
inside *another* project's checkout reports **that project's** HEAD; and on a dirty working tree it
reports a commit that does not describe the running bytes. Both failures are invisible in the
artifact — a screenshot, a diagnostics file and a log line all look identical whether the hash is
true or meaningless.

> **The build-identity rule.** Atlas prints a build identifier only when it can prove the
> identifier describes the running bytes — the tree is **clean** (`git describe --dirty` empty)
> **and** the repository is **this package's**. Otherwise it prints the causeless
> `not available in this build`.

This is the same principle PR-179 already enforces for exception text ("only ever *selects*
canonical copy") and the same principle §8 states for identifiers. A missing value announces its
own absence; a wrong value announces confidence.

**Mechanics (smallest form):**

1. `@lru_cache(maxsize=1)` on `build_commit()` — the commit cannot legitimately change within a
   process, and `register_observability` already primes it at startup, so the cached value is the
   commit the process loaded. Land this **first**; a test must pin the priming order so a future
   refactor cannot silently invert the honesty property.
2. Switch to `git describe --always --dirty` (or `rev-parse` + `status --porcelain`) and suppress
   the value when dirty; compare the discovered repo to this package before trusting it.
3. A single `BUILD_ID` seam: `ATLAS_BUILD_ID` env var → generated `_build_id.py` → git → `None`.
   Packaged builds inject; git checkouts derive; neither branch is packaging *work* in PR-180 —
   only the seam and its fallback.

**Where it is visible:** one operator-facing location (the persistent chrome line, §4) carrying
`DISPLAY_VERSION` only, and one diagnostic location (the `system.admin` Settings card, the CLI,
`diagnostics.json`) carrying the build identifier. **A commit hash never enters shared chrome.**

---

## 4. Beta / channel labelling

`0.3.0a1` is a Python packaging convention; a network engineer does not read `a1` as "pre-release".
Nothing in the product says beta.

**Decision:** one word, in the version line itself, nowhere else. Rendered as
**`FounderOS Atlas 0.3.0a1 · Beta`**. No banner, no modal, no per-page chrome tax, no interstitial.

**Derivation:** an anchored PEP 440 test — `re.search(r"(a|b|rc)\d+$", VERSION.split("+")[0])` or
`packaging.version.Version(VERSION).is_prerelease` — **never** a substring scan (`'a' in version`
labels `0.3.0.dev1` a finished release and `1.0.0+build.5` a pre-release). Do not introduce the
word "channel": it implies update infrastructure Atlas deliberately does not have.

---

## 5. Support / diagnostic context

The reported case — *"Topology is wrong"* — needs five facts. Measured availability today:

| Fact | Exists? | Source |
|---|---|---|
| Product + version | ✅ | `system_info["display_version"]` |
| Build identifier | ⚠️ (trust rule §3) | `release.build_commit()` |
| Workspace schema | ✅ | `applied_version` / `CURRENT_SCHEMA_VERSION` |
| **Which workspace** | ❌ | — |
| **Which scope/profile** | ❌ | — |
| **Last discovery status + time** | ❌ | `job_manager().list_recent()` (already in the process) |
| Integrity state | ✅ (separate page) | `/system/integrity` |
| Correlation id | ✅ | error page / `X-Request-ID` |
| Host platform | ❌ | not computed anywhere |

So the artifact proves the build and the schema, and cannot say which network it describes. That is
the whole gap — roughly five keys, all from values Atlas already holds.

---

## 6. Copy-diagnostics decision

Of the four options, the answer is **D-plus**: *no new feature — the existing one is completed and
made trustworthy.* Download + Copy already exist and are audited. PR-180 adds keys, a notice, and
an allowlist; it does not add a bundle, a zip, or a new surface.

**Included** (all non-identifying): `_notice`; product, version, display_version, pre-release flag,
build identifier (or its causeless absence); workspace schema applied/target;
`workspace_fingerprint` = `sha256(workspace_root)[:12]`; `active_scope_fingerprint` +
`active_scope_kind` ∈ {enterprise, profile, default}; `last_discovery` = **explicit literal**
`{status, finished_at, profile_fingerprint}`; `failed_attempts_since_success`; authentication mode;
credential-provider *friendly name* + availability; TLS/HSTS booleans; trusted-proxy **count**;
session mode; schema/logging level; retention policy; update-provider state; host platform as
exactly `f"{platform.system()} {platform.release()}"`; `python`; `profile_count`; `generated_at`.

**Excluded, permanently:** every filesystem path (workspace root, output dir, history root, log
path); user account names; hostnames — `platform.node()`, `platform.uname()`,
`socket.gethostname()`, `os.getlogin()` are forbidden by name; device or management addresses;
profile/site/network display names; trusted-proxy *addresses*; credential material of any kind;
raw configuration; `preferences.__dict__`; and anything reachable by a `**spread`.

---

## 7. Secret / privacy contract

Measured: **no password input carries `value=`**; drafts are filtered at three layers; the PRISM API
key crosses the wire as a boolean; configuration and evidence exports are wholesale-redacted;
zero filesystem paths on twelve primary pages for a non-admin; every deliberate path exposure is
`system.admin`-gated; diagnostics.json today contains **no** path (the Settings paths are separate
template variables). This is genuinely strong and mostly finished.

The three live hazards are structural, not present leaks:

1. **The spread.** `payload = {**system_info, …, preferences.__dict__}` means any field added later
   to `system_info` or `WorkspacePreferences` silently joins a support artifact. **Convert to an
   explicit allowlist with an exact-key-set test *before* adding any key.** This amendment is the
   precondition for every other diagnostics change in this PR.
2. **Raw exception text in two places** — a settings-save `OSError` flashed verbatim (an `OSError`'s
   `str()` carries its filename), and the CLI's `except (RuntimeError, OSError)` interpolating
   `{error}` into a terminal message. Both must follow the PR-179 pattern: canonical copy to the
   human, `logger.exception` for the detail.
3. **The provider class name** on the Credentials page — not a secret, but it tells a tester
   `InMemoryCredentialProvider` where Settings says "in-memory (non-persistent; test/development
   only)". The friendly mapping already exists.

---

## 8. Correlation-id rule

Two namespaces exist: request correlation `req-<16 hex>` and job id `uuid4().hex[:12]`, plus
`bulk:<uuid>` batch correlation. Exactly two surfaces tell a tester to quote an id today, and both
are correct.

> **The rule.** Show an identifier **iff** the failure is `internal`-class *and* the product can
> resolve that identifier later. Never print an id Atlas cannot look up; never decorate a
> user-correctable failure with one.

Corollaries, applied only to the sites already identified: the bulk internal failure **gains** an id
(and a `logger.exception`); the 400/404/429 pages **lose** theirs (they name a user-correctable
condition — an id there is noise the tester may waste a paragraph quoting). Implement the error-page
switch as `hide_correlation=True` on those three, not `show_correlation=True` on the rest, so a
future call site fails toward *showing* a resolvable id. The full sweep is recorded, not performed.

---

## 9. Settings / About design

**No new page, no `/about` route.** Settings already has the right shape: a `system.admin`
"System information" card plus a diagnostics card. PR-180 changes four lines and adds two:

- Version line gains the pre-release token (§4).
- Build-commit line obeys the trust rule and uses **one** causeless fallback string, unified with
  `system_update.html` (today they disagree).
- Diagnostics card gains one muted sentence stating what the file contains **before** the click.
- Backup blurb gains the inclusion it currently omits: *user accounts (with password hashes)*.
- Restore disclosure gains prose naming what is replaced, in categories, plus the two facts the
  operator currently learns too late — Atlas snapshots first, and a restart is required.
- The retention contradiction is corrected to point at the shipped control.

The page-head "System information" jump link must be gated to the roles that receive the section.

---

## 10. Workspace identity treatment

**On screen (admin only):** the raw path stays exactly where it is — an operator who owns the
machine deserves to know where their data lives.

**In any artifact that leaves the machine:** `workspace_fingerprint` = first 12 hex of
`sha256(workspace_root)` — stable across exports from one tester, correlatable by support,
non-reversible, and free of the OS username that `C:\Users\<name>\…` carries. Same treatment for
scope: `active_scope_fingerprint` + `active_scope_kind`.

Do not build the multi-workspace manager. Do not name the workspace after a profile.

---

## 11. Topology orientation and help

Three small, specific gaps — no redesign, no tutorial:

1. **The legend is hidden exactly when it is needed.** A fresh workspace resolves to
   `display_level = simple`, and `body[data-level="simple"] #legend { display: none }`. The
   first-time tester gets solid/dashed/dotted lines and six node colours with no key.
   *Fix (amended):* wrap the legend body in a `<details>` closed at `simple`, open otherwise — the
   key becomes reachable without leaving the map and the first-glance composition survives.
   (Also hidden below 480px; acceptable, and the `<details>` form improves it.)
2. **Unresolved peers are counted but not drawn.** The header states "N unresolved peer identities"
   while the layer that renders them ships **off**, and the term is defined only behind `?support=1`.
   *Fix (amended):* set the summary's canonical definition from `vocabulary.py` via a property
   assignment (never `innerHTML` — that data is device-controlled), and state the hidden/shown fact
   in the **Layers panel beside the switch**, derived from live checkbox state — never as a static
   parenthetical baked in at load.
3. **Canonical count definitions are hover-only** on a non-focusable div, and the page tells the
   user to hover. *Fix (amended):* one `<details>Canonical definitions</details>` list below the
   grid, and delete the "hover any tile" sentence — not seven per-tile edits.

Control labels and accessible names in the generated viewer are already correct (Fit all, Reset
view, Zoom in/out one step, Lens, Layers, Legend, Export, Search, view level, layout).

---

## 12. Zoom / scroll regression result

**NO ACTION.** Measured in the delivered artifact:

```
minZoom 0.05 · maxZoom 3 · wheelSensitivity 0.15
zoom × 10^(deltaY / −250 × wheelSensitivity)  →  one 100px notch = 1.148×  (~30 notches across range)
```

The PR-117 tuning survived the PR-174.1 re-deletion attempt; the code comment argues arithmetic
rather than taste, and a test pins the value to `[0.05, 0.35]`. The regression has not returned.

---

## 13. Touch-target audit

`--touch-target: 44px` and `@media (pointer: coarse)` already lift the entire `.btn` family to 44px
on touch devices. **Measurement caveat that changes the conclusion:** narrowing a desktop browser to
375px does **not** activate coarse-pointer rules, so live fine-pointer numbers understate what a
tablet gets. Measured live at 375px (fine pointer), against static CSS for coarse:

| Control | Fine @375 | Coarse | Verdict |
|---|---|---|---|
| Row menu trigger | 59×44 | 44 | ✅ (PR-178.1) |
| `.btn` / pager / filter chips | 27–39 h | 44 | ✅ |
| Columns disclosure | 74×30 | 44 | ✅ |
| Nav toggle / search | 44×44 | 44 | ✅ |
| **Grid checkboxes (row-select, select-all)** | **13×13** | **13×13** | ❌ no rule covers them |
| **`.chip-remove`** | 16×17 | 16×17 | ❌ destructive and smallest in the sheet |
| Column-picker label rows | 177×20 | 20 | ⚠️ marginal |
| `.inbox-link` | 28×28 | 28 | ⚠️ acceptable |

Only the two ❌ rows are materially problematic — and the first is the entry point to PR-178.2 bulk
triage. Fix with **one selector added to the existing coarse block**, using the existing
`--control-height-sm` token; land it together with the dead `input[type="checkbox"] + span`
selector cleanup. Do not inflate anything else.

---

## 14. Keyboard audit

Measured live, with real key events:

- Global `:focus-visible` ring (`2px solid #2563eb`, offset 2px) covering every interactive
  element type — **verified with an actual Tab press**, `:focus-visible` matching. ✅
- Ctrl+K: opens, focuses the input, `role="dialog"` + `aria-modal="true"` + label; **Escape closes
  and returns focus to the invoking element with the ring visible.** ✅
- Skip-link → `<main id="atlas-main" tabindex="-1">`, `nav aria-label="Workflows"`. ✅
- Row action menus are native `<details>`/`<summary>` (PR-178.1). ✅

Three residues, all template-level: the Ctrl+K **search input's** focus ring is suppressed by a
later rule; Evidence's saved-filter Rename puts `role="button"` on a `<summary>` (destroying the
expanded/collapsed announcement — delete one attribute); and `_device_actions.html`'s `disabled`
button hides its computed reason from every keyboard user (`disabled` removes it from the tab
order, so `title` can never fire).

---

## 15. Hover-only / accessible-name audit

The icon system enforces names (`_icons.html` emits `role="img" aria-label`, decorative icons are
`aria-hidden focusable="false"`), `.visually-hidden` is real and used, and status badges pair colour
with text everywhere measured. The remaining hover-only meaning is four items, all listed above:
`_device_actions.html` (×3 — it never received the treatment its sibling `_entity_actions.html`
shipped), the topology tile definitions, the Ctrl+K 1.12:1 selection tint, and the topology site
filter's colour-only "active" state (add `aria-current`).

---

## 16. Developer / test artifact audit

The GUI is substantially clean: **no** TODO/FIXME/debugger/`console.log` in any Atlas-authored
template or JS; no traceback reaches a page; the failure classifier discards foreign text by design.

| Hit | Classification |
|---|---|
| `/discovery/console` — reachable, unlinked, renders a fabricated "Delhi Lab" | **GATE (keep)** — it self-labels: *"Sample walkthrough… it is not one of your networks, and the controls do not act on a live run."* Deleting it is its own PR, and would have to delete two test references in the same commit. |
| "PRISM Playground" | **INTENTIONAL** — an advanced surface, correctly located |
| `type(provider).__name__` on Credentials | **REMOVE/RENAME** — friendly mapping exists |
| `type(error).__name__` in three schedule messages + `schedule_worker_last_error` | **REMOVE/RENAME** — canonical sentences stand alone |
| "Local development mode" in the sidebar, every page | **RENAME** — it describes a *security posture* in *build* vocabulary. `Single-operator access · loopback only` keeps the load-bearing half. |
| BGP/OSPF/CDP/LLDP/VRF/SSH/netmiko | **INTENTIONAL** — do not sanitize engineering vocabulary |

---

## 17. Startup / runtime hygiene

Good already: a two-layer already-running defence (TCP probe + OS instance lock), migrations run
and are audited, discovery threads are daemons, Ctrl+C exits cleanly.

Product-hygiene items (PR-180):

- **The recovery instruction is wrong.** `atlas web --port 8766` — the only console script is
  `founderos`. One string edit: `founderos atlas web --port {port + 1}`. Do **not** add an `atlas`
  alias; that is packaging.
- **Raw tracebacks escape** on bind failures the probe cannot predict (`--port 80`, a race, an
  exclusive socket) and on non-`RuntimeError/OSError` startup failures. Widen the catch, **narrow
  the message**: canonical copy plus `errno` to the terminal, `logger.exception` for the detail —
  never interpolate the exception (an `OSError` carries its filename).
- **Where results go is never stated.** `output_dir` defaults to the current working directory, so
  starting from a different folder silently yields an empty history. Print the resolved directory
  as a startup line — terminal and admin Settings only; it must never enter diagnostics, a flash,
  an error page or a log line.
- **The first screen** is dominated by Werkzeug's bold-red "development server" warning.
  *Adjudicated against the audit's proposal:* **keep the warning** — it is true, and hiding a true
  statement to look finished is precisely what this PR must not do. Ship the ordering fix instead:
  Atlas's own closing line after the handoff (URL + storage location + `Press Ctrl+C to stop
  Atlas.`), and, if the duplicate access log is intolerable, a `logging.Filter` on *access records
  only* — never a blanket level change.

---

## 18. Destructive-action language audit

The substrate is excellent: `web/confirmation.py` provides a server-verified, signed, path-bound,
JS-free confirm page, wired into profile delete/archive, credential delete, user delete, incident
unlink, advisor deletion and both draft-discard paths. There is not one `confirm(` in any template.

Three copy defects, no lifecycle changes:

1. **Restore metadata** never says what it replaces (accounts *with password hashes*, audit log,
   annotations, incidents, profiles, policy exceptions, schedules), nor that Atlas snapshots first,
   nor that a restart is required. Categories, not filenames.
2. **Backup blurb** lists exclusions and omits the one inclusion an attacker would want.
3. **Settings contradicts itself** on retention: one card says nothing is deleted "in this phase",
   another ships the control that deletes.

Console **Disconnect** ends another named operator's live session with one unconfirmed click:
PR-180 ships the label/title naming operator and device; the missing ownership/permission check is
filed as its own security finding — an authz gap is never closed with a dialog.

**PR-178.2A profile-deletion semantics are NOT misrepresented by the current copy** — no change.

---

## 19. Packaging-readiness boundary

**Product hygiene (PR-180):** version constant and its single source; a `BUILD_ID` seam with an
honest fallback; the build-identity trust rule; diagnostics allowlist + notice; correlation-id
rule; startup messages that name the URL, the storage location and a real recovery command;
no developer paths in the UI.

**Packaging work (explicitly deferred, recorded):** the `atlas` console-script alias; build-id
injection at package time; a log **file** with rotation, redaction and a stable location; log
retention policy; an installed-build date; update delivery, signing and entitlement; the
`output_dir` default relocation to `atlas_home()` (it would strand every existing tester's
history — a migration question, not a hygiene one).

---

## 20. Current beta-gate recheck

| Gate item | Verdict at HEAD |
|---|---|
| No obvious developer artifacts | **PASS** — one self-labelled sample surface, one class name, one vocabulary rename |
| Responsive UI | **PASS** — zero horizontal overflow at 375/768/1440/1920 |
| Accessibility | **PASS with residue** — focus, names, landmarks, colour+text all pass; four hover-only items remain |
| Version visibility | **FAIL for non-admin roles** — the one gate item PR-180 must close |
| Diagnostics / supportability | **PARTIAL** — export exists; identity, notice and allowlist missing |
| Topology comprehensibility | **PARTIAL** — legend exists but hidden at the default level |
| No silent runtime failures | **PARTIAL** — bulk internal failure is silent to support |
| No secrets in user-facing errors | **PASS** (PR-179), with two raw-exception paths to canonicalize |

---

## 21. Remaining blockers

**None.** No finding meets the bar of *do not hand this build to an external tester*. The six HIGH
items are supportability defects that make the first bad day expensive, not unsafe. Two carry the
most weight and should lead the implementation: the **bulk internal failure with no identifier**
and the **dead `?job=` deep link**, because both occur at the exact moment a tester is trying to
tell us something went wrong.

---

## 22. Risks

1. **Diagnostics scope creep** — every added key is permanent egress surface. Mitigated by the
   allowlist + exact-key-set test landing *first*.
2. **Chrome tax** — version, channel and posture are three temptations to add three lines to every
   page. Mitigated: **one** line, reviewed as one change.
3. **Per-request cost** — the PR-176 lesson. `build_commit()` is a subprocess on a page render
   today; the cache must land before version identity spreads anywhere else.
4. **Honesty inversion** — a cached or packaged build identifier that describes bytes the process
   never ran is worse than no identifier. Mitigated by the trust rule and the priming test.
5. **Packaging leakage** — a log file is the single most likely item to be smuggled in as hygiene.
   Deferred explicitly.
6. **Over-correction on the startup warning** — suppressing a true statement to look polished.
   Rejected above.

---

## 23. Test strategy

**Version/build** — (1) `DISPLAY_VERSION` renders for every role on a normal page; (2) the build
identifier renders on the admin card and the CLI; (3) non-git / packaged fallback returns the
single causeless string and never raises; (4) **no** repository path in any rendered output;
(5) a dirty tree suppresses the identifier; (6) a foreign parent repo suppresses it;
(7) `GET /settings` spawns **no** subprocess after startup; (8) `build_commit()` is primed before
the first request; (9) shared chrome contains no commit hash; (10) `founderos version` carries the
identifier, `founderos help` does not.

**Diagnostics** — (11) `set(payload) == EXPECTED_KEYS` exactly (the guard test); (12) no value
matches a path separator, `AppData`, `/home/`, the user's home, or `%TEMP%`; (13) no password,
token or private key substring; (14) `last_discovery` has exactly `{status, finished_at,
profile_fingerprint}`; (15) fingerprints are stable across two calls and differ across workspaces;
(16) `_notice` is present and first; (17) `preferences` is a named-field dict, not `__dict__`.

**Correlation** — (18) the bulk internal failure flashes an id **and** logs `exc_info`;
(19) `JsonLineFormatter` emits the exception *class name* only, never a traceback;
(20) `/discovery?job=<valid>` renders that job; (21) `?job=<malformed>` is treated as absent;
(22) `?job=<well-formed unknown>` says so and shows no other job; (23) 400/404/429 hide the id,
500 shows it.

**Topology** — (24) the legend is reachable at `level=simple`; (25) every control has an accessible
name; (26) wheel sensitivity stays within `[0.05, 0.35]` (existing pin); (27) PR-179 freshness
wording unchanged.

**Accessibility/touch** — (28) grid checkboxes and `.chip-remove` meet the coarse-pointer minimum;
(29) `_device_actions.html` exposes its reasons to assistive tech; (30) no `role="button"` on a
`<summary>`; (31) the Ctrl+K active row has a non-colour indicator; (32) focus ring present on the
search input.

**Artifacts/copy** — (33) no `type(...).__name__` reaches a template; (34) "Local development mode"
is gone and the loopback fact survives; (35) the sample console keeps its self-label; (36) restore
prose names the categories; (37) backup blurb names the hash inclusion; (38) retention copy is
consistent; (39) the port-in-use message contains `founderos atlas web --port`.

**Regression** — (40) PR-179 failure messages and freshness banners byte-identical; (41) PR-178.2
bulk truth unchanged; (42) PR-177 first-run unchanged; (43) no horizontal overflow at four widths;
(44) full suite green (baseline **3219 passed, 2 skipped, 924 subtests**).

---

## 24. Browser-validation strategy

At 375 / 768 / 1440 / 1920, with mouse, keyboard and a coarse-pointer emulation (required — a
narrow desktop window does **not** activate the touch rules):

Settings/About (version + channel + diagnostics notice, admin and non-admin) · Topology (legend at
`simple`, unresolved-peer statement, controls by keyboard) · Ctrl+K (open, arrow, Enter, Escape,
focus restoration, visible selection) · Discovery (`?job=` deep link: valid, malformed, unknown) ·
one dense table (grid checkbox target under coarse pointer, bulk bar, row menu) · one degraded
state (corrupt annotations banner + the gated integrity link for a non-admin) · the bulk internal
failure flash carrying its id · a 500 page carrying the version and the id · a 404 page carrying
neither.

---

## 25. Adversarial review findings

Three hostile lenses attacked the draft. What landed:

1. **Path egress, in the direction the draft was careless about.** The draft proposed adding
   `workspace_root` to `diagnostics.json` on the reasoning that the path is *already* on screen for
   the same admin. **Refuted:** a screen is a consent surface, an exported file is a portable
   artifact — and the path carries the OS username. Fingerprint only.
2. **The spread is the real defect, not the missing keys.** `{**system_info, …,
   preferences.__dict__}` makes every "additive keys are safe" claim in the review unfounded until
   an allowlist exists. Reclassified **HIGH**, and made a precondition.
3. **The log-file proposal fails the leakage test as written.** `request.path` carries device ids
   and hostnames; an unfiltered on-disk artifact would durably record the tester's estate. Both
   lenses rejected it — one as a leak, one as packaging. **Deferred**, with the honest sentence
   shipped instead.
4. **Suppressing the Werkzeug warning hides a true statement.** Rejected; ordering fix only.
5. **`'a' in VERSION` is not a pre-release test.** It mislabels `0.3.0.dev1` as a finished release.
   Anchored regex or `packaging.version`.
6. **A dirty tree or a foreign parent repo makes the hash a lie**, and the lie is unfalsifiable
   from the artifact. This produced the §3 trust rule and is the single most important amendment in
   the review.
7. **`base.html:131-135` is not "every page".** It sits inside `{% if not bare_chrome %}`, so the
   login and failed-login screens — the highest-frequency first bug report — would not show the
   version; and below 1024px the sidebar is a drawer. Placement corrected.
8. **Severity inflation.** Touch targets and the startup screen were reclassified down; the review's
   own "no BLOCKER" claim was challenged and survived, but only once the standing rule (§26.1) was
   adopted.
9. **Duplicate findings** (provider class name ×2, `build_commit` cost ×2) merged.

What did **not** change the plan: the zoom result, the focus-ring result, the Ctrl+K result, the
confirmation-substrate result, the credential-redisplay result, and the decision to keep the
self-labelled sample console.

---

## 26. Required amendments

1. **Standing rule (governs every item):** no change may add a filesystem path, user account name,
   hostname, device/management address, or operator-authored network/site/profile name to any
   artifact that can leave the machine — `diagnostics.json`, the clipboard copy, a log line, a
   flash, an error page or a CLI message. Identity is fingerprints and correlation ids only.
2. Diagnostics **allowlist + exact-key-set test lands before any new key**.
3. Diagnostics `_notice` first key, plus one pre-click sentence in Settings.
4. Build identifier obeys the **trust rule**; `lru_cache` lands first with a priming-order test.
5. Pre-release detection is anchored; the word is **Beta**; "channel" is not introduced.
6. Version in chrome = `DISPLAY_VERSION` only, guarded on an identified principal, one line,
   merged with the posture rewording; **never** the commit hash.
7. Log file **deferred to packaging**; ship the honest sentence.
8. Werkzeug warning **kept**; ordering and a closing line only.
9. `?job=` fix validates the id (`^[0-9a-f]{12}$`), and an unknown-but-well-formed id says so
   rather than silently showing a different job.
10. Bulk failure copy drops the invented cause; the id is interpolated at flash time.
11. Restore/backup prose uses `backup.py`'s own phrasing — *user accounts (with password hashes)*.
12. Touch-target fixes reclassified **LOW** and landed with the dead-selector cleanup.
13. Topology: legend becomes a `<details>`; the unresolved-peer state is derived from live layer
    state, never a static parenthetical; tile definitions become one `<details>` list.
14. Console Disconnect: copy in PR-180; the ownership check filed separately.
15. Error-page id flag is **inverted** (`hide_correlation` on 400/404/429).

---

## 27. Recommended PR scope

**In:** version identity and its trust rule; one chrome line (version · Beta · posture);
diagnostics allowlist + notice + five identity/state keys; correlation-id rule applied to the two
identified sites; `?job=` deep link; bulk failure id + log; startup message corrections
(`founderos atlas web --port`, storage location, closing line, canonical bind/startup errors);
seven copy fixes (restore, backup, retention, provider name, posture, schedule error suffixes,
integrity-link gating); four accessibility residues; two touch targets; three topology
explanation fixes.

**Out:** everything in §28.

---

## 28. Explicit non-goals

No page/navigation/first-run redesign. No change to bulk semantics, discovery architecture, change
identity, or the PR-179 failure contract. No Windows packaging, installer, update delivery, code
signing, entitlement or licensing. No telemetry SaaS. No frontend framework. No tutorial overlay.
No new page (`/about` is rejected — Settings already holds it). No log file. No multi-workspace
manager. No credential-storage redesign. No profile-deletion lifecycle change. No sanitizing of
engineering vocabulary. No deletion of the sample console in this PR.

---

## 29. Success criteria

An external tester can answer, without Atlas exposing credentials, secrets, filesystem internals or
debug noise: **What version am I running?** (every page, every role) · **Is this a beta build?**
(one word, in the version line) · **What workspace is this?** (a fingerprint they can quote) ·
**What do I send you?** (Copy diagnostics — and it says what it contains before they click) ·
**What does this control mean?** (the legend is reachable at the default level) · **Can I use it by
keyboard and touch?** (yes, including the bulk-selection checkbox) · **Is this a real product
surface?** (yes — and the one sample surface says so itself).

And when something goes wrong, the failure hands them an identifier that Atlas can actually
resolve — including the two cases where it currently hands them nothing.

---

## 30. FINAL APPROVED IMPLEMENTATION PLAN

**Step 0 — the guard rails (must land first, nothing else depends on being second).**
`@lru_cache` on `build_commit()` + priming-order test; convert `diagnostics.json` to an explicit
allowlist with the exact-key-set test and named `preferences` fields; write the standing rule
(§26.1) into the review and the test names. *No user-visible change yet.*

**Step 1 — build identity you can trust.** Apply the trust rule (`describe --dirty` + repository
identity, suppress otherwise); unify the causeless fallback string across both templates; add the
`ATLAS_BUILD_ID` → generated-file → git seam; append the identifier to `founderos version` (not to
`help`). *Tests 3–10.*

**Step 2 — one line of chrome.** `DISPLAY_VERSION · Beta` (anchored pre-release detection) rendered
for every role via a template global, guarded on an identified principal and placed so it survives
`bare_chrome`; the sidebar posture line becomes `Single-operator access · loopback only`; the
Settings jump link is gated to the roles that receive the section. *Tests 1, 2, 9, 34.*

**Step 3 — make the support artifact answer the question.** Add `_notice`, workspace/scope
fingerprints, `last_discovery` (literal construction), `failed_attempts_since_success`, host
platform; one pre-click sentence beside the buttons. *Tests 11–17.*

**Step 4 — failures that can be reported.** Bulk internal failure: `logger.exception` + id in the
flash, copy without an invented cause; `/discovery?job=` honoured with validation and an honest
miss; error-page id flag inverted. *Tests 18–23.*

**Step 5 — startup truth.** `founderos atlas web --port N`; canonical bind/startup errors with
`errno` and a logged traceback; print the resolved storage location and a closing line; keep the
framework warning. *Tests 39, and the CLI pins.*

**Step 6 — comprehension and reach.** Topology: legend `<details>`, canonical definitions
`<details>`, unresolved-peer state from live layer state, `aria-current` on the site filter.
Accessibility: `_device_actions.html` visually-hidden reasons, drop `role="button"` from the
Evidence summary, Ctrl+K active-row indicator + input focus ring. Touch: grid checkboxes and
`.chip-remove` in the coarse block, with the dead-selector cleanup. *Tests 24–32.*

**Step 7 — copy corrections.** Restore prose; backup inclusion; retention contradiction; provider
friendly name (promote `_provider_name` to public); schedule error-type suffixes; integrity-link
gating via one `_degraded.html` macro; console Disconnect label. *Tests 33–38.*

**Step 8 — validate.** Full suite against the 3219/2/924 baseline; the browser matrix of §24 at four
widths including a coarse-pointer pass; confirm PR-176 budgets, PR-177 first-run, PR-178.2 bulk
truth and PR-179 failure/freshness wording are untouched; then the **PR-175 gate re-audit**, which
is the next PR, not this one.

**Sequencing rule:** Steps 0 and 1 are prerequisites for Step 2 and Step 3. Steps 4–7 are
independent of each other and may land in any order. No step may add a field to a leaving artifact
without a corresponding assertion in the exact-key-set test.

---

*Evidence base: HEAD `bd50303`; ten parallel read-only repository audits (104 findings, 0 blockers,
6 HIGH, 39 NO CHANGE REQUIRED) and three adversarial lenses (leakage, scope-creep, build-identity)
that reproduced the dirty-tree, foreign-repo, absent-git, worktree and PEP 440 cases directly; live
measurement of four scratch worlds across three roles and four widths, including a real Tab/Ctrl+K/
Escape traversal, per-control bounding boxes on a dense table, the delivered topology artifact's
zoom arithmetic, and a 14-page sweep for version, beta and path exposure. No repository file was
modified.*
