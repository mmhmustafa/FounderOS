# Atlas Inbox Actionability Report — Assignment Notifications

Date: 2026-07-19 · Objective: every assignment notification identifies
its subject, and every Open action lands on the exact object or a
persistent, server-resolved assignment batch.

## Decision: GO

All assignment notification types now identify their subject; every
Open action reaches the exact object or a shareable, restart-persistent,
permission-checked batch view. Automated and real-browser evidence
below. Full suite: **1895 passed, 2 skipped, 468 subtests passed**
(10m26s), including the 17 new assignment tests.

## Root cause

`/policy/assign` emitted a notification that carried only a count
("1 policy result(s) assigned to you") and reused the operator's *return
URL* as the Open link — a generic, filter-losing page with no connection
to the assigned rows. Nothing recorded which annotations belonged to an
assignment event in a queryable way: the correlation id went to the
audit log only, so no page could reconstruct the batch. Change
assignments had the same defect ("A change was assigned to you" →
generic /changes).

## Notification types corrected

| Type | Before | After |
|---|---|---|
| Policy, single | count only → generic /policy | `Policy assigned: <policy> on <device>` + verdict/severity/scope/assigner detail → exact `/policy/result/<policy_id>/<hostname>?scope=<scope>` |
| Policy, bulk | count only → generic /policy | one notification: count, first-3 preview, "and N more", scope, assigner → `/policy?assignment=<correlation>&scope=<scope>` |
| Change | "A change was assigned to you" → generic /changes | `Change assigned: <what> on <device>` + severity/network/assigner → device-filtered /changes with the row's own anchor |
| Incident | already exact (title + case link) | unchanged; duplicate-notification guard added |
| Approval request | already exact (plan title + link) | unchanged |

## URL / filter contracts (new)

- `?owner=<name>` — exact owner filter.
- `?mine=1` — resolved to the **authenticated principal on the server**;
  the URL never carries an identity.
- `?assignment=<correlation>` — the assignment batch, resolved from the
  audited `policy-assignment` annotations, which now carry
  `correlation` and `batch_size` alongside `owner` (single source of
  truth; no duplicated assignment data). All three ride
  `ResultFilter.to_args()`, so pagination, grouping, and CSV export
  preserve them automatically; they render as removable chips.

Opening a batch shows the "Assignment received" banner (assigner,
timestamp, current match count), marks each batch row with an accent
inset **plus a text badge** (never color alone), offers "Clear
assignment filter", and — when results were since reassigned or removed
— states "N of the originally assigned M result(s) no longer carry this
assignment", with the audit log named as the full history.

## Reassignment behavior

Historical notification text is never rewritten. The batch view shows
current state honestly (verified live: 5 assigned → 1 reassigned →
banner reports 4 matching, 1 moved on). Repeating an identical
assignment (same owner, no change) is audited but emits **no** duplicate
unread notification — policy, change, and incident paths all guard this.

## Security decisions

- `mine=1` resolves server-side from the principal; a client-supplied
  `owner` is only ever a filter, never an identity assertion.
- The assignment filter *narrows* rows the caller is already authorized
  to see — a guessed correlation id reveals nothing beyond the caller's
  existing policy-view permission, and unauthenticated access to
  `/policy?assignment=…` fails closed to login (tested).
- Per-recipient isolation unchanged and tested for two users.
- Hrefs built via `url_for` / `scoped_url` (safe encoding); correlation
  ids are server-generated hex; no subject lists in URLs; bulk detail is
  bounded (3 previews + remainder, < 600 chars regardless of batch
  size). No secrets in titles, details, URLs, audit records, or logs.
- CSRF on `/policy/assign`, `/changes/annotate`, `/inbox/<id>` is
  untouched and exercised by the existing security suite.

## Inbox presentation

Simple: identifying title, status, Open. Detailed: + severity/scope/
assigner line. Expert: + correlation id (`<code>`), for audit
cross-reference. Internal identifiers stay out of Simple.

## Exact files changed

- `src/founderos_atlas/policy/explorer.py` — ResultFilter owner/mine/
  assignment; assignment metadata on rows; filter matching.
- `src/founderos_atlas/web/routes.py` — `_scope_from_next`,
  `_resolve_identity_filters`, rewritten `policy_assign`, banner context
  in `policy_page`, identity-resolved export, richer change-assignment
  notification.
- `src/founderos_atlas/web/lifecycle_routes.py` — incident duplicate-
  notification guard.
- `src/founderos_atlas/web/templates/policy.html` — banner, owner/mine/
  assignment filter controls, chips, row markers, honest empty state.
- `src/founderos_atlas/web/templates/inbox.html` — display-level
  disclosure.
- `src/founderos_atlas/web/static/atlas.css` — token-only banner and
  row-marker styles (correct in light, dark, and the System mirror with
  no theme-specific rules).
- `tests/test_assignment_notifications.py` — new, 17 tests.

## Automated tests

17 new tests across 6 classes: single identification + exact link; bulk
conciseness + exact batch + boundedness; filter round-trip through
pagination/export; restart persistence; principal-resolved `mine`
(local, password, proxy); honest empty batch; reassignment honesty; no
duplicate on identical reassignment; special-character safety;
notification lifecycle; two-user isolation; unauthenticated fail-closed.
All 17 pass; the 232-test policy/inbox/change/incident set passes.

## Browser coverage (live server, real workspace data)

- Assigned one result to `local-operator` via the page's own form: Inbox
  title "Policy assigned: AAA Present on access1", Open →
  `/policy/result/STD-AAA-001/access1?scope=all`, exact verdict page.
- Bulk-assigned 5: one notification, Open → batch URL, banner
  "5 policy result(s) assigned by local-operator on 19-Jul-2026 IST",
  exactly 5 of 480 rows shown, all marked, removable chip.
- Reassigned one to `priya`: historical batch honestly reports
  "1 of the originally assigned 5…"; priya received exactly one
  identifying notification with an exact-verdict link; recipients see
  only their own items.
- Read → Done → Include done lifecycle verified.
- Display levels: Simple (title only) / Detailed (+detail) / Expert
  (+correlation) verified live.
- Widths 375/768/1440/1920: no horizontal overflow anywhere.
- Dark theme: banner at 14.4:1 contrast; light theme covered by token
  tests. Zero console errors; every network request 200/304.
- Two authenticated users in a real browser were exercised via the
  automated password-mode client tests (`MultiUserSecurityTests`)
  rather than a manual dual-login browser session — the isolation
  contract is identical.

## Remaining limitations

- A policy×device subject that evaluates in more than one network shows
  one row per network in a batch view (each genuinely carries the
  assignment); the banner counts rows, the notification counts subjects.
- The change-assignment link filters to the device and anchors the row;
  if the change ages off the report, the operator lands on the filtered
  changes list (with its own honest empty state) — change rows have no
  standalone detail page to link instead.
- `production_world` has no discovery data, so password/proxy-mode
  assertions exercise the filter/identity contract rather than rendered
  policy rows (local mode covers those end-to-end).

## Worktree state

Dirty by design — this feature plus the earlier dark-theme fixes are
uncommitted, awaiting an explicit commit request. `git diff --check`
clean.
