# PR-176 — Nothing Blocks Without Saying So — Root-Cause Analysis & Implementation Plan

**Role:** Chief Software Architect / Performance Architect / Enterprise UX Architect.
**Status:** architecture only — nothing implemented, nothing modified, nothing committed.
**Method:** the real repository and the running application, profiled and measured. Every number
below was taken from execution. The recommended fix was **measured before being recommended**,
using a throwaway harness that never touched `src/`.

---

## 1. Executive diagnosis

**The ten seconds is not policy evaluation. It is the same JSON being parsed 125 times.**

Only ~4 s of a ~25 s Enterprise-scope evaluation is real work; **over 90 % is redundant I/O and
deserialization.** `EnterpriseMemoryStore.evidence_records(device_id=…)` reads the entire
`records.json`, constructs a `RawEvidenceRecord` for **every** record in the store, and *then*
filters to the one device asked for. `configuration_snapshots(device_id=…)` does the same. The
policy engine calls both **once per device**, so a store of *D* devices and *R* records performs
*D × R* object constructions where *R* would do. The profiler counted **1,900,471** `from_dict`
calls for **9,054** records.

`_read()` has no memoisation, so the file is re-read from disk on every one of those calls.

**Proven fix, measured:** memoising the store's reads and indexing records by device — with no
change to the engine, the pack, or any verdict — takes Enterprise scope from **25,167 ms → 2,031 ms
(12.4×)** and the 85-device scope from **6,652 ms → 272 ms (24×)**, producing **byte-identical
verdicts** (passed 3,980 / failed 4,166 / n-a 914 in both runs).

**The audit under-reported the blocker.** PR-175 measured 9,975 ms; the live app confirms 10,544 ms
for that scope — but also reveals that the report cache holds **exactly one entry**, so *every scope
switch is a full cold render*. A multi-profile operator pays 10–11 s on **every** Policy
navigation, not once.

**Recommendation: fix the cause, keep the cache as an optimisation, add progress only for what
genuinely remains.** No spinner is needed for single-scope Policy after the fix — 272 ms needs no
progress indicator.

## 2. Measured cold-path breakdown

Enterprise scope, 16 stores, 865 devices, 12 policies = 10,380 evaluations. cProfile, cumulative:

| Stage | Cumulative | Calls | Share |
|---|---|---|---|
| `evaluate_scopes` (total) | **58.8 s** | 1 | 100 % |
| ├─ `store.evidence_records()` | **42.6 s** | 2,784 | **72 %** |
| ├─ `models.py:259 from_dict` | **28.7 s** | **1,900,471** | 49 % |
| ├─ `retrieval.get_raw_evidence` | 21.6 s | 1,373 | 37 % |
| ├─ `store._read` (disk + json) | 17.1 s | 8,314 | 29 % |
| ├─ `configuration_snapshots` | 7.5 s | 4,157 | 13 % |
| └─ **`matcher.evaluate_check`** — *the actual policy work* | **3.95 s** | 28,376 | **6.7 %** |
| `report.to_dict()` | 0.76 s | 1 | 1 % |
| `PolicyGovernanceRepository.active()` | 0.9 ms | 1 | ~0 % |
| `effective_pack()` | 0.0 ms | 1 | ~0 % |

*(cProfile inflates absolute times ~2×; the **proportions** are what matter. Clean, un-profiled
measurement of the same work: 25,167 ms.)*

**Evidence volume:** 7.2 MB of `records.json` across 16 stores, 9,054 records. Largest store: 117
devices / 1,061 records. Per-device loop on that store alone: **1,631 ms** vs **13 ms** for one bulk
read — **125× amplification**. A second identical loop costs **1,733 ms**: there is no memoisation
anywhere.

## 3. Exact root cause

```python
# enterprise_memory/store.py:245
def evidence_records(self, *, device_id=None, discovery_session=None):
    rows = self._read(self._evidence / "records.json", [])      # full file, every call
    records = [RawEvidenceRecord.from_dict(row) for row in rows]  # EVERY record
    if device_id is not None:
        records = [r for r in records if r.device_id == device_id]  # …then filter
```

…and `_read` (store.py:68) re-reads from disk each time, with no cache.

The policy engine's per-device loop (`policy/engine.py:85`) calls `get_device_memory(device_id)`
— which calls **both** `evidence_records(device_id=…)` and `configuration_snapshots(device_id=…)` —
and the reasoning provider (`reasoning/providers.py:143`) calls `get_raw_evidence(subject)` again for
the same device. **Two to three full-store parses per device.**

**Blast radius is narrow and that matters.** Every *other* caller reads in bulk exactly once
(`search/builder.py:589`, `evidence_resolution_routes.py:80,86`, `routes.py:2375,2378`); the
per-device callers outside Policy are single-device pages and the evidence-bundle download, where
one parse is correct. **Policy is the only page that loops.** That is precisely why Policy is the
only destination over 2 s.

## 4. Cold vs warm

| Request | Measured |
|---|---|
| `/policy?scope=all` with cache primed | 136 ms |
| `/policy?scope=all` warm | 93 ms |
| **`/policy?scope=19onlyai` (evicts)** | **10,544 ms** |
| **`/policy?scope=all` again (recomputed)** | **11,492 ms** |

Warm is fast **only** because the whole report dict is memoised in-process. Nothing else is cached:
the store re-parses from scratch on every miss. And because the cache holds **one entry**,
alternating between two scopes guarantees a cold render every time — the audit's "first click"
framing understates it.

## 5. Current cache / lifecycle analysis

`routes.py:2789` — `_policy_report_cache = {"key": None, "report": None, "sites": None,
"platforms": None}`.

| Question | Answer |
|---|---|
| What exists after the first request? | One report dict + derived site/platform maps |
| Where stored? | Module-level dict inside `create_app` — **process-local, memory-only** |
| Entries | **Exactly one** |
| Invalidated by restart? | **Yes** — nothing on disk |
| Invalidated by new discovery? | Yes — key includes `records.json` and `configurations/index.json` `mtime_ns` + `size` |
| Invalidated by policy change? | Yes — key includes `PolicyGovernanceRepository.revision()` |
| Invalidated by scope change? | Yes — key includes `scope_id` (and evicts, §4) |
| Invalidated by pack/code change? | **Not by key** — but the cache dies with the process, and code changes require a restart, so the exposure is bounded |
| Could it show a wrong verdict? | **No path found.** The key covers scope, evidence identity and governance revision; correctness rests on evidence mtime+size, which is sound for this workload |

**Assessment: the existing contract is correct but the cache is a band-aid over §3.** It exists to
hide a 25-second computation. Once the cause is fixed it becomes a genuine optimisation, and its
single-entry limitation becomes cheap to fix.

## 6. Recommended architecture

**Fix the cause in the store; keep the report cache; add progress only for what remains.**

### Layer 1 — stop re-parsing (the actual fix)

Give `EnterpriseMemoryStore` **per-instance, request-lifetime memoisation** and a **by-device
index**:

- memoise `_read(path)` per store instance;
- build `{device_id: [records]}` and `{device_id: [snapshots]}` once, lazily, on first per-device
  query; serve `device_id=` lookups from it.

This is the smallest change that removes the work rather than hiding it. **Measured: 12.4× / 24×,
identical verdicts.**

*Correctness note — this is the one thing to get right:* the memoised store must be **per-request,
not global**. An `EnterpriseMemoryStore` that outlives a discovery would serve stale evidence. The
web layer already constructs stores per request via `memory_service(scope)`; the memoisation must
live on that instance and die with it. **A process-global store cache would trade a performance bug
for a correctness bug — do not do it.**

### Layer 2 — keep the report cache, make it hold more than one entry

Retain it as an optimisation for paginated/filtered navigation (the investigation workflow makes
many requests against one report). Raise it to a small bounded LRU (**4 entries**) so alternating
scopes stops thrashing. Keep the existing key **unchanged** — it is already correct — and add
`atlas_version` so an upgrade cannot serve a report built by different rule code.

### Layer 3 — progress, only where work genuinely remains

After Layer 1, single-scope Policy is **272 ms** — no progress affordance is warranted or wanted.
Enterprise scope lands at **~2.0 s**, at the gate boundary and growing with estate size. For that
case only, use the **existing** server-rendered architecture: render the page shell immediately,
then fetch the report body. Atlas already does exactly this on `/topology` (shell + iframed
artifact) and `/history` (deferred supporting tables), so this introduces **no new frontend
architecture**.

### Rejected alternatives

| Option | Why rejected |
|---|---|
| **Spinner over the 10 s** | Hides a defect that measurement shows is removable. Fails the brief's first principle. |
| **Precompute at discovery completion** | Moves 25 s into discovery without removing it, and Policy depends on governance revision too — a policy edit would still force a cold path. Explicitly warned against in the brief; measurement shows it is unnecessary. |
| **Persist the report to disk** | A second source of truth for verdicts, with its own staleness and corruption surface — for work that becomes 272 ms. |
| **Compute at startup** | Penalises every launch, including users who never open Policy; wrong on a fresh workspace. |
| **SPA / frontend framework** | Explicit non-goal, and unnecessary — the deferred-body pattern already exists in this codebase. |

## 7. Cache / precomputation strategy

**No precomputation.** After Layer 1 there is nothing worth precomputing. Caching stays in memory,
process-local, bounded.

## 8. Invalidation contract

Report cache key — **existing dimensions retained, one added**:

| Dimension | Source | Why |
|---|---|---|
| `scope_id` | request | never serve one scope's report for another |
| per-scope `records.json` `mtime_ns` + `size` | filesystem | new evidence ⇒ new report |
| per-scope `configurations/index.json` `mtime_ns` + `size` | filesystem | new configuration ⇒ new report |
| governance revision | `PolicyGovernanceRepository.revision()` | policy edits ⇒ new report |
| **`atlas_version`** *(new)* | `release.VERSION` | rule-code changes cannot be served from an old report |

Deliberately **excluded**: subject, vendor, capability, evidence version — all derived from the
evidence files already covered; adding them would be key inflation without correctness gain.

Store-level memoisation needs no key: it is scoped to one request's store instance and cannot
outlive the data it read.

## 9. User progress experience

- **Single scope (272 ms):** nothing. No spinner. Silence at 272 ms is correct.
- **Enterprise scope (~2 s):** shell renders immediately with the page heading and scope context;
  the report region shows one honest, non-animated line — *"Preparing policy assessment…"* — replaced
  by content when ready.
- **No fabricated percentages, no fake stages.** Atlas cannot measure progress through
  `evaluate_scopes`, so it must not imply it. Indeterminate work gets an indeterminate message.
- Multi-stage wording (*"Evaluating configuration evidence…"* → *"Building policy summary…"*) is
  only permissible if the backend genuinely reports those transitions. **It currently cannot, so do
  not add it.**

## 10. Failure behaviour

Follow the Atlas honesty ladder — what happened → what Atlas could still determine → what it could
not → what to do next.

| Failure | Behaviour |
|---|---|
| Report preparation raises | Page shell stays; region shows what failed and offers retry. Never an indefinite loading state. |
| Cached artifact unusable | Not applicable — memory-only; a miss simply recomputes |
| Evidence changes mid-computation | Key is captured **before** evaluation; the result is stored under the key it was computed from. A changed file yields a new key and a recompute on the next request — never a mislabelled report |
| App restarts | Cache empty; first request recomputes (272 ms single-scope) |
| Discovery completes while Policy is open | Next request has a new key ⇒ fresh report. The page should say the report is from an older evidence set rather than silently updating |
| Policy definitions change | Governance revision changes the key ⇒ recompute |
| Scope changes | Different key; with the LRU both scopes stay warm |
| No evidence | Existing empty state — already correct (verified in PR-175) |

## 11. Observability

Development-mode by default (the `?diag=1` pattern PR-174 established), not production logging:

- total policy preparation ms, and the store-index build ms;
- cache **hit / miss / evicted**, plus the **invalidation reason** (which key dimension changed);
- evaluation count and device count, so amplification regressions are visible;
- a single INFO log line in normal operation **only** when preparation exceeds the budget — a
  regression should be noisy exactly once, not on every request.

**Regression guard:** assert the amplification invariant directly — parses ≈ records, not
records × devices (§13, T8). That is the test that would have caught this defect years ago.

## 12. Performance budgets

Measured against this architecture, not aspiration:

| Budget | Target | Evidence |
|---|---|---|
| Navigation shell visible | < 500 ms | already met on all destinations |
| Warm Policy | < 500 ms | today 93–136 ms |
| **Cold Policy, single scope** | **< 1 s** | measured 272 ms after fix |
| **Cold Policy, Enterprise scope** | **< 2 s, else visible progress** | measured 2,031 ms after fix |
| Any destination silent | **< 2 s (G1)** | all others 21–1,055 ms today |
| Store parse amplification | **≤ 2× record count** | today 125× |

## 13. Test plan

| # | Test | Guards |
|---|---|---|
| T1 | Empty workspace, cold `/policy` → 200, empty state, < 1 s | first-run |
| T2 | Populated workspace, cold `/policy` single scope → < 1 s | the blocker |
| T3 | Warm `/policy` → < 500 ms | no warm regression |
| T4 | Fresh process (cache cold) → correct report | restart |
| T5 | New evidence (touch `records.json`) → key changes, report rebuilt | invalidation |
| T6 | Governance revision change → report rebuilt | policy edits |
| T7 | Scope A → B → A: all three correct; **no scope's report served for another** | the thrash + correctness |
| T8 | **Amplification invariant: `from_dict` calls ≈ record count, not records × devices** | **the root cause** |
| T9 | Memoised store and plain store produce **identical** `PolicyReport` counts and evaluations | correctness of the fix |
| T10 | A store instance never serves evidence written after it was constructed | the per-request-lifetime rule |
| T11 | Preparation failure → error state with retry, never indefinite loading | failure |
| T12 | Progress region appears only when preparation exceeds the threshold | no gratuitous spinner |
| T13 | Progress region terminates on success **and** on failure | no stuck state |
| T14 | Every nav destination cold < 2 s at Enterprise scope | **G1** |
| T15 | All existing policy / validation regression tests unchanged in semantics | no behaviour drift |

T9 is the headline: it is the test I already ran by hand (identical passed/failed/not-applicable
across 10,380 evaluations) and it must become permanent.

## 14. Browser-validation plan

Measure what the **user** experiences, per the brief:

1. Fresh workspace → `/policy` (empty state, timed).
2. Populated estate, cold process → `/policy` single scope; record wall-clock to first content.
3. Enterprise scope → `/policy`; confirm shell < 500 ms and either content < 2 s or an honest
   progress line.
4. **Scope A → B → A**, timing each — the thrash case from §4.
5. Immediately after a discovery completes → confirm rebuild and that the page does not present a
   pre-discovery report as current.
6. After a policy/governance change → confirm rebuild.
7. Re-run the PR-175 cold sweep across all destinations at Enterprise scope; confirm no new breach.
8. Confirm **no spinner appears** in the 272 ms single-scope case.

## 15. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **A memoised store outliving a discovery serves stale evidence** | **Critical** | Memoisation is per-instance and per-request; T10 pins it. This is the one way this PR could trade a performance bug for a correctness bug. |
| R2 | Index build cost on stores with many records but few queried devices | Low | Build lazily on first per-device query; single-device pages keep one bulk parse (13 ms on the largest store) |
| R3 | Memory: indexing 7.2 MB of records per request | Low–Medium | Records are already fully materialised today (1.9 M objects); indexing *reduces* peak allocation. Measure on the largest store. |
| R4 | LRU hides a stale report if the key is wrong | Medium | Key unchanged from today's correct contract, plus `atlas_version`; T5–T7 pin it |
| R5 | Enterprise scope grows past 2 s again as estates grow | Medium | Budget + T14 + the amplification invariant (T8) make regression visible; deferred-body path already handles the overflow case honestly |
| R6 | Deferred body changes page structure enough to disturb PR-178 | Low | Restrict to the report region; PR-178 owns hierarchy |

## 16. Non-goals

No Policy information-hierarchy redesign, no word-count reduction, no navigation change, no
first-run work, no PRISM move, no verdict-vocabulary change, no Home redesign, no new policy or
validation capability, no AI, no history, no Windows packaging, **no frontend framework**. Those
belong to PR-177 / PR-178 and beyond.

## 17. Recommended PR scope

**In scope**
1. `enterprise_memory/store.py` — per-instance `_read` memoisation; lazy by-device indexes for
   `evidence_records` and `configuration_snapshots`. *(the fix)*
2. `web/routes.py` — report cache to a bounded 4-entry LRU; add `atlas_version` to the key.
3. Deferred report body **for Enterprise scope only**, using the existing shell pattern, with an
   honest indeterminate message and a real failure state.
4. Development-mode timing/cache diagnostics.
5. Tests T1–T15.

**Explicitly out of scope:** everything in §16; optimising destinations already inside the gate
(21–1,055 ms) without a measured reason.

## 18. Success criteria

1. **G1 passes:** no destination blocks > 2 s without visible progress, verified at Enterprise scope.
2. Cold Policy, single scope **< 1 s** (measured 272 ms in the proof harness).
3. Cold Policy, Enterprise scope **< 2 s**, else honest progress from the shell.
4. Warm Policy **< 500 ms** — no regression from today's 93–136 ms.
5. **Verdicts byte-identical** to today: passed / failed / warnings / unknown / not-applicable and
   per-evaluation results unchanged.
6. Scope switching no longer triggers a full recompute each way.
7. No stale, cross-scope or cross-version report can be served.
8. Parse amplification ≤ 2× record count (from 125×).
9. No spinner where none is warranted.
10. Full regression suite green (baseline **2,971 passed / 2 skipped / 917 subtests**).

## 19. APPROVED IMPLEMENTATION PLAN

**Step 1 — Remove the redundant work (this is the PR).**
In `EnterpriseMemoryStore`: memoise `_read` per instance; build `{device_id: […]}` indexes lazily on
first per-device query for both `evidence_records` and `configuration_snapshots`; serve `device_id=`
lookups from them. Bulk and `discovery_session=` queries keep today's behaviour. **Nothing in the
policy engine, the pack, the matcher or the reasoning layer changes.**

**Step 2 — Pin correctness before optimising further.**
Add T9 (memoised vs plain store produce identical reports over the real estate) and T10 (a store
instance never serves evidence written after its construction). Step 3 does not start until these
pass — they are what makes Step 1 safe.

**Step 3 — Make the report cache stop thrashing.**
Bounded 4-entry LRU; add `atlas_version` to the existing key; leave every other dimension alone.
Add T5–T7.

**Step 4 — Progress only for Enterprise scope.**
Render shell first, then the report region, using the deferred pattern already present on
`/topology` and `/history`. One honest indeterminate line. A real failure state with retry.
**No percentages, no fabricated stages.** If Step 1 brings Enterprise scope under 2 s on the target
estate, **skip this step entirely** and record that decision — the budget, not the plan, decides.

**Step 5 — Diagnostics and budgets.**
Development-mode timings, cache hit/miss/evicted with invalidation reason, and the amplification
invariant (T8) as a permanent regression guard. One INFO line only when a budget is exceeded.

**Step 6 — Validate.**
Full regression suite; the eight browser scenarios in §14; re-run the PR-175 cold sweep across all
destinations at Enterprise scope; confirm G1.

**Handover must state:** measured before/after for single scope and Enterprise scope; confirmation
that verdict counts are identical; whether Step 4 was needed or skipped and why; the final
invalidation contract; and the amplification figure achieved.

---

*Measured against the live 16-profile / 865-device workspace. The recommended fix was executed in a
throwaway harness and produced identical verdicts before being recommended; the repository was not
modified during this investigation.*

---

## Implementation decision record (2026-08-12)

**Step 4 was deliberately skipped.** The budget, not the plan, decided — as this document
required. After Steps 1–3 landed, the live estate measured (real browser, fresh server process,
Home visited first as an operator would):

| Scenario | Before (PR-175 audit) | After Steps 1–3 | Target |
| --- | --- | --- | --- |
| Cold `/policy`, single scope (19onlyai, 85 devices) | 9,975 ms | **578 ms** | < 1 s |
| Cold `/policy`, single scope (default, 21,411 records) | — | **402 ms** | < 1 s |
| Cold `/policy`, Enterprise scope | ~10 s | **745 ms** | < 2 s |
| Warm `/policy`, any scope | 98–388 ms | **88–393 ms** | < 500 ms |
| Scope A → B → A, returning to A | 10,544–11,492 ms | **88 ms** | cache hit |

Enterprise scope is under 2 s, so no deferred loading, no progress region, and no loading
copy were added. Nothing on `/policy` blocks long enough to need to say so.

Step 1 grew one clarification during implementation: pure instance-lifetime memoisation broke
`test_rerun_without_change_stores_no_duplicate` (a handle constructed before a second discovery
must observe it — the write goes through other instances). Per "do not weaken a correctness test
to meet a timing target," the memo became **stat-validated**: every entry carries the file's
`(mtime_ns, size)` at parse time and is served only while the file still matches — one `stat()`
instead of one full parse, so a store handle can never serve stale evidence no matter who wrote
the file. This is *stronger* freshness than the plan's T10 wording ("never serves evidence
written after construction"), which is therefore superseded: behaviour is identical to the
re-read-every-call original, and only the redundant parsing is gone. The plan's report-level
pins (T9, and fresh-evidence-visible) hold unchanged.

A second latent defect surfaced and was fixed in the same step: writers mutated the memoised
list/dict in place, which preserved object identity and would have made a same-instance
query → write → query sequence serve a stale index. All three write paths now copy before
mutating, and the sequence is pinned by
`MemoisationCorrectnessTests.test_query_write_query_on_one_instance_sees_the_write`.

**Amplification achieved:** one parse per store per request — 21,411 `from_dict` calls for the
21,411-record store that previously parsed 3× per render (and per-device before Step 1). The
permanent guard (`test_amplification_is_linear_in_records_not_devices`) budgets ≤ 2× records.
