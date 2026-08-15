# PR-A0 — Compliance Foundation & Deterministic Runtime Manifest
## Implementation Handover

**Status: implemented, validated, committed locally. NOT PUSHED — awaiting review.**

Stage A0 of the PR-A architecture review (§32) only. LICENSE untouched. The GPL dependency
untouched. No notices generated. No packaging. A1 and A2 not started.

---

### 1. Baseline and final state

| Fact | Value |
|---|---|
| Baseline HEAD | `947654c` (= `origin/main`, verified by fetch) |
| Final local HEAD | `9aba223` |
| Working tree at handover | clean (untracked review documents only) |
| Baseline full suite | 3345 passed · 2 skipped · 1130 subtests · 0 failed |
| Final full suite | *see §12 — recorded at completion* |

### 2. Commit list (four logical stages)

| Commit | Stage |
|---|---|
| `c112858` | Determinism + the one partition rule (`.gitattributes`, `scripts/compliance_core.py`) |
| `0a46816` | Runtime manifest generator, tracked artifact, foundation tests |
| `c850c21` | SBOM convergence + regenerated `sbom.cdx.json` + audit-scope documentation |
| `9aba223` | setuptools ≥ 77, `MANIFEST.in` allow-list, CI interlock |

### 3. Files changed

**Created:** `.gitattributes` · `scripts/compliance_core.py` · `scripts/runtime_manifest.py` ·
`compliance/runtime-manifest.json` · `MANIFEST.in` · `tests/test_compliance_foundation.py`
(26 tests).

**Modified:** `scripts/generate_sbom.py` (partition + licence data + LF) · `sbom.cdx.json`
(regenerated, same commit) · `scripts/audit_dependencies.py` (docstring only — deliberate
whole-lock scope documented) · `pyproject.toml` (build-system floor only) ·
`.github/workflows/security.yml` (manifest generation + widened diff-check).

**Explicitly unchanged:** `LICENSE` (still `LICENSE NOT YET SELECTED` — test-pinned) ·
`jsonschema[format]` (test-pinned) · `rfc3987==1.3.8` (test-pinned) · README licensing wording ·
`PRODUCT_REVIEW_ZERO.md` · the tracked source ZIPs (A2 owns their removal) · all product source.

### 4. Runtime counts per target platform

From the tracked manifest (`compliance/runtime-manifest.json`), resolved from the declared
runtime roots (base + `credentials`/`ssh`/`web` extras), markers evaluated per platform at the
python floor 3.11:

| Measure | Count |
|---|---:|
| Runtime entries (union across platforms) | **58** |
| — on `win32` | **56** |
| — on `linux` | **56** |
| — on `darwin` | **54** |
| — of which lock-pinned | 53 |
| — of which honest not-locked leaves | 5 (`secretstorage`, `jeepney` [linux]; `backports-tarfile`, `importlib-metadata`, `typing-extensions` [floor-marker leaves]) |
| Development-only (must never ship) | **26** |
| Unassigned pins | **1** (`setuptools` — build tooling, reachable from neither root set) |

Platform-specific membership, measured and test-pinned: `pywin32-ctypes` and `colorama` are
win32-only; `secretstorage` and `jeepney` are linux-only **and recorded as not-locked** — the
constraints.txt gap the architecture review found is now permanently visible in a tracked
artifact instead of being platform luck.

### 5. The runtime/dev partition rule

One rule, one module — `scripts/compliance_core.py` — consumed by the manifest generator and
`generate_sbom.py`. `audit_dependencies.py` documents why it deliberately audits the whole lock
(a vulnerable dev tool still runs on the dev machine; narrowing the *security* gate would reduce
coverage).

- **Roots:** `[project.dependencies]` + runtime extras (`credentials`, `ssh`, `web`); dev extra
  separately. Root declaration order cannot affect output (sorted, and test-pinned by resolving
  a reversed root list).
- **Markers:** evaluated against fixed per-platform environments (darwin/linux/win32) at
  python 3.11 — never the generator's interpreter.
- **Expansion is locked-only:** unpinned dependencies become recorded leaves
  (`expansion: "not-locked"`), identical output on every generation host.
- **Failure is loud:** a pinned, reached package missing or version-skewed aborts generation
  with the exact remediation command.
- **Naming:** PEP 503 everywhere (`PyYAML→pyyaml`, `ruamel.yaml→ruamel-yaml`,
  `jaraco.classes→jaraco-classes`, `boolean.py→boolean-py`).

### 6. Proof constraints.txt is no longer treated as runtime truth

- The SBOM now marks each of the 80 pins with the partition's verdict: **53 runtime / 26
  development / 1 unassigned** — the file itself now says it is an environment lock with a
  runtime subset, not a runtime list.
- `certifi` (MPL-2.0) is scoped `development` — the exact misclassification the v1 design would
  have shipped is now structurally impossible.
- An injected bogus pin (`left-pad==1.0.0`, adversarial run) enters **neither** closure and
  surfaces as `unassigned` — constraints.txt cannot smuggle anything into runtime.

### 7. Deterministic-generation measurements

| Check | Result |
|---|---|
| Two consecutive generations | byte-identical (test-pinned) |
| Tracked file vs regeneration | byte-identical (test + CI interlock, run live: `git diff --exit-code` clean) |
| **Fresh clone with `core.autocrlf=true`** | manifest and SBOM both **BYTE-IDENTICAL** to working-tree generation |
| CRLF bytes in either artifact | 0 (written `newline="\n"`; `.gitattributes` pins `eol=lf`) |
| Root-order shuffle | identical output |

### 8. SBOM before/after

| | Before | After |
|---|---|---|
| Components | 80 | 80 (same universe — it remains the environment inventory) |
| Scope information | none | CycloneDX `scope` + `founderos:scope` + `founderos:platforms` per component |
| Licence data | **0 of 80** | **80 of 80** declared-licence strings from pinned metadata |
| `rfc3987` | listed, nothing said | listed, `scope=required`, licence **`GNU GPLv3+`** — honestly visible until A1 removes it |
| Name normalization | casefold, dots kept | PEP 503 (`boolean-py`, `ruamel-yaml`) |
| Line endings | platform-dependent write | LF explicit |

### 9. sdist contents audit

`MANIFEST.in` converts the previously unenumerated sdist into an allow-list. Measured by
building the real sdist in-process (also a permanent test):

- **No** `tests/` (previously 174 files shipped, one carrying a verbatim third-party device
  banner), **no** `docs/`, **no** `.atlas/` (281 MB of live lab data in the working tree),
  **no** `configs/`, `enterprise-memory/`, `deliverables/`, `_zip/`, **no** `*.zip`.
- `compliance/runtime-manifest.json` **travels with the sdist** — the evidence ships beside the
  code it describes, as the architecture review's MANIFEST.in amendment required.

### 10. Licence-evidence model (structural, A2-ready)

Every pinned runtime entry carries `license_evidence`: declared expression/field/classifiers,
`evidence_files` (dist-info), `nested_evidence_files` (in-package), `component_sboms`,
`rejected_root_paths`, and factual `observations`. The review's hard cases, all represented and
test-pinned:

| Case | Representation |
|---|---|
| netmiko root-LICENSE collision | root path **rejected** (`root-level-evidence-ignored`); dist-info + `_telnetlib/LICENSE` (PSF) attributed correctly |
| ntc_templates root-LICENSE collision | root path rejected — the wrong-attribution failure is structurally impossible |
| cryptography static linkage | both bundled CycloneDX SBOMs recorded (`dist-info/sboms/…`) |
| PyNaCl libsodium | doubly-nested `licenses/licenses/LICENSE.libsodium.txt` preserved unflattened |
| werkzeug icon licence | `debug/shared/ICON_LICENSE.md` as nested evidence |
| pyserial | `no-license-file-shipped` — recorded, not fatal (A2's gate decides policy) |
| isoduration | `metadata-license-unknown` + `bundled-license-text-present` |

### 11. Adversarial results — 15 of 15 pass

1. Ambient stray packages (`cairosvg`, `pillow`, `build`) unreachable — pinned by test.
2. Missing/skewed runtime package → loud `EnvironmentMismatch` — pinned by test.
3. Injected constraints pin → `unassigned`, never runtime/dev — run live.
4/5. win32 and linux markers evaluated explicitly and correctly — pinned by tests.
6. pyproject declaration order shuffled → identical output — pinned by test.
7. Mixed name casing → one normalized identity — pinned by test.
8. Double generation → byte-identical — pinned by test.
9/10. Fresh `autocrlf=true` clone → both artifacts byte-identical — run live.
11. Root-LICENSE collision as evidence → impossible — pinned by test.
12. cryptography nested SBOM representation — pinned by test.
13. sdist leakage (lab data, ZIPs, tests) → none — pinned by test.
14. Deliberately stale manifest → CI diff-check **fails** — run live in a clone.
15. Deliberately stale SBOM → CI diff-check **fails** — run live (first attempt was a no-op
    mutation — the file contains no literal `80` bytes; re-run with a real version-string
    mutation and caught).

### 12. Final test counts

Focused: `test_compliance_foundation.py` **26 passed**; with `test_release_trust.py`:
**48 passed, 31 subtests**. CI interlock run locally: regeneration reproduces tracked bytes,
`git diff --exit-code` clean.

Full suite at final HEAD: **3371 passed, 2 skipped, 1130 subtests passed, 0 failed** —
the 3345 baseline plus the 26 new foundation tests, no regressions.

### 13. Deviations from the architecture

1. **`audit_dependencies.py` was documented, not converted.** The review said "consumed …
   where appropriate"; narrowing the vulnerability audit to the runtime closure would REDUCE
   security coverage, so its whole-lock scope is now an explicit, commented decision referencing
   the shared rule. The partition consumers are the manifest and the SBOM.
2. **The manifest carries licence evidence already.** The review placed evidence collection in
   A2's generator; collecting the structural facts in A0 costs nothing extra, made the hard-case
   representation provable now, and A2 still owns all classification.
3. **`unassigned` bucket added** (not in the review's two-way split): pins reachable from neither
   root set surface explicitly (`setuptools`) instead of disappearing — and it is the landing
   zone that makes adversarial attack 3 visible.

### 14. Residual risks

- The five not-locked leaves (notably `secretstorage`/`jeepney` on linux) are honest records of
  a constraints.txt gap — pinning them is a small follow-up best taken with A1's lock edit.
- `.gitattributes` pins only the compliance surface; the wider repository remains
  autocrlf-variable by design (no churn), which A2 must remember when it adds licence texts
  (they land under `compliance/**`, already covered).
- The sdist test builds in-process with setuptools; if a future packaging change moves to
  isolated builds, the test's cwd-based invocation will need the same move.

### 15. Readiness for A1

**A1 is now safe to begin.** Its edit surface is exactly: `pyproject.toml` (extra swap),
`constraints.txt` (−`rfc3987`, +`rfc3986-validator`, +`rfc3987-syntax`, +`lark`), regeneration of
**both** tracked artifacts (the CI interlock that would have failed the v1 plan is now the
guard that proves A1 correct), and the schema-equivalence tests. The manifest will show the GPL
package leaving the runtime closure as a one-line diff in a tracked file.

---

### Stop-condition report

1. **Commits:** `c112858`, `0a46816`, `c850c21`, `9aba223` (4).
2. **Final tests:** foundation 26/26; full suite 3371 / 2 skipped / 1130 subtests / 0 failed.
3. **Runtime count per platform:** win32 **56**, linux **56**, darwin **54** (union 58).
4. **Dev-only count:** **26**; unassigned **1**.
5. **Manifest generation byte-stable:** **yes** — twice-run, fresh-clone and autocrlf all
   byte-identical.
6. **SBOM regeneration clean:** **yes** — `git diff --exit-code` clean locally; CI interlock
   extended to both artifacts.
7. **Fresh-clone/autocrlf attack:** **passes** (byte-identical).
8. **sdist leakage check:** **passes** — no lab data, no ZIPs, no tests/; compliance/ included.
9. **Deviations:** three, listed in §13, all scope-conservative.
10. **A1 safe to begin:** **yes.**

*LICENSE unchanged. `jsonschema[format]` unchanged. `rfc3987` unchanged. Nothing pushed.*
