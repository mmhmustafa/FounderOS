# PR-A1 — GPL Runtime Dependency Remedy
## Implementation Handover

**Status: implemented, validated, committed locally. NOT PUSHED — awaiting review.**

Stage A1 of the PR-A architecture review (§32) only. One job: remove the single RED runtime
dependency (`rfc3987`, GPL-3.0-or-later) without changing Atlas behaviour. A2 not started.
LICENSE untouched. No notices generated. No packaging.

---

### 1. Starting HEAD

`630cd6f` — equal to `origin/main`, verified by `git fetch` at preflight; working tree carried
only the three untracked review documents; both tracked artifacts regenerated clean before any
change was made.

### 2. Final code HEAD

`6cba9ca` — `fix(compliance): PR-A1 - the GPL runtime dependency leaves the closure`.
(The commit adding this handover document follows it; no code or artifacts change after
`6cba9ca`.)

### 3. Commit list

| Commit | Content |
|---|---|
| `6cba9ca` | Dependency extra swap + lock delta + both regenerated artifacts + tests, one unit — the SBOM and manifest describe the dependency state of the same commit |
| *(next)* | This handover document only |

### 4. Files changed

`pyproject.toml` (one dependency line + explanatory comment) · `constraints.txt` (the exact
four-line delta) · `compliance/runtime-manifest.json` (regenerated) · `sbom.cdx.json`
(regenerated) · `tests/test_compliance_foundation.py` (two A0 scope guards flipped to their
pre-planned A1 forms + new `GplRemedyTests`). 5 files, +263/−22. Nothing else.

### 5. Exact dependency delta

**pyproject.toml:** `jsonschema[format]>=4.23,<5` → `jsonschema[format-nongpl]>=4.23,<5`.
Version range unchanged. FormatChecker usage unchanged. No schema-validation redesign.

**constraints.txt:**

| | Package | Licence (from actual evidence) |
|---|---|---|
| REMOVE | `rfc3987==1.3.8` | GPL-3.0-or-later (the RED finding) |
| ADD | `rfc3986-validator==0.1.1` | MIT (bundled LICENSE + metadata) |
| ADD | `rfc3987-syntax==1.1.0` | MIT (bundled LICENSE + metadata field; see §9) |
| ADD | `lark==1.3.1` | MIT (bundled LICENSE + metadata) |

Resolution matched the architecture review's verified versions exactly — the STOP condition
("if resolution differs") never triggered. The five A0 not-locked leaves were deliberately
**not** pinned (§15).

### 6. Runtime counts per target platform

From the regenerated tracked manifest (A0 → A1):

| Measure | A0 | A1 |
|---|---:|---:|
| Runtime entries (union) | 58 | **60** |
| — on `win32` | 56 | **58** |
| — on `linux` | 56 | **58** |
| — on `darwin` | 54 | **56** |
| — lock-pinned | 53 | **55** (−rfc3987, +3) |
| — honest not-locked leaves | 5 | **5** (unchanged) |
| Development-only | 26 | **26** |
| Unassigned pins | 1 | **1** (`setuptools`) |

All three replacements resolve on all three platforms (no markers), which is why every
platform count rises by exactly +2 (= −1 +3).

### 7. RED / AMBER / UNKNOWN / GREEN after remedy

| Band | Count | Members |
|---|---:|---|
| **RED (GPL/AGPL)** | **0** | — |
| AMBER (weak copyleft) | 3 | `paramiko` LGPL-2.1 (in `declared_expression`; `declared_license` empty — any scan must join both fields), `scp` LGPL-2.1-or-later, `fqdn` MPL-2.0 |
| UNKNOWN-leaning evidence | 2 | `pyserial` (`no-license-file-shipped`; metadata declares BSD), `isoduration` (`metadata-license-unknown` + `bundled-license-text-present`) |
| GREEN | remainder | all other runtime members, permissive declarations with dist-info evidence |

Scanned across **all** declared surfaces (expression + licence field + classifiers) of all 60
runtime members, and separately across all 82 SBOM components in every scope: **zero GPL, zero
AGPL** anywhere. (`certifi` MPL-2.0 remains **development**-scoped, exactly as A0 classified
it.) AMBER treatment is A2's, untouched here.

### 8. Proof rfc3987 is absent from every runtime path

1. **Manifest bytes:** the exact quoted token `"rfc3987"` appears nowhere in
   `compliance/runtime-manifest.json` (test-pinned; `rfc3987-syntax` is a distinct token).
2. **SBOM:** no component named `rfc3987` (test-pinned).
3. **Closure metadata:** the only `Requires-Dist:` mentioning `rfc3987` across every installed
   dist-info in the closure is **jsonschema's own**, gated behind `extra == 'format'` — an
   extra nothing requests any more. No second dependency path exists.
4. **Independent resolution:** `pip install --dry-run` of `.[credentials,ssh,web]` against the
   new lock resolves the entire runtime closure with `founderos-runtime` itself as the only
   install item — rfc3987 nowhere in the resolver's plan.
5. **Environment:** `importlib.util.find_spec("rfc3987")` is `None` (test-pinned);
   `pip check` clean after the uninstall/install alignment.
6. **Tracked text:** `git grep` finds `jsonschema[format]` only in historical documents
   (Milestone-3 record, the A0 handover) and in the new test's own `assertNotIn`.

### 9. Replacement package licence evidence

| Package | Expression | Licence field | Classifier | Evidence files (dist-info) |
|---|---|---|---|---|
| `rfc3986-validator` 0.1.1 | — | `MIT license` | MIT License | `LICENSE`, `AUTHORS.rst` |
| `rfc3987-syntax` 1.1.0 | `MIT` | — | **Apache Software License** | `licenses/LICENSE` |
| `lark` 1.3.1 | — | `MIT` | MIT License | `licenses/LICENSE` |

All three bundled texts were read and are MIT texts. `rfc3987-syntax` carries a known
metadata/classifier discrepancy (MIT field + text vs. a stale Apache classifier) — recorded
here and in the manifest evidence rather than hidden; both are permissive, and A2's policy
gate owns the final classification. Test-pinned via `declared_expression or declared_license`.

### 10. Schema-equivalence result

Atlas's 33 tracked schemas (verified again at `630cd6f` and pinned by count) use exactly two
formats: `date-time` (×3) and the nonstandard `ip` (×1). `rfc3987` backed neither — it backed
`uri`/`iri`/`idn-hostname`, which Atlas never uses. The before/after format-checker
fingerprint (registered checkers + conformance results over a probe corpus, run in the real
project venv immediately before and immediately after the swap) is **IDENTICAL**. The
surviving behaviour is test-pinned permanently: `date-time` validates correctly, and `ip`
remains **unregistered** — it validated nothing before and validates nothing now. Per the
mandate, the `ip` observation stays an out-of-scope observation; A1 did not "fix" it.

### 11. Manifest regeneration result

Regenerated twice consecutively: byte-identical
(`ea304aa9…da6d2`), and identical to the tracked bytes at `6cba9ca`. 60 runtime / 26 dev-only /
1 unassigned.

### 12. SBOM regeneration result

Regenerated twice consecutively: byte-identical (`c24253ce…d31`), identical to the tracked
bytes at `6cba9ca`. 82 components (80 + 3 − 1), every one carrying scope and a declared-licence
string. The CI interlock (`git diff --exit-code` over both artifacts) reproduces cleanly.

### 13. Full-suite result

**3379 passed · 2 skipped · 1130 subtests passed · 0 failed** (12:53) — the 3371 baseline
plus exactly the eight new `GplRemedyTests`, no regressions. Focused runs: compliance
foundation **34/34**; schema/contract/manifest/release regression block **181 passed,
133 subtests**. The single warning is a pre-existing, deliberate duplicate-member zipfile
test (`test_persistence_safety.py`), unrelated.

### 14. Adversarial results — 10 of 10 pass

1. Runtime closure searched for `rfc3987` → absent everywhere (§8) — test-pinned.
2. Runtime closure searched for GPL/AGPL expressions across all declared surfaces → zero —
   test-pinned (LGPL masked as a distinct family, so an LGPL string cannot hide a GPL one).
3. pyproject + lock searched for a leftover `[format]` extra → none in live configuration.
4. Second dependency path to rfc3987 → none; the only `Requires-Dist` is jsonschema's own
   extra-gated one, and independent pip resolution confirms.
5. Dev-only/ambient packages altering the result → `build`, `CairoSVG`, `pillow` are
   installed ambient in the venv and appear in **neither** closure (run live; A0's
   unreachability test also still green).
6. Manifest regenerated twice → byte-identical.
7. SBOM regenerated twice → byte-identical.
8. Fresh `core.autocrlf=true` clone at `6cba9ca`, both artifacts regenerated inside it →
   `git diff --exit-code` clean in the clone; SHA-256 equal to the main tree's bytes.
9. Schema fingerprints before/after → identical (§10).
10. Replacement licences from actual evidence → verified from installed bundled texts +
    metadata (§9), discrepancy recorded — test-pinned.

### 15. Deviations

1. **The five A0 not-locked leaves stay unpinned** (`secretstorage`, `jeepney`,
   `backports-tarfile`, `importlib-metadata`, `typing-extensions`). The spec allowed pinning
   only if required for A1 reproducibility; it is not — generation is byte-stable across
   double runs and a fresh autocrlf clone without them. The lock delta stays exactly the
   reviewed four lines.
2. **The schema-format census test is scoped to the tracked schema roots**
   (`apps/`, `examples/`, `runtime/`, count pinned at 33) rather than the whole working tree,
   which carries untracked historical copies under `deliverables/` and 281 MB of lab data.
3. **The 16 mandated pins map onto fewer test methods**: 8 new `GplRemedyTests` + the 2
   flipped scope guards cover pins 1–11 and 14; pins 12–13 (regeneration clean) are already
   owned by the A0 convergence tests, deliberately not duplicated and not weakened; pins
   15–16 are the recorded green runs above.
4. **The before/after fingerprint is a transition-time proof** — the "before" world no longer
   exists once the swap lands, so the comparison artifacts live in the session record, and
   what is pinned in-repo forever is the surviving behaviour (§10).

### 16. Residual A2 decisions (none advanced here)

AMBER treatment (LGPL-2.1 texts for paramiko/scp, MPL-2.0 notice for fqdn) ·
`THIRD-PARTY-NOTICES.txt` generation · `compliance/license-policy.json` · the LICENSE text
itself (`LicenseRef-FounderOS-Atlas-Beta`, PEP 639 form) · README / PRODUCT_REVIEW_ZERO
licensing language · tracked source-ZIP removal · the `rfc3987-syntax` classifier discrepancy's
final classification · optionally pinning the five not-locked leaves · the `pyserial` /
`isoduration` evidence observations' policy verdicts. Owner-of-record decisions (Mohammed
Mustafa Hussain, individual) remain recorded in the PR-A review, unimplemented.

### 17. Explicit statement

**No Atlas-owned licence terms were changed in PR-A1.** `LICENSE` still reads
`LICENSE NOT YET SELECTED` (still test-pinned); README and PRODUCT_REVIEW_ZERO licensing
language untouched; no proprietary terms drafted.

### 18. Explicit statement

**No Windows packaging work was performed.** No binaries, no PyInstaller configuration, no
licence keys, no signing, no telemetry, no auto-update.

### 19. Push recommendation

**A1 is ready to push.** The change is the smallest possible remedy (one dependency line, four
lock lines, two regenerated artifacts, tests), every one of the ten adversarial attacks fails,
behaviour equivalence is fingerprint-proven and test-pinned, the full suite is green with zero
failures, and the CI interlock will hold the artifacts honest from here.

### 20. Exact next action

On approval: `git push origin main` (moves `origin/main` from `630cd6f` to the handover
commit), then confirm the remote HEAD and start **Stage A2** — licence text + notices + policy
gate — as its own reviewed PR. Until approval: nothing; the working tree is clean and nothing
has been pushed.

---

*LICENSE unchanged. Product source unchanged. Nothing pushed.*
