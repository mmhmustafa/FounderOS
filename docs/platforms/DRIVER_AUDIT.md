# PR-049 Part 1 — Current Driver Audit (POLYGLOT)

Audited: `platforms/base.py`, `platforms/registry.py`, `platforms/classify.py`,
drivers (`ios`, `frr`, `atlaslab_firewall`, `atlaslab_switch`, `lldpd`),
`transport/ssh.py`, `discovery/multihop.py`, `discovery/adapters/cisco_ios.py`,
`enterprise_memory/sink.py`, `policy/` pack + matcher.

## What is genuinely shared (keep — do not rewrite)

- **`PlatformDriver` base** already owns the generic collect→parse→annotate
  flow: probe matcher, `CapabilitySpec` plan, `classify_output`, capability
  stamping into canonical metadata. The four existing drivers are declarative.
- **Parse-only adapters** (`DiscoveryAdapter`): normalization never connects.
- **Evidence sink**: raw outputs and configuration snapshots are captured from
  the one authenticated session, for every driver, with provenance. No driver
  writes memory directly.
- **Correlation owns topology**: no driver constructs edges; drivers emit
  `NetworkNeighbor` observations and metadata, correlation/federation build
  the graph. Already vendor-independent.

## Vendor logic leaking into generic layers (the real findings)

1. **The transport is Cisco-locked.** `SUPPORTED_DEVICE_TYPES = ("cisco_ios",
   "cisco_xe")` and session setup hardcodes `terminal length 0`
   (`transport/ssh.py:22,39`). Every FRR and AtlasLab device this month was
   driven over netmiko's *cisco_ios* personality — it worked by coincidence
   (IOS-like prompts, setup failure tolerated). NX-OS/EOS/Junos need their own
   netmiko personalities and session preparation. **The session layer must be
   driver-selected, not hardcoded.**
2. **Exec failure is recorded as "unavailable"** (`base.py discover()`):
   a transport exception and a device saying "unknown command" collapse into
   one state. That is FAILED being reported as UNSUPPORTED — the inverse of
   the classic sin, equally dishonest. Needs a distinct FAILED state.
3. **`_ensure_command_permitted` lies** (`transport/ssh.py:229`): on any
   unrecognized command it says "Atlas live discovery requires a Cisco IOS or
   IOS-XE device" — even on FRR. Pre-dates the platform framework.
4. **Detection is first-match boolean.** `registry.detect()` returns a driver
   or None: no confidence, no evidence, no alternatives, no operator override.
5. **IOS driver is thin**: 3 commands (identity/interfaces/CDP); routes are
   honestly not-collected. Its matcher claims IOS *and* IOS-XE — fine for
   identification, but Part 7's evidence targets need a real IOS-XE plan.
6. **No fallback commands anywhere**: one `CapabilitySpec` = one command.
7. **Policies are Cisco-syntax-specific with no honest N/A path**: the starter
   pack matches directives like `hostname`/`ntp server` against config text.
   Junos (`host-name`, `system { }` hierarchy) would FAIL policies it doesn't
   violate. `Policy` has no platform scoping field.
8. **No maturity vocabulary**: nothing distinguishes a transcript-tested
   driver from a live-validated one.

## Platform-specific assumptions found (and where)

- IOS-only: CDP as the only neighbor source in `cisco_ios` adapter; `%`-prefix
  error classification in `base.classify_output` (vtysh/IOS convention —
  AtlasLab drivers already had to override it; Junos errors look different).
- FRR-only: vtysh single-mode CLI; hostname parsed from `show version` banner.
- Lab-only: AtlasLab identity regexes; registry registers lab drivers last so
  they can never shadow production platforms (correct, keep).

## Duplication

- `_valid_ip` / `_split_os` / identity-regex parsing repeated across the two
  AtlasLab drivers (acceptable, small); interface-line parsing of `ip -br addr`
  duplicated between them (candidate for a shared helper, not urgent).

## Conclusion

The base contract is sound and extensible — PR-049 **extends** it
(capabilities vocabulary, fallbacks, per-driver session profile, detection
detail, FAILED state, maturity) rather than replacing it. The transport's
device-type lock and the failed/unsupported conflation are the two changes
generic layers actually require; everything else is additive.
