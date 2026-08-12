# PR-176 Implementation Handover — Nothing Blocks Without Saying So

*Implemented 2026-08-12 against the approved architecture in
[PR-176_NOTHING_BLOCKS_WITHOUT_SAYING_SO.md](PR-176_NOTHING_BLOCKS_WITHOUT_SAYING_SO.md).
All six steps executed in order. Full regression suite green.*

## 1. What was delivered

The `/policy` cold-render blocker from the PR-175 audit is fixed at its measured root
cause: the policy engine asked the evidence store for records once per device, and the
store re-parsed its entire JSON file on every call — a measured 125× parse amplification
(1.9 million `from_dict` calls for 9,054 records). No spinner was added, because after
the fix nothing on the page blocks long enough to need one.

## 2. Measured before/after (real browser, live estate, fresh server process)

| Scenario | Before (PR-175 audit) | After | Target |
|---|---|---|---|
| Cold `/policy`, single scope (19onlyai, 85 devices) | 9,975 ms | **578–878 ms** | < 1 s ✓ |
| Cold `/policy`, single scope (default, 21,411 records) | — | **402–736 ms** | < 1 s ✓ |
| Cold `/policy`, Enterprise scope | ~10 s | **459–745 ms** | < 2 s ✓ |
| Warm `/policy`, any scope | 98–388 ms | **88–402 ms** | < 500 ms ✓ |
| Scope A → B → A, returning to A | 10,544–11,492 ms | **88–95 ms** | cache hit ✓ |
| Fresh empty workspace, cold `/policy` | — | **424 ms**, clean empty state | < 1 s ✓ |

**Amplification achieved: exactly 1 parse per store per request** (21,411 `from_dict`
calls for the 21,411-record store; previously 3 parses per render on top of the
per-device loop). The permanent guard budgets ≤ 2× records.

## 3. Step 1 — Store memoisation (`enterprise_memory/store.py`)

- `_read` is now a **stat-validated memo**: each entry carries the file's
  `(mtime_ns, st_size)` at parse time and is served only while a fresh `stat()` still
  matches — one stat instead of one full parse. Per-instance, never process-global.
- Lazy by-device indexes for `evidence_records` and `configuration_snapshots`, rebuilt
  whenever the parsed object's *identity* changes; snapshots are sorted once at build so
  per-device slices inherit the original `captured_at` order. `discovery_session`
  filtering and all bulk behaviour unchanged.
- No engine, matcher, pack, or CORTEX changes.

## 4. One planned semantic was deliberately strengthened

The plan's T10 said a store instance should *never see* evidence written after
construction. Implementing that broke an existing correctness test
(`test_rerun_without_change_stores_no_duplicate`: a handle held across a second
discovery must observe it). Per "do not weaken a correctness test to meet a timing
target," the memo became stat-validated instead — **freshness at every query boundary,
byte-identical behaviour to the re-read-every-call original**. T10 is superseded by a
stronger pin: `test_a_handle_observes_evidence_written_by_another_instance`.

## 5. A latent bug found and fixed in the same step

Writers (`_append_record`, `_record_observation`, `store_configuration`) mutated the
memoised list/dict **in place**, which preserved object identity — so a same-instance
*query → write → query* sequence would have served a stale index missing the new
record. All three now copy before mutating; the sequence is pinned by
`test_query_write_query_on_one_instance_sees_the_write`.

## 6. Step 2 — Correctness pins (proven before any caching work continued)

- `MemoisedEvaluationPinTests` (`tests/test_enterprise_policy.py`): warm, cold, and
  fresh-instance evaluations produce **byte-identical `PolicyReport.to_dict()`**;
  evidence written after a report appears in the very next one.
- `MemoisationCorrectnessTests` (`tests/test_enterprise_memory.py`): cross-instance
  freshness, same-instance write visibility, parsed-object sharing, per-device ≡ bulk
  with ordering.

## 7. Step 3 — Bounded LRU report cache (`web/routes.py`)

Single entry → **4-entry LRU** (`OrderedDict`, move-to-end on hit, evict oldest). The
key kept every existing dimension (scope id, per-scope `records.json` +
`configurations/index.json` stamps, governance revision) and gained **`atlas-version`**,
so an upgrade can never serve a report computed under older semantics. Governance save
now calls `_policy_cache_invalidate("policy governance baseline saved")` —
belt-and-braces over the key, with the reason kept for diagnostics. `_device_maps`
reads the most-recently-used entry (the maps are enterprise-wide, so any entry's copy
is valid). T5–T7 pinned in `tests/test_policy_report_cache.py`, including
A→B→A-serves-the-right-scope content checks.

## 8. Step 4 — Deferred loading deliberately skipped

Enterprise cold measured 459–745 ms, far under the 2 s gate, so no deferred body, no
progress region, no loading copy. The decision and full measurement table are recorded
in the implementation decision record appended to the architecture document. While
measuring, one more redundancy was removed: the render built **two** store instances
per scope (engine + contexts); `_policy_contexts_for_scope` now accepts the caller's
memory, halving parses on both the `/policy` and CORTEX ask paths.

## 9. Step 5 — Diagnostics and the permanent guard

- Store: `diagnostics` counters (index builds + build ms per file) — two dict updates
  per rebuild, nothing per query.
- Route: one **DEBUG-level** line per cold build (`atlas.policy.report scope=…
  prep_ms=… evaluations=… devices=… stores=… index_builds=… cache_hits/misses/
  evictions/invalidations… last_invalidation=…`). Silent at the production INFO level;
  smoke-tested — a healthy line shows exactly 2 index builds (records + snapshots) per
  store.
- **T8 guard**: `test_amplification_is_linear_in_records_not_devices` counts real
  `from_dict` calls during a 6-device evaluation and fails if parses exceed 2× records.

## 10. Step 6 — Validation results

- **Full suite: 2,983 passed, 2 skipped, 917 subtests, 0 failures** (10:43) — exactly
  +12 over the 2,971 baseline, matching the 12 new tests.
- **Browser scenarios**: fresh workspace (424 ms, no spinner) ✓; cold single scope,
  cold Enterprise, A→B→A (table above) ✓; touching a scope's `records.json`
  invalidated both that scope's entry *and* the Enterprise entry (rebuild, then warm
  again), so a post-discovery request can never see a pre-discovery report ✓; no
  spinner/loading UI exists anywhere on `/policy` ✓. The governance-change scenario is
  validated by the route-level test with a real Flask app rather than by mutating the
  live governance store in the browser.
- **PR-175 cold sweep re-run**, Enterprise scope, fresh process, 24 nav destinations:
  zero G1 breaches; worst page is `/topology` at 785 ms; `/policy` (686 ms) is no
  longer the slowest page in the product.

## 11. Final invalidation contract

A cached report is served only while **all** of these match: requested scope id; each
member scope's `records.json` and `configurations/index.json` `(mtime_ns, size)`; the
policy-governance revision; the Atlas version. A governance save additionally clears
the cache outright with a recorded reason. Below that, the store memo re-validates
against the file's stat on **every** query, so even a mid-request external write is
picked up at the next query boundary. Never process-global; the LRU holds at most 4
report dicts.

## 12. Non-goals respected

No Policy UX/hierarchy redesign, no navigation changes, no persisted policy reports,
no frontend framework, no verdict-vocabulary or Home changes. The only
template-visible difference is speed.

## 13. Known residuals

- The report-cache key and the store memo both rely on `(mtime_ns, size)`; a writer
  that produces identical size within the same nanosecond tick would alias. This is
  the same contract the pre-existing cache already used, and same-instance writes are
  exempt (the memo is refreshed with the written object directly).
- On this estate the Enterprise scope aggregates one profile scope (the legacy local
  workspace is excluded from aggregation by design), so Enterprise ≈ single-scope
  cost here; the budgets were also proven against the 16-store harness (25.2 s →
  2.3 s for 865 devices × 12 policies).
