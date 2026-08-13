# PR-179 IMPLEMENTATION HANDOVER — When Things Go Wrong, Atlas Must Still Explain Itself

Implements the FINAL APPROVED IMPLEMENTATION PLAN (§34 of
`PR-179_FAILURE_PATHS_ARCHITECTURE_REVIEW.md`). Five steps, six commits,
all validated. **Not pushed** — awaiting review under the current
workflow.

| Commit | Step |
|---|---|
| `56498bb` | Step 1 — `web/failures.py` typed classifier + job adoption + UI action link |
| `55a6a34` | Step 2 — outcome honesty (answered-but-not-collected) |
| `a1cc1a9` | Step 3 — degraded storage keeps its voice (no 500, no silent omission) |
| `4c8d324` | Step 4 — Topology last-known-good freshness banner |
| `2b3db84` | Step 5 finding — classifier recovers the typed cause a pipeline wrapper strips |
| `2772ea1` | Step 5 finding — row 12 (strict 404) reverted as not-free; decision recorded |
| (docs)   | Step 5 — this handover + the architecture review committed together |

---

## 1. What shipped, per step

### Step 1 — the typed failure classifier (`src/founderos_atlas/web/failures.py`)

**1.** `classify(error) -> FailureVerdict(failure_class, operator_message,
diagnostic_code, severity, next_action_label, next_action_href)` is the
ONE place an exception becomes what the operator is told. Verdict
classes: `user-correctable`, `environmental`, `unsupported`,
`storage-integrity`, `internal`.

**2. The trust rule, stated exactly:** no foreign exception message is
trusted unless its **exact class** is explicitly allowlisted.
Inheritance grants nothing (pinned with a hostile
`VendorAuthenticationError` subclass carrying `password=` text — its
message never surfaces, wrapped or unwrapped). Every raise site of
every allowlisted class was audited as Atlas-authored and secret-free;
the transport layer already canonicalises foreign netmiko/paramiko
errors before they become typed exceptions.

**3.** Two allowlisted classes carry canonical copy instead of their
own words: `WorkspaceCorruptedError` (its message names filesystem
paths — never surfaced) and `CredentialStoreUnavailableError` (§6
audited the shipped sentence as correct-and-unchanged; raise sites can
be terse).

**4.** Foreign/untyped exceptions keep the pre-existing discipline:
their text only **selects** one of the legacy canonical messages
(`friendly_failure`, preserved verbatim as the fallback selector) and
is never returned, rendered, or persisted. Anything unselectable is an
INTERNAL verdict — and its traceback is finally **logged with the job
id** (`logger "atlas"`, `exc_info`), closing the support gap where an
internal failure left no diagnostic anywhere.

**5. Before → after operator message, per failure class** (before:
every row below except the three marked ✅ rendered **"Discovery failed
unexpectedly. Review the collection gaps and server diagnostics, then
retry."**):

| Failure | After (message · severity · action) |
|---|---|
| `CredentialNotFoundError` (flagship) | its own words: "No stored credential was found for this profile. Update the profile to set the password again." · warning · **Edit the profile → /profiles** |
| `CredentialStoreUnavailableError` | canonical (unchanged copy): "Secure credential storage is unavailable. Check Atlas Settings, or reinstall…" · warning · **Open Settings → /settings** |
| `AuthenticationError` ✅(was already selected by text) | its own canonical sentence, e.g. "Authentication failed for 10.0.0.1 after 1 credential attempt(s); stopping to protect the account from lockout." · warning · **Review credentials → /credentials** |
| `PermissionDeniedError` | its own words (reached, authenticated, refused a command) · warning · **Review credentials → /credentials** |
| `TransportDependencyError` | its own words (missing optional dependency + the pip extra) · warning |
| `SSHUnavailableError` | its own words ("No SSH service is reachable on …") · warning · environmental |
| `ConnectionTimeoutError` ✅ | its own words · warning · environmental |
| `ConnectionLostError` | its own words ("connection … lost while running 'show …'") · warning · environmental |
| `UnsupportedPlatformError` (both classes) | its own words incl. the capped probe first line · **neutral** — Atlas knowing it cannot collect something is not an Atlas fault |
| `WorkspaceCorruptedError` | canonical: "A stored Atlas file could not be read. Existing network evidence is unaffected; open System Integrity…" · error · **Check system integrity → /system/integrity** |
| anything else | "Atlas could not complete this discovery — an internal error occurred. Results already collected were preserved. Quote job `<id>` when reporting this." · error · traceback logged |

**6.** `DiscoveryJob` gained `failure_class`, `failure_severity`,
`next_action_label`, `next_action_href`; old persisted job records load
with `None` (pinned — the pr179 world's pre-PR job renders correctly).
The durable job log stores only the allowlisted `diagnostic_code`.

**7.** The discovery page renders the failure box server-side
(severity-mapped flash class, `role="status"`, the one next action as a
button) and `atlas.js` keeps it live during polling — verified on the
injection world: message + "Edit the profile → /profiles" present on a
fresh GET, so it survives reload by construction.

### Step 5 finding folded into Step 1 (`2b3db84`)

**8. The wrapper gap, measured live:** the pipeline re-raises failures
as `CliError(str(error)) from error`
(`founderos_runtime/cli/commands.py`), so on the real discovery path
the job layer never received the typed exception — a live seed-connect
`AuthenticationError` classified INTERNAL. The in-process Step 1
injections had called `_finish_failed` with unwrapped exceptions and
missed it. `classify()` now walks the **explicit-cause chain**
(`__cause__` only — never `__context__`) and applies the same
exact-type allowlist there. The cause instance is the very object the
audited raise site created, so the trust decision is identical, and a
wrapped hostile subclass is still refused (pinned). Verified live: the
world's real failure (missing keyring credential inside the runner) now
renders the flagship verdict end-to-end.

### Step 2 — outcome honesty (`55a6a34`)

**9. The partial-run rule:** a run is PARTIAL when devices that
**answered** could not be collected. The completion copy states
collected-of-attempted with the split: *"Collected 72 of 85 device(s)
that answered — 8 refused authentication · 2 unsupported platform(s) ·
3 could not be collected. Successful results were preserved."* The
pre-PR rule was literally `if refused:` — non-auth answered failures
(e.g. unsupported platforms) produced **"completed successfully"** (B2).

**10. Why silent addresses are excluded:** `failed_devices` counts
every per-address failure detail INCLUDING silent addresses, so the
rule never reads it directly. The answered count is derived from the
statistics split (refused + unsupported + a subtraction-derived
remainder, only when the silent count is present). Silent addresses in
a discovery sweep are **coverage, never failed devices** (PR-043.10,
§30.2): a /24 sweep holding nine devices stays a plain success, never
"245 failures" — pinned, including the no-false-partial sweep case.

**11.** A run that collected **nothing** is never called a success:
"Discovery completed — nothing was collected", with the refused/
unsupported detail and "Previously stored results were preserved."

**12.** Older summaries without the statistics keys still say nothing
rather than guess (pinned, unchanged).

**13.** `make_pipeline_runner` now carries `unsupported_platforms`
straight from the snapshot's own `discovery_statistics` — no new
aggregation. The completion warning box is `flash-warning` (was
`flash-error`): the run finished; red is reserved for failures.

**14.** PR-177 readiness unchanged: the `on_success` hook fires on
partial and even empty completions (the snapshot is already on disk) —
pinned, so a partial first run cannot strand the workspace locked. The
live "Addresses contacted" counter keeps its audited label and meaning;
collected-vs-attempted truth lives in the completion copy.

### Step 3 — degraded storage (`a1cc1a9`)

**15. Which pages now degrade instead of 500:** `/policy` (and the
result page), `/changes`, `/timeline` — a corrupt `annotations.json`
(a SECONDARY overlay file) used to 500 all three (B3). `/audit` and
`/timeline` — one bad `audit.jsonl` line used to lose the whole
chronology. `/configuration` (+ device page) and `/evidence` — a
corrupt store record used to vanish silently from a complete-looking
page. All verified live: 200 + primary data + loud banner, as
operator, investigator and viewer.

**16. A corrupt annotation store is never silently treated as healthy
or empty.** `AnnotationStore.read_all()` answers `(data, degraded)`
for render paths; the strict `all()`/`get()` keep raising for callers
that must not tolerate a partial record. The banner is loud and
specific (§30.3): *"Operator annotations could not be read.
Acknowledgements, owners, notes and suppressions are not shown, and
annotation actions are disabled so nothing overwrites the stored file.
The rows below are complete — only the annotations are missing."* +
System Integrity link — because a suppression that silently vanishes
makes hidden rows reappear as fake new problems.

**17. Annotation writes are blocked while the store is unreadable.**
Every annotation control disappears (`annotations_writable` /
`assignments_writable` template gates = permission AND readable
store), and `/changes/bulk`, `/changes/annotate`, `/policy/assign` and
the configuration-annotation route refuse with "Nothing was changed —
check System Integrity" before any byte is touched. Second line of
defence: the store re-reads before every write and raises first.
Verified live with a permitted role: refusal flashed, corrupt file
byte-for-byte untouched. Atlas never auto-repairs, resets, or deletes.

**18.** `AuditLog.events_tolerant()` skips an unparseable line and
**counts** it; `unified_audit_events_tolerant` feeds `/timeline`,
`/audit`, the changes batch-marker lookup and the CSV export. The page
states "N audit entr(ies) could not be read … every other entry is.
Nothing has been repaired or deleted." `skipped=None` (file itself
unreadable) has its own fully-degraded sentence. The strict `events()`
contract is unchanged for non-render callers.

**19.** Evidence/configuration omissions are counted and stated
(row 18): `EnterpriseMemoryStore` tracks files that exist but failed to
parse (`unreadable_count`, self-clearing on recovery), surfaced on
`/evidence`; `ConfigMemoryStore.index_unreadable()` finally
distinguishes "could not be read" from "nothing is remembered",
surfaced on `/configuration` per scope.

**20. HTTP contract:** branded 400 and 403 handlers registered in
`security.py` (the last two unbranded surfaces); Atlas-authored
`abort(..., description=…)` text passes through on 400/403/404 while
werkzeug's canned copy never surfaces; JSON callers get JSON with the
correlation id. Row 12 (strict 404 for `/configuration/<unknown>`)
was **tried and reverted as not-free** (commit `2772ea1`): device
menus on Policy/Topology legitimately render a Configuration link for
a device whose configuration is not remembered yet, and the shipped
link-integrity contract (`test_navigation`) is that a rendered link
never 404s — the full suite caught it. The honest flash-redirect
stays for that reachable-but-empty case; a truly unknown URL still
gets the branded 404.

**21.** No path, filename, or exception text reaches any page — pinned
per page (`C:\Users…`, `annotations.json`, workspace directory names
asserted absent) and re-verified live on every scenario.

### Step 4 — Topology freshness (`4c8d324`)

**22. The wording, exactly as approved (§30.4 — age AND consecutive
failures, because "as of <date>" alone quietly ages into "silently
ancient"):**

> *Showing the last successful topology, collected 10-Jul-2026 13:30
> IST (34 days ago). The latest discovery attempt for Hyderabad failed
> — 3 attempt(s) have failed since this topology was collected.
> [Open Discovery]*

**23.** Rendered only while the LATEST terminal discovery attempt for
the visible scope failed; a later success clears it (pinned end-to-end
through the real pipeline: succeed → fail → count 1 → fail → count 2 →
succeed → gone). Interrupted and cancelled runs are neither successes
nor failures and do not count. The Enterprise view names WHICH
network's attempt failed; a failure in one network never marks another
scope's view (pinned). Everything reads from the job manager's
in-memory record and the snapshot timestamp the page already loads —
no extra store scan.

**24.** The stale graph itself keeps rendering — last known good is
preserved exactly as before; only its presentation gains the truth. A
fixture snapshot with `created_at: ""` honestly renders "collected an
unrecorded time" (the real pipeline always stamps it).

---

## 2. Beta-blocker gate

**25.** **B1** — typed failures no longer collapse into one generic
sentence: allowlist verdicts + cause-chain recovery through the
pipeline wrapper, proven live on the injection world. ✔
**B2** — answered-but-uncollected devices cannot produce the
full-success message; zero-collected is never "success". ✔
**B3** — corrupt annotations cannot 500 Policy/Changes/Timeline; loud
banner; writes blocked. ✔
**B4** — Topology cannot present last-known-good without the freshness
marker (age + failed attempts). ✔

## 3. Validation record

**26. Full suite:** `PYTHONPATH="src;." pytest tests -q` — **3219
passed, 2 skipped, 924 subtests passed, 0 failed** (10:48; baseline
before PR-179: 3169 passed, 2 skipped, 924 subtests — **+50 tests, no
regressions**). New coverage: 17 classifier tests
(`test_failure_classification.py`, incl. the wrapped-cause and
wrapped-hostile-subclass pins), 6 outcome tests + a severity template
pin (`test_discovery_jobs.py`, `test_discovery_sweep_wording.py`),
22 degraded-storage tests (`test_degraded_storage.py`), 4 freshness
tests (`test_topology_freshness.py`), plus plumbing pins. Four pre-PR
pins updated deliberately, each with a PR-179 comment stating why the
new expectation is stricter (`error: internal-error` code honesty;
partial-collection headline; live auth message now the typed
canonical sentence + action fields; the policy row-selection gate
widened to permission AND readable store).

**27. Injection suite (unit level):** every allowlisted class through
the real `DiscoveryJobManager`; secret-bearing foreign errors
(`password=`, `token=`, paths) reach neither the API payload nor the
durable jobs file; INTERNAL logs traceback + job id; legacy persisted
jobs load with `None` verdict fields.

**28. Browser scenarios** (atlas-pr179 world, port 8773, password
mode, roles opsy/ivy/vera, widths 375/768/1440/1920): live failed
discovery renders the flagship verdict server-side with the action
link and zero leaks; topology freshness banner scoped + enterprise
with correct age and count; corrupt annotations → three pages 200,
loud banner, controls withheld, bulk write refused with file bytes
untouched; corrupt audit line → count stated on /audit + /timeline,
readable events still shown, export intact; corrupt configuration
index → banner, never "nothing is remembered"; branded 404 naming the
missing record; permission 403 still names the exact permission
(row 16 preserved); zero horizontal overflow and banners fit at all
four widths; every page 200 for the viewer role. World fixtures
restored; no stray servers left running.

**29. Measured-correct behaviours preserved (re-verified):** the last
good snapshot survives a failed run (world estate intact across three
failed live runs); restart → `interrupted` honestly (pinned suite);
PRISM absence still yields a deterministic answer (suite); 403 names
the permission; branded 404/409/500 with correlation id; PR-178.2 bulk
semantics (updated/unchanged/not-present truth, one correlation id,
batch collapse) — full bulk test files green; PR-178.2A scoped
identity untouched; PR-176 performance memoisation untouched (the
annotation read on /changes went from four file parses to one);
PR-177 readiness/unlock pinned on partial and empty completions.

## 4. Explicit statements (required by §34)

**30.** *No foreign exception text can reach a response.* Trust is
exact-type allowlist only, at every depth of the explicit-cause chain;
everything else at most SELECTS canonical copy and is discarded.
Pinned with hostile subclasses, wrapped and unwrapped, and with
secret-bearing foreign errors end-to-end through manager, API and
durable file.

**31.** *Silent addresses in a discovery sweep are not counted as
failed devices* — coverage, per PR-043.10, excluded from the partial
rule by construction (§30.2), pinned with the /24 sweep case.

**32.** *A corrupt annotation store is never silently treated as
healthy or empty; annotation writes are blocked while it is
unreadable; Atlas never auto-repairs, resets, or deletes user data* —
degraded reads are flagged, banners are loud and specific, write
routes refuse before touching bytes, and every scenario ends with the
corrupt file byte-identical.

**33.** *Data preservation, secret hygiene, restart reconciliation and
bulk truth are preserved unchanged* — item 29 lists the re-verified
evidence for each.

## 5. Deferred (recorded, not silently dropped)

**34.** (a) Export-emptiness copy (matrix row 11, M) — not free within
this scope; unchanged. (b) A policy evaluator-failure "could not
evaluate" seam (row-level) — no contained seam exists in the evaluator
today; recorded for a future PR. (c) 404 consistency for
`/configuration/<unknown>` (row 12, L) — tried, measured not-free
(breaks the rendered-link-never-404s contract for
not-yet-remembered devices), reverted in `2772ea1`; see item 20.
(d) The legacy-only global topology branch (default scope, no profile
scopes with data) renders no freshness banner — jobs belong to
profile scopes, so there is no job history to state; recorded.
(e) `list_recent` caps the failed-attempt count at the manager's
recent-job window (20) — an estate with more than 20 consecutive
failed runs would understate the count, never the condition. (f) Two pre-existing
thread-timing tests (`test_discovery_modes.py` wizard GUI;
`test_discovery_jobs.py` latency opt-in) each flaked ONCE while a
second pytest process ran concurrently on the same machine; both pass
standalone, in their modules, and in the final clean full run —
recorded as load-sensitive, not PR-179 regressions.
