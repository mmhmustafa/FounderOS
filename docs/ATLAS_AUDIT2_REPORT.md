# Atlas Audit-2 Remediation Report — GO/NO-GO

Date: 2026-07-19 · Scope: the eleven audit-2 corrections after the seven
UX-simplification prompts · Verification: full automated suite plus a
real-browser pass against a live server carrying the real workspace data.

## Decision: GO

No blocker or high-severity finding remains open. Every GO criterion is
met and evidenced below. Nothing was committed or pushed.

## Findings and dispositions (severity-ranked)

### 1. HIGH — Topology layer persistence broke under authentication (fixed)

The viewer posted to `/api/preferences/ui` with no CSRF header and no
credentials: it worked in local mode and returned 403 in password mode
while the UI silently pretended the choice was saved.

- The viewer (`visualization/templates/topology.html`) now sends
  `X-Atlas-CSRF` from the readable `atlas_csrf` cookie with
  `credentials: 'same-origin'`, and reports 401/403/network/malformed
  responses in a visible `role="status"` note — it never claims a save
  that did not happen. Server-side CSRF enforcement is untouched.
- `tests/test_authenticated_ui_preferences.py` (6 tests): the exact wire
  protocol persists for a password-mode viewer; the old un-headered call
  is refused with 403; per-user isolation across reauth; proxy-mode
  isolation; local-mode persistence across restart; and a source-contract
  test pinning header + credentials + honest failure text.
- Browser pass: layer save round-trips on the live server and the saved
  state survives reload.

### 2. HIGH — Home said "Degraded" and "Nothing needs your attention" (fixed)

Canonical health is now authoritative for attention.
`web/mission.py::attention_from_health` turns every critical, degraded,
or stale dimension into an attention item with conclusion, evidence
(counts), severity, and a filtered action link. Documented rules:
unknown/unavailable never become tasks; discovery-freshness defers to
per-contribution recommendations when those exist. "Nothing needs your
attention" renders only when no actionable condition exists.
Simple mode shows at most three items with the rest one disclosure away.

- `tests/test_home_hierarchy.py::HealthAttentionConsistencyTests`.
- Browser pass on real data: status banner Degraded, eight attention
  actions (Run Discovery ×4, Open Topology, Open Configuration, Review
  Policy, Review Changes), zero occurrences of the contradiction.

### 3. Display-level adoption breadth (completed)

The level now shapes every operational page through two uniform,
server-rendered mechanisms — content is never removed, only collapsed:

- Every adopted table applies Simple/Detailed/Expert column presets from
  the user's level on load (16 tables, list under finding 4).
- Every GET filter bar (Audit, Changes ×2 incl. compare, Incidents,
  Paths, Policy, Timeline) sits in a `<details>` disclosure collapsed at
  Simple, open at Detailed/Expert. POST action forms are deliberately
  never collapsed behind a "Filters" summary
  (`tests/test_table_adoption.py::FilterDisclosureTests`).
- Level never changes permissions, evidence, exports, or calculations
  (`test_display_levels.py::test_rbac_is_identical_in_every_display_mode`).

### 4. Table simplification breadth (completed)

The column-customization engine was upgraded so ONLY the `<thead>` needs
markers: body cells hide by column position, rows using colspans keep
their layout, toggle labels come from `data-col-label` (never whitespace
headings), the initial preset is a view and writes no preference, and a
refused save shows a visible note instead of silently claiming success.

Adopted with stable IDs and presets: `audit-events`, `users`,
`discoveries`, `changes`, `incidents`, `config-devices`, `credentials`,
`profiles`, `path-history`, `predictions`, `compass-plans`,
`retention-preview`, `inbox`, `policy-results`, `policy-packs`,
`evidence-devices`. Exports remain server-side and independent of
visible columns; every adopted grid sits in a labelled, focusable
scroll region (the missing one on policy-packs was found in the browser
pass and fixed). `tests/test_table_adoption.py` (6 tests) pins all of it.

Browser proof: at Simple, detailed/expert columns are hidden in both
head and body; toggling a column back on persists
`{"hidden": ["delta","reason","correlation"]}` server-side per user.

### 5. Guided workflow adoption (completed)

- Add credential: Basic path is set, label, username, password,
  priority; scoping and lifecycle live in an Advanced disclosure with
  `data-remember="workflow:credential-advanced"`. Only the open/closed
  state is remembered — never secret values; drafts continue to exclude
  passwords everywhere.
- Discovery wizard candidate preview and the Discovery page's two log
  disclosures remember their state per user.
- A validation error inside a collapsed section auto-opens it and
  focuses the field (existing `invalid` capture handler, verified).
- Reauth, confirmation phrases, RBAC, CSRF, conflict detection, and
  audit records are untouched (365 credential/wizard/workflow tests).

### 6. Dark theme (completed)

Semantic tokens with `body[data-theme="dark"]` overrides across buttons,
forms, tables, cards, chips, flashes, code blocks, diffs, and nav; the
theme propagates into the topology iframe (`theme=dark` observed on the
live iframe src) and the viewer paints dark chrome.
`tests/test_theme_contrast.py` computes WCAG contrast from the parsed
tokens and fails the suite if any pair drops below AA.

### 7. Compact density (completed)

Compact tightens table, form, card, list, filter-bar, and nav spacing
(`td` padding 5px 8px observed live) with a `@media (pointer: coarse)`
floor so touch targets never shrink below accessible minimums.

### 8. Settings ownership honesty (fixed)

Settings now separates "Personal preferences" (display level, saved
topology layers, table columns — genuinely per-user) from "Workspace
preferences" (timezone, theme, density, retention, logging — labelled as
shared policy requiring settings-manage). No destructive migration.

### 9. Presentation polish (fixed)

Predict headings no longer render `None`; Home activity and Evidence
timestamps flow through the central `| timestamp` filter (stored UTC is
never rewritten); the expert-mode onboarding note is dismissible and
only shows for migrated-default experts.

### 10. Home performance (fixed): warm ~3.05 s → ~65 ms

Profiling (not guessing) showed 4.4 s of every Home render was the
policy engine re-reading the entire evidence store (480 evaluations,
~1,500 index-file reads). `policy_summary_for` now caches the summary
keyed on a fingerprint of the store's four mutable index files plus the
Atlas version. Blobs are content-addressed and immutable, so any
evidence write changes an index stamp and deterministically invalidates
the cache. The value is derived workspace data identical for every
operator — nothing user-specific enters the evaluation or the key, so
nothing can leak between users.

- Measured on real data: warm Home 53–75 ms (target < 750 ms); Evidence
  and Policy unchanged.
- `tests/test_home_policy_cache.py`: unchanged store never re-evaluates;
  a touched index file always does.

### 11. Hermetic suite (fixed)

The two CLI startup tests run under a temporary `ATLAS_HOME` and no
longer touch the operator's real workspace. The single-instance lock is
NOT weakened: a new test proves a second real process on the same
workspace is refused (`WorkspaceLockRefusalTests`, real subprocess).
The full suite was executed while a normal Atlas server was serving the
real workspace on 127.0.0.1:8765.

## Quality gates

- Full automated suite: **1872 passed, 2 skipped, 468 subtests passed**
  in 8m50s — executed while the normal Atlas server was serving the real
  workspace on 127.0.0.1:8765 (the hermeticity condition itself). The
  two template fixes found during the browser pass afterwards were
  covered by re-running the policy/evidence suites (223 passed) and the
  adoption suite (6 passed) on the final tree.
- CSP/inline-handler and secret-canary checks: part of the suite.
- `git diff --check`: clean.
- Dependency policy: `paramiko==4.0.0` advisory PYSEC-2026-2858 /
  CVE-2026-44405 remains explicit and governed in
  `security/vulnerability-exceptions.json`; its exception still expires
  **2026-10-18** with compensating controls and an upgrade gate. It was
  not suppressed.

## Browser verification matrix (live server, new code, real data)

| Axis | Verified |
|---|---|
| Modes | Local: full interactive pass. Password/proxy: wire-protocol and isolation proven by `test_authenticated_ui_preferences.py` and `test_display_levels.py` (Password/Proxy classes). |
| Levels | Simple and Expert interactively (columns, filters, disclosures); Detailed via preset tests. |
| Theme | Dark verified live incl. iframe propagation; Light/System via token tests. |
| Density | Compact verified live; Comfortable is the default baseline. |
| Widths | 375 (no horizontal overflow, scroll regions take the width) and native desktop; wide tables scroll inside labelled regions at every width. |
| Console | Zero errors during the whole pass. |

## Constraints honoured

No functionality, evidence, route, export, action, RBAC rule, CSRF
enforcement, audit record, confirmation safeguard, topology capability,
or provenance was removed. No preference is ever silently claimed as
saved. Nothing was committed or pushed.
