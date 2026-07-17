# PR-049 — Production Multi-Vendor Foundation (POLYGLOT) — Handover

**Status:** foundation + all four Wave-1 drivers implemented and
transcript-tested. **Not committed.**
**Regression:** 1,496 passed, 1 skipped, 137 subtests (was 1,453 — +43, 0 broken).

## Support maturity — the honest table

| Platform | Maturity | Basis |
|---|---|---|
| Cisco IOS-XE | **EXPERIMENTAL** | TRANSCRIPT-VALIDATED — LIVE VALIDATION PENDING |
| Cisco NX-OS | **EXPERIMENTAL** | TRANSCRIPT-VALIDATED — LIVE VALIDATION PENDING |
| Arista EOS | **EXPERIMENTAL** | TRANSCRIPT-VALIDATED — LIVE VALIDATION PENDING |
| Juniper Junos | **EXPERIMENTAL** | TRANSCRIPT-VALIDATED — LIVE VALIDATION PENDING |
| FRRouting / Cisco IOS / AtlasLab (pre-existing) | unchanged | live-validated on the lab |

**No Wave-1 platform is BETA or PRODUCTION.** No IOS-XE, NX-OS, EOS or Junos
device (physical or virtual image) was available in this environment, so
Parts 19's live validation and the 15-step manual validation **could not be
performed** — parsers ran only against sanitized transcripts of realistic
output that I authored from platform knowledge. A guard test
(`test_no_wave1_driver_claims_more_than_transcripts_prove`) pins every Wave-1
driver at EXPERIMENTAL so maturity cannot be granted by accident; it must be
earned by live evidence and a deliberate test change recording it.

## Delivered (mapping to the 19 deliverables)

1. **Audit** — `docs/platforms/DRIVER_AUDIT.md`. Headline findings: the
   transport was hard-locked to Cisco netmiko personalities; exec failures
   were recorded as "unavailable" (FAILED masquerading as UNSUPPORTED);
   detection was first-match boolean; policies are Cisco-syntax-specific with
   no N/A path; no fallbacks, no maturity vocabulary.
2. **Contract** — `platforms/production.py` (`ProductionDriver`) extends the
   proven base: per-driver session profile, command fallbacks, five honest
   statuses, tier gating, diagnostics. `docs/platforms/DRIVER_CONTRACT.md`.
3. **Capability model** — `platforms/capabilities.py`: 22-term vocabulary,
   5 statuses, 3 tiers, maturity levels. `docs/platforms/CAPABILITY_MATRIX.md`.
4. **Detection** — `registry.identify()`: deterministic confidence (0.9 unique
   / 0.6 contested / 0.95 override, capped), evidence, alternatives, reason,
   operator override (`driver_for` + `identify(override=)`). The IOS-XE↔IOS
   contest is *reported*, not hidden.
5–8. **Four drivers** — `drivers/ios_xe.py`, `nxos.py`, `eos.py`, `junos.py`.
   Each with its own refusal grammar, management-endpoint preference
   (mgmt-VRF / Management1 / me0-fxp0), platform-distinctive metadata
   (inventory+HSRP / vPC+port-channels / MLAG / logical units+instances), and
   netmiko personality. Transport now accepts all five device types and its
   lying "requires a Cisco IOS device" message is fixed.
9. **Fixtures** — `tests/platform_fixtures/{ios_xe,nxos,eos,junos}.py`:
   sanitized realistic transcripts (documentation addresses, lab hostnames,
   invented serials) incl. degraded variants (LLDP disabled, feature absent,
   unsupported, privilege denied, empty).
10. **Cross-vendor contract results** — `CrossVendorContractTests` runs 8
    invariants over every driver: identity, endpoint preservation, unique
    interfaces, honest config status, raw retention, FAILED≠UNSUPPORTED≠empty,
    partial preservation, serializable+complete diagnostics matrix,
    determinism, no secret leakage. All pass for all four.
11. **Mixed-vendor topology** — `MixedVendorNormalizationTests`: the fixture
    estate is a real square (XE↔NX-OS via CDP+LLDP, XE↔EOS, NX-OS↔EOS,
    Junos↔EOS, Junos↔XE); both ends of every pair name each other identically
    after normalization — the precondition correlation needs. No driver
    builds an edge.
12. **Memory/Explorer** — raw outputs flow through the *unchanged* sink; the
    sink learned Junos's configuration commands (`show configuration |
    display set`) so Junos devices get snapshots. Diagnostics live in device
    metadata. *Not validated in the browser* — a fixture cannot flow through
    a live discovery, and there is no live Wave-1 device (see Limitations).
13. **Policy compatibility** — reviewed, NOT fixed: see Limitations #2.
14. **Performance** — tiers implemented end-to-end in the contract
    (FAST/STANDARD/DEEP; skipped = NOT_ATTEMPTED by name; default STANDARD
    preserves today's behaviour). *Timings not measured* — meaningless
    against fixtures. The tier is recorded in diagnostics; plumbing an
    operator-selectable tier through profiles is Wave-2 work.
15. **Live validation evidence** — none exists, and none is claimed.
16. Maturity table above. 17. Test results above (1,496 green).

## Remaining limitations (the honest list)

1. **Detection-then-redispatch is not wired.** Discovery still connects with
   the default netmiko personality, probes, then detects. The driver now
   *declares* its personality, but multihop does not yet reconnect/redispatch
   an NX-OS/EOS/Junos session onto it — harmless for probing (these CLIs
   tolerate the probe), but session robustness (prompts, paging) on real
   devices needs the redispatch step + live testing. This is the single
   biggest gap between "transcript-validated" and "works on your Nexus".
2. **The Starter Policy Pack is Cisco-syntax-specific.** A Junos config
   (`set system ntp server …`) would FAIL "NTP Configured" it doesn't
   violate. Policies need either per-platform directive normalization or a
   platform-applicability field with an honest Not-Applicable verdict.
   Deliberately not half-built here; it is the first Wave-2 item.
3. **Operator override is registry-level, not yet a profile field** — the
   mechanism and tests exist; the wizard checkbox does not.
4. **Tier selection isn't operator-facing** (contract-complete, UI absent).
5. Per-command durations aren't captured (the record field exists in memory's
   schema; the transport doesn't time commands yet).
6. Junos route/OSPF/BGP parsing summarizes; per-instance detail is future.
7. Manual validation steps 1–15: **pending live devices, all of them.**

## Recommended Wave 2

1. Live-validate Wave 1 on virtual images (CML/EVE-NG: IOS-XE, NX-OS 9300v,
   vEOS, vJunos) → promote to BETA per platform with recorded evidence.
2. Session redispatch (netmiko `redispatch`) after detection + banner/enable
   handling tests against live prompts.
3. Policy platform-applicability + directive normalization (Junos/EOS).
4. FortiOS + PAN-OS with the separate firewall evidence model PR-048 started.
5. Profile-level platform override + collection-tier selection in the wizard.
