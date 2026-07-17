# Juniper Junos — Driver Notes

**Maturity: EXPERIMENTAL — TRANSCRIPT-VALIDATED, LIVE VALIDATION PENDING.**
Fixture shapes: EX4300, 21.4R3. Read-only operational mode only —
configuration mode is never entered.

- Session: netmiko `juniper_junos`; `set cli screen-length 0` / width 0.
- Detection: `Junos: <version>` — Junos names itself; no Cisco heuristics.
- Refusal grammar is Junos's own (`unknown command`, caret) via a `rejects()`
  override; Cisco `%` conventions do not apply.
- Interfaces from `show interfaces terse`: physical and logical units both
  normalized; a unit records physical parent + unit number + address family +
  address — hierarchy preserved, not flattened.
- Management endpoint prefers me0/fxp0/em0.
- Configuration: `show configuration | display set` (fallback: plain) — one
  deterministic statement per line, hierarchy as explicit paths; recognized by
  the Enterprise Memory sink as this platform's configuration snapshot.
- Routing instances observed from route table names (`mgmt_junos.inet.0`).
- Not yet: per-instance detail, VC/chassis-cluster, IPv6 families.
