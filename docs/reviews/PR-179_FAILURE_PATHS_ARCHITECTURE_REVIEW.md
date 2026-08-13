# PR-179 — Failure Paths

**When Things Go Wrong, Atlas Must Still Explain Itself.**
*Audit + failure-mode review + recovery architecture. No code was modified. Nothing was committed.*

Measured against HEAD `b60d80c` (post-PR-178.2) with deterministic failure injection through the
real job manager, the real Flask stack, and a live password-mode server.

---

## 1. Executive diagnosis

**Atlas's failure infrastructure is far better than its failure *messages*.** Almost everything a
trustworthy failure story needs already exists and is already correct:

- The last known good snapshot **survives a failed run** (measured: 3 devices → 3 devices, Home
  still renders the estate).
- **Nothing leaks.** No traceback, exception class, filesystem path or secret reached any job
  payload or error page in any injection.
- **Restart reconciliation is honest**: active jobs become `interrupted` with "Atlas restarted
  while this discovery was running… run discovery again." No job can be stuck running forever.
- **Partial discovery is already modelled with real data**: the run separates *refused
  credentials* from *silent addresses*, and the snapshot carries
  `discovery_completeness_percent`, `authentication_failures`, `authenticated`, `reachable`.
- **Failure text persists** across reload — the failed job's message is server-rendered into
  `/discovery`, not just flashed.
- **PRISM failure is already isolated**: with no provider configured, `/advisor` returns a full
  deterministic answer with confidence and unknowns.
- **Permission denial is precise**: *"Your roles do not include the permission required for this
  operation (discovery.run)."*
- 404 / 409 / 500 all render branded pages with a correlation id and no internal detail.

And then one function throws most of it away.

> **`friendly_failure()` (web/jobs.py:166) classifies failures by lowercase substring match on the
> exception's text, not by its type.** Atlas has a rich typed hierarchy —
> `AuthenticationError`, `ConnectionTimeoutError`, `SSHUnavailableError`,
> `UnsupportedPlatformError`, `PermissionDeniedError`, `ConnectionLostError`,
> `TransportDependencyError`, `CredentialNotFoundError` — and three substring branches.
> Everything else becomes: *"Discovery failed unexpectedly. Review the collection gaps and server
> diagnostics, then retry."*

The clearest measured instance, reproduced end-to-end on a live server:

| | |
|---|---|
| **Atlas actually knew** | `CredentialNotFoundError: "No stored credential was found for this profile. Update the profile to set the password again."` |
| **Atlas actually said** | *"Discovery failed unexpectedly. Review the collection gaps and server diagnostics, then retry."* |

A perfectly-worded, secret-free, user-correctable message — replaced with a non-answer that sends
the operator to "server diagnostics" for a problem they could fix in fifteen seconds.

**The shape of PR-179 is therefore not "add error handling". It is: stop discarding what Atlas
already knows.** That is a small, contained change, and it fixes most of the beta blockers.

Two further defects are structural rather than cosmetic: a corrupt *annotation* file takes down
three primary pages with a 500, and Topology renders yesterday's graph with no staleness marker
after a failed run.

---

## 2. Complete failure matrix

Severity: **B** = beta blocker, **H** = high, **M** = medium, **L** = low. "Measured" = injected
and observed; "Code" = verified by reading the path.

| # | Surface | Failure | Current behaviour | Current message | Data preserved? | Next action? | Problem | Proposed | Sev |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Discovery | Missing stored credential (`CredentialNotFoundError`) | job `failed`, stage "Preparing discovery" (measured) | "Discovery failed unexpectedly…" | yes | none | The real message existed and was discarded | Trust the typed failure; show "No stored credential…" + **Edit profile** | **B** |
| 2 | Discovery | No credential scoped to a device (`AuthenticationError`, "No credential applies to…") | job `failed` | "Discovery failed unexpectedly…" | yes | none | User-correctable shown as unexpected | Show the raised guidance + **Credentials** | **B** |
| 3 | Discovery | Device unreachable (`SSHUnavailableError`, `ConnectionTimeoutError` from the reachability probe: *"did not answer a reachability probe on any management port"*) | job `failed` | "Discovery failed unexpectedly…" | yes | none | **Operator cannot tell "unreachable" from "Atlas broke"** — the single most operationally critical distinction | "Atlas could not reach <host>…" + check-path guidance | **B** |
| 4 | Discovery | Unsupported platform (`UnsupportedPlatformError`) | job `failed` | "Discovery failed unexpectedly…" | yes | none | **Unsupported rendered as failure**; the raised text already lists supported platforms | "Atlas does not recognise this device" + supported list, neutral severity | **B** |
| 5 | Discovery | Internal defect (e.g. `KeyError`) | job `failed` | *identical wording to #3* | yes | none | Operator cannot separate "my network" from "your bug" | Distinct internal-error copy + correlation id; log with traceback | **B** |
| 6 | Discovery | Devices fail for non-auth reasons (unreachable/unsupported) with `auth_failed == 0` | `completed`, **no warning**, "Discovery completed successfully" (Code: `_finish_completed`, `if refused:`) | "…completed successfully" | yes | — | **Partial failure presented as full success** | Warn whenever any device was attempted and not collected | **B** |
| 7 | Storage | `annotations.json` invalid JSON | `WorkspaceCorruptedError` → **500** on `/policy`, `/changes`, `/timeline` (measured) | branded 500 + correlation id | yes (evidence/topology fine) | "server diagnostics" | A secondary overlay file takes down three primary pages | Degrade: render data, banner "operator annotations unreadable", link `/system/integrity` | **B** |
| 8 | Storage | `audit.jsonl` truncated/garbage line | **500** on `/timeline` and `/audit` (measured) | branded 500 | yes | as above | One bad line loses the whole chronology | Skip unparseable lines, count them, say so | **H** |
| 9 | Topology | Fresh run failed; last-good graph shown | renders yesterday's graph, **no "stale"/"as of" marker** (measured) | none | yes | none | **Old data can be mistaken for current** on the most authoritative visual | Freshness banner naming the last successful run + the failed attempt | **B** |
| 10 | Discovery | Job counters on a failed run | `devices_discovered` counts hosts *attempted* via `_on_connect` (Code; measured 1 in-process, 0 live) | "1 device" on a run that stored none | — | — | Overstates what was learned | Report attempted vs collected separately | M |
| 11 | Export | Filtered set is empty | 200 + header-only CSV (measured, `/changes/export.csv`) | none | — | — | An empty file downloads as success | Say "0 rows match" before generating, or include a stated basis line | M |
| 12 | HTTP | `/configuration/<unknown>` | 302 + flash (measured) while `/devices/<unknown>` → 404 | flash | — | back to list | Inconsistent not-found semantics | Keep 404 for unknown records | L |
| 13 | Discovery | Cancel | `cancelled` + "stopped at the operator's request", checked before start (Code) | correct | yes | — | — | Preserve | — |
| 14 | Discovery | Restart mid-run | `interrupted` + honest text (Code) | correct | yes | rerun | — | Preserve | — |
| 15 | Bulk | Audit-block write fails | pre-image restored, "…nothing was changed" (PR-178.2, pinned) | correct | yes | retry | — | Preserve | — |
| 16 | Authz | Missing permission | 403 naming the exact permission (measured) | correct | — | — | — | Preserve | — |
| 17 | PRISM | No provider / provider down | deterministic answer still served; page names PRISM and "unavailable" (measured) | correct | yes | configure | — | Preserve | — |
| 18 | Evidence/Config | One stored record corrupt | pages still 200 (measured) | silent | yes | — | Corrupt record silently omitted from a complete-looking table | Count and state omissions | H |

---

## 3. Failure taxonomy

The brief's nine classes survive contact with the repository, with one amendment: **C (partial
collection) is not a failure class at all — it is an outcome class**, and conflating them is
exactly defect #6. The taxonomy Atlas should use:

| Class | Meaning | Severity | Example (real, from this audit) |
|---|---|---|---|
| **A — user-correctable** | Atlas knows what to change | warning + action | `CredentialNotFoundError`; no credential scoped to host |
| **B — environmental** | The network, not Atlas | warning + check-path | reachability probe unanswered; SSH unavailable |
| **D — unsupported** | Atlas knows it cannot | **neutral, never red** | `UnsupportedPlatformError` (names the supported list) |
| **E — stale / insufficient** | Data exists, freshness or coverage is short | warning | last-good snapshot after a failed run |
| **F — internal** | Atlas's own defect | error + correlation id | `KeyError` in a collector |
| **G — external provider** | PRISM/API | neutral; core unaffected | provider unset (already correct) |
| **H — permission** | Not allowed | **neutral, not failure** | 403 naming the permission (already correct) |
| **I — conflict / stale subject** | The world moved | neutral | PR-178.2 `NOT_PRESENT` (already correct) |
| **J — storage integrity** *(new)* | A stored file is unreadable | degraded per surface | corrupt `annotations.json` |

Class **J** is added because the repository has a distinct behaviour (a raised
`WorkspaceCorruptedError`) with distinct recovery (`/system/integrity`) that none of the brief's
classes described.

**Outcome classes for a completed operation** (orthogonal to the above):
`COLLECTED · REFUSED · UNREACHABLE · UNSUPPORTED · SILENT (no device) · NOT ATTEMPTED`.

---

## 4. Discovery failure architecture

Keep the job model exactly as it is — statuses, persistence, cancellation, restart
reconciliation are all correct. Change **one boundary**:

```
pipeline raises a TYPED failure
        ↓
classify(exception)  ← by type first, message second
        ↓
FailureVerdict(class, operator_message, next_action, diagnostic_code, severity)
        ↓
job.error / job.warning / job.next_action  (no raw text, ever)
```

`classify()` replaces `friendly_failure()`'s substring ladder with a type table, falling back to
today's substring rules only for untyped exceptions crossing an adapter boundary. Crucially:
**when a typed Atlas exception already carries an operator-safe message, that message is used**
— these are written for operators (they say "Update the profile to set the password again"), and
they are the reason the fix is small. Untyped/foreign exceptions keep the current allowlist
discipline: their text is used only to *select* a message, never shown.

`FailureVerdict.next_action` is a link Atlas already has (`/profiles`, `/credentials`,
`/settings/ai`, `/system/integrity`, "Run discovery") — no new destinations are invented.

## 5. Partial-discovery contract

**Definition:** a run is `PARTIAL` when it completed its pipeline *and* the attempted set is
larger than the collected set. Every input already exists in the snapshot's
`discovery_statistics` (measured: `authenticated`, `authentication_failures`,
`discovery_completeness_percent`, `reachable`, `addresses_scanned`, `unused_addresses`).

| Run | Today | Proposed |
|---|---|---|
| 72/72 collected | "completed successfully" | unchanged |
| 72 collected, 8 refused, 3 unreachable, 2 unsupported | "**completed successfully**" unless auth>0 | "**Collected 72 of 85 devices** · 8 refused credentials · 3 unreachable · 2 unsupported" |
| 0 collected, all refused | "completed with warnings" | "**Collected nothing** — 85 devices refused the credentials" (a failure in operator terms) |
| pipeline raised | "Discovery failed" | unchanged + the real reason (§4) |

No new aggregation is computed: the numbers are read from the run's own statistics, exactly as
the completion panel already reads `addresses_scanned` and `auth_failed_devices`. **A run that
collected nothing is never called a success**; a run that collected most of the estate is never
called a failure.

## 6. Credential/authentication failure contract

Atlas must distinguish five conditions that today collapse into two:

| Condition | Today | Proposed operator message | Action |
|---|---|---|---|
| Credentials rejected by a device | ✅ correct | unchanged | Edit credentials |
| **No stored credential for the profile** | ❌ generic | "No stored credential was found for this profile." *(its own words)* | Edit profile |
| **No credential scoped to a device** | ❌ generic | "No credential applies to <host>…" *(its own words)* | Credentials |
| Credential backend unavailable | ✅ correct | unchanged | Settings |
| Privilege/enable refused (`PermissionDeniedError`) | ❌ generic | "<host> accepted the credentials but refused a command (privilege level)." | Credentials |

Secret hygiene is already correct and must be preserved verbatim: exception text is used to
*select* a message and is never returned or persisted; the durable job log stores only an
allowlisted `diagnostic_code`. **Measured: zero leaks across every injection.**

## 7. Connectivity failure contract

`SSHUnavailableError`, the reachability-probe `ConnectionTimeoutError`, and `ConnectionLostError`
each get their own message. The operator-critical sentence — *"Atlas reached this address but the
credentials were refused"* vs *"nothing answered at this address"* — already exists for the
per-device sweep (refused vs silent) and must simply extend to whole-run failures.

## 8. Retry/recovery model

**Audited: Atlas supports whole-run retry only.** There is no per-device retry, no failed-subset
rerun. Say so plainly rather than implying more:

- Whole-run retry: the existing **Run Discovery** button (already correct).
- "Fix and rerun": every user-correctable verdict carries a link to the thing to fix.
- Per-device retry is **explicitly out of scope** — it needs a targeted-discovery capability the
  pipeline does not have, and inventing it here would be a new orchestration layer the brief
  forbids. Recorded as a future PR.

## 9. Last-known-good / stale-data model

**Measured: last-good is already preserved on failure** — snapshot intact, Home renders, and Home
already carries "as of", "last discovery", "stale" and "fresh" language. The gap is not
preservation; it is **labelling on the pages that don't label**.

The contract:

> A page may serve last-known-good data whenever it says *when* that data was collected and
> *that the newest attempt did not succeed*. It may never present it as current.

| Page | Freshness today | Proposed |
|---|---|---|
| Home | "as of" / "stale" (measured present) | unchanged |
| **Topology** | **none** (measured: no "stale", no "as of") | freshness line + failed-attempt note |
| Policy / Evidence / Configuration | evidence freshness per row (PR-178) | unchanged |
| Advisor / Investigate | confidence + unknowns | unchanged |

One shared, cheap component: a **degraded-state banner** rendered from facts the page already
has (the latest job outcome + the snapshot timestamp), reused by Topology first and available to
any page. No new stores, no new computation per row.

## 10–14. Degraded-state models per surface

**Topology (10)** — must state: the graph is from run X at time T; the newest attempt failed/was
partial; which scopes contributed. Never a blank canvas without a reason. Measured today:
renders correctly but silently.

**Policy (11)** — PR-178's honesty already distinguishes *Not scored* / *missing evidence* /
*unknown* / *non-compliant*. The one addition: when the *evaluator itself* fails or a policy pack
is unreadable, that must read as **"could not evaluate"**, never as *Not scored* (which means
"nothing to score") and never as compliant.

**Evidence (12)** — the trust surface. Measured: a corrupt record leaves pages at 200 and the
record silently missing. **Any omission must be counted and stated** ("2 records could not be
read"), because a complete-looking evidence table that is quietly incomplete is the worst failure
Atlas can have.

**Configuration (13)** — three distinct states already exist in the data and must not merge:
*not collected* (the profile did not ask) · *collection failed* (asked, refused) · *unsupported
for this platform*.

**Advisor / Investigate (14)** — already bounded (confidence, unknowns, "not enough evidence").
Preserve; the only requirement is that a *stale* input is named as stale in the answer's basis,
which the evidence layer already tracks.

## 15. PRISM / provider failure model

Measured correct and to be preserved: the deterministic answer is produced first and never lost;
the page distinguishes Atlas from the provider; no key material appears. Additions are limited to
naming the provider-side condition (not configured / rejected the key / rate-limited / timed out
/ unreadable response) and keeping the failure **neutral** — a missing optional provider is not
an Atlas fault.

## 16. Bulk-operation failure model

PR-178.2 shipped this and it is pinned: compensating restore on audit failure, honest
per-subject counts, `NOT_PRESENT` for vanished subjects, no partial success claimed. **PR-179
changes nothing here** beyond ensuring the failure copy uses the shared vocabulary.

## 17. Export failure model

Generation must precede the download decision: a failed generation returns to the page with a
reason rather than serving a broken file, and an **empty** result is stated ("0 rows match this
filter") rather than downloading a header-only file as success (measured).

## 18. Startup / storage-corruption model

| File | Today | Proposed |
|---|---|---|
| `annotations.json` corrupt | **500** on 3 pages (measured) | pages render; banner names the unreadable overlay; annotations treated as absent |
| `audit.jsonl` bad line | **500** on 2 pages (measured) | skip and count unparseable lines |
| `topology_snapshot.json` truncated | pages still 200 (measured) | unchanged |
| evidence/config record corrupt | silently omitted (measured) | counted and stated (§12) |
| workspace schema | migration ladder with backups (PR-178.2A) | unchanged |

**Nothing is ever auto-deleted or auto-reset.** Recovery is: state the damage, keep serving what
is readable, and point at `/system/integrity` (which already exists and already names
corruption).

## 19. HTTP / error-page model

Measured: 404, 409, 500 are branded, carry a correlation id, leak nothing, and 500 logs with
`exc_info`. 401 redirects to login; 403 is precise. Remaining work is small: register **400** and
**403** handlers so a bare `abort()` cannot fall through to a Werkzeug default page, and make
unknown-record routes consistently 404 rather than a 302 + flash.

## 20. Safe exception-mapping model

One module, `web/failures.py` (name illustrative), owning `FailureVerdict` and `classify()`, used
by the job layer first and available to any other surface. It is the only place that reads
exception text, and it never returns it. This is the one abstraction the audit justifies: the
same classification is needed by discovery today and by scheduled runs and connection tests
already present in the repository.

## 21. Logging / diagnostics model

Already strong: structured JSON logs with correlation id, actor, endpoint, status, duration; 500s
logged with traceback; audit denials recorded with roles and outcome. The one gap: **when a
verdict falls through to the internal-error class, the underlying exception must be logged with
its traceback and correlation id** — today the generic branch produces a user message and a
`discovery-failed` code with no technical detail anywhere, so support cannot diagnose a defect
that a user reports. Nothing sensitive is added to logs.

## 22. Empty / error / unknown / unsupported / stale / partial semantics

| State | Means | Colour | Today's main conflations |
|---|---|---|---|
| EMPTY | nothing exists; valid | neutral | — (PR-178 fixed the big ones) |
| ERROR | attempted, failed | red | — |
| UNKNOWN | Atlas cannot tell | amber | — |
| UNSUPPORTED | Atlas knows it cannot | **neutral** | **shown as ERROR** (#4) |
| STALE | old data, still useful | amber | **shown as CURRENT on Topology** (#9) |
| PARTIAL | some succeeded | amber | **shown as SUCCESS** (#6) |

## 23. Accessibility model

Failure banners use `role="alert"` only for a failure the operator just caused (a submit that
failed); background/asynchronous outcomes use `role="status"` (the discovery panel's existing
pattern). Severity is never colour-only — every state carries a word. Focus moves to the failure
summary after a failed submit; the retry/fix control is a real link or button in the tab order.

## 24. Responsive model

Failure banners are prose in the existing card/flash components, already fluid; the only specific
risk is long device names and error strings, which must wrap rather than force horizontal
overflow. Validate at 375/768/1440/1920 with a long hostname and a long reason.

## 25. Failure-injection test strategy

All deterministic, no network: a transport factory raising each typed exception (the pattern
already used in this audit); a profile whose credential is absent; a scripted mixed network
(some devices collect, some refuse, some unreachable, one unsupported); corrupt fixtures for
`annotations.json`, `audit.jsonl` and one evidence record; a store method monkeypatched to raise
on write; a job manager restarted with an active job in its file. Assertions target the
**verdict** (class, message, action), not prose.

## 26. Browser-validation strategy

The ten scenarios in the brief, on a purpose-built world with a good run followed by a failing
one: wrong credentials · unreachable seed · partial run · last-good + failed new run (Topology
banner) · Policy with no config evidence · corrupt evidence fixture · PRISM absent · permission
denial · bulk failure injection · restart mid-discovery. Validate at four widths.

## 27. Beta-readiness blockers

1. **#1–#5** — the failure-classification collapse. An external tester with a wrong password, an
   unreachable device, an unsupported switch, or an Atlas defect sees the *same sentence*.
2. **#6** — partial failure presented as full success when no authentication failed.
3. **#7** — a corrupt annotation file 500s three primary pages.
4. **#9** — Topology presents stale data as current after a failed run.

Everything else is High or below. Notably **not** blockers, because they are already correct:
data preservation, secret hygiene, stuck jobs, permission copy, PRISM isolation, bulk truth.

## 28. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Trusting typed exception text re-opens the leak the current design guards against | Only *Atlas-owned* typed exceptions are trusted; foreign/untyped text still selects an allowlisted message. Pinned by a test that no third-party exception's text ever reaches a response |
| R2 | Degrading corrupt-annotation pages hides real corruption | The banner is loud, counts what was lost, and links `/system/integrity`; a test asserts the banner appears |
| R3 | A staleness banner appears on healthy pages and becomes noise | It renders only when the latest attempt did not succeed or the snapshot predates it |
| R4 | New per-request work to compute freshness | Reuse the job record and snapshot timestamp the pages already load; no new store reads |
| R5 | Copy churn breaks existing pinned tests | Verdict-level assertions; update pins deliberately in the same commit |

## 29. Non-goals

No happy-path hierarchy, navigation, PR-178.2 bulk semantics, or permission changes. No per-device
retry orchestration, no new job framework, no new discovery protocols or vendor support, no AI
capability, no PR-180 diagnostics/version work, no packaging/licensing/updates/branding, no SPA.
No auto-repair or auto-deletion of user data.

---

## 30. Adversarial review findings

Performed against the plan above; **four findings changed it**.

**30.1 — BLOCKER (amended): trusting exception messages could re-open a leak.** The plan's
central move is "use the typed exception's own message". Attack: `CredentialNotFoundError` is
Atlas's, but a *wrapped* third-party error (netmiko, paramiko, an OS error) could arrive as a
subclass or carry an interpolated command line containing a secret. The current design's blanket
distrust is exactly why nothing leaked in this audit. **Amendment:** trust is granted by an
explicit allowlist of Atlas-owned exception classes whose messages are audited as operator-safe —
never by inheritance, never by duck-typing. Everything else keeps the substring-selection
discipline. This is now R1, with a pinned test.

**30.2 — BLOCKER (amended): the partial-success rule could turn a healthy sweep into an alarm.**
The draft said "warn whenever attempted > collected". Attack: a /24 sweep attempts 254 addresses
and collects 9 — and PR-043.10 established that silent addresses are *coverage, not failure*.
That draft rule would have made every subnet discovery look broken and undone a shipped decision.
**Amendment:** the partial rule counts only devices that **answered** — refused, unsupported, or
lost mid-collection. Silent addresses stay coverage and stay out of the warning, exactly as
today.

**30.3 — HIGH (amended): degrading corrupt annotations could silently drop operator state.** The
draft said "treat annotations as absent". Attack: acknowledgements and suppressions would vanish
without a word — and a *suppression* vanishing makes hidden rows reappear, which looks like new
problems. **Amendment:** degradation is loud and specific ("operator annotations could not be
read — acknowledgements, owners, notes and suppressions are not shown"), and the page must not
offer bulk or single-row annotation actions while the store is unreadable, so a write cannot
overwrite a file Atlas could not parse. That last clause also prevents a data-destroying repair.

**30.4 — MEDIUM (amended): "last known good" must not become "silently ancient".** Attack: the
banner says "as of 14 days ago" and an operator keeps working against a fortnight-old graph
believing Atlas is fine. **Amendment:** the banner states the age *and* the consecutive failed
attempts since ("last successful discovery 14 days ago; 3 attempts have failed since"), which is
information the job history already holds.

**Attacks that did *not* change the plan** — recorded so they need not be re-run:

- *Does the plan destroy old state?* No — it changes only messages, banners and one classifier;
  the preservation behaviour is already correct and measured.
- *Does it mislabel unsupported as failed?* That is the defect being fixed; unsupported becomes
  neutral (class D).
- *Does it get stuck after restart?* Untouched — `_restore()` already marks interrupted.
- *False retries?* No retry orchestration is added; only links to the thing to fix.
- *Swallowed internal exceptions?* The opposite: the internal class gains a traceback log it does
  not have today (§21).
- *Expensive normal-path work?* Freshness comes from the job record and snapshot timestamp both
  already loaded; the classifier runs once per failure.
- *Does it regress PR-178.2?* No bulk semantics change; §16 is preserve-only.
- *One correction to my own audit:* an early live probe reported "the discovery page does not
  show the failure" — **false**. It searched for the wrong string; the failure text *is*
  server-rendered into `/discovery` and survives reload (re-measured, `job-failure` visible).
  Failure persistence is correct today.

## 31. Required amendments from the adversarial review

1. Trust only an explicit allowlist of Atlas-owned exception classes (§30.1).
2. Partial counts devices that answered; silent addresses remain coverage (§30.2).
3. Corrupt-annotation degradation is loud, and disables annotation writes while unreadable
   (§30.3).
4. The staleness banner states age **and** consecutive failed attempts (§30.4).

## 32. Recommended PR scope

**Step 1 — the classifier (highest value, smallest change).** `web/failures.py`:
`FailureVerdict` + `classify()` with the Atlas-owned allowlist; job layer emits
message/action/severity/diagnostic code; internal class logs the traceback. Fixes blockers #1–#5.

**Step 2 — outcome honesty.** Partial-run rule (answered-but-not-collected), completion copy that
states collected-of-attempted with the refused/unreachable/unsupported split, attempted vs
collected counters. Fixes #6, #10.

**Step 3 — degraded rendering.** Corrupt annotations/audit degrade instead of 500 (loud banner,
annotation writes disabled); evidence/configuration state their omissions; register 400/403
handlers. Fixes #7, #8, #18, #19.

**Step 4 — freshness banner.** The shared degraded-state banner, adopted by Topology first, with
age + consecutive failures. Fixes #9.

**Step 5 — validate.** Injection suite, the ten browser scenarios at four widths, full suite.

**Deferred:** per-device retry; export emptiness copy (#11) and 404 consistency (#12) may ride
along if free, otherwise recorded.

## 33. Success criteria

An external beta tester never asks "did Atlas fail, or is there no data?", "is this old or
current?", "did some devices work?", "are my credentials wrong or is the device unreachable?",
"did that partly succeed?", or "what do I do next?" — because every failure carries its class,
what Atlas still knows, what it could not determine, and one concrete next step. And the things
that are already right — no leaks, no lost data, no stuck jobs, honest bulk truth — remain
exactly as they are.

## 34. FINAL APPROVED IMPLEMENTATION PLAN

**Step 1 — `web/failures.py` + job-layer adoption.**
`FailureVerdict(failure_class, operator_message, next_action_label, next_action_href,
diagnostic_code, severity)` and `classify(exception) -> FailureVerdict`. Type table for
Atlas-owned exceptions (`CredentialNotFoundError`, `AuthenticationError`, `SSHUnavailableError`,
`ConnectionTimeoutError`, `ConnectionLostError`, `UnsupportedPlatformError`,
`PermissionDeniedError`, `TransportDependencyError`, `WorkspaceCorruptedError`), whose own
messages are used **only for the allowlisted classes**; today's substring rules retained as the
fallback for untyped/foreign exceptions; a final internal-error class that logs `exc_info` with
the correlation id. `DiscoveryJob` gains `failure_class`, `next_action_label`,
`next_action_href`; `friendly_failure()` becomes a thin wrapper so nothing else breaks.
*Tests:* one per class asserting message, action and that no foreign exception text ever reaches
the payload; the `CredentialNotFoundError` case end-to-end.

**Step 2 — outcome honesty.** `attempted`/`collected`/`refused`/`unreachable`/`unsupported`
derived from the run's existing statistics; `PARTIAL` outcome when answered-but-not-collected > 0;
completion copy and the discovery panel state collected-of-attempted; silent addresses stay
coverage. *Tests:* the four §5 rows; a /24 sweep with 9 devices raises no warning.

**Step 3 — degraded rendering.** `AnnotationStore`/`AuditLog` readers gain a
"degraded" result (readable data + a reason) instead of raising into the request; `/policy`,
`/changes`, `/timeline`, `/audit` render with a loud banner and annotation writes disabled;
evidence/configuration count and state unreadable records; 400/403 handlers registered; unknown
records 404 consistently. *Tests:* corrupt fixtures return 200 with the banner and no annotation
controls; a bad audit line is skipped and counted; no page 500s on any corrupt fixture.

**Step 4 — freshness banner.** One template component rendering "collected <when> · last
successful discovery <when> · N attempts failed since", from the job record and snapshot
timestamp already loaded; adopted by Topology, available elsewhere. *Tests:* appears only when
the latest attempt failed or the data predates it; no extra store reads.

**Step 5 — validate.** Full suite; the injection suite; the ten browser scenarios at
375/768/1440/1920; confirm PR-176/178.1/178.2 budgets and semantics untouched.

**Handover must state:** the before/after operator message for each failure class; that no
foreign exception text can reach a response; the partial-run rule and why silent addresses are
excluded; which pages now degrade instead of 500; the Topology freshness wording; and that data
preservation, secret hygiene, restart reconciliation and bulk truth were preserved unchanged.

---

*Evidence base: HEAD `b60d80c`; deterministic injection of every typed transport failure through
the real `DiscoveryJobManager`; a mixed scripted network producing a genuine partial run; corrupt
`annotations.json` / `audit.jsonl` / truncated snapshot / corrupt evidence fixtures probed across
13 pages in both TESTING and production error modes; a live password-mode server exercising a
failed discovery, the 403 path, and last-good rendering; and the persisted job record read from
disk. No repository file was modified.*
