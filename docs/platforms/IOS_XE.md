# Cisco IOS-XE — Driver Notes

**Maturity: EXPERIMENTAL — TRANSCRIPT-VALIDATED, LIVE VALIDATION PENDING.**
Fixture shapes: Catalyst 9300, 17.09.x. Privilege: read-only exec (priv-15
only for `show running-config` on some AAA setups — privilege-denied is
reported FAILED with the reason, everything else survives).

- Session: netmiko `cisco_xe`; setup `terminal length 0`, `terminal width 511`.
- Detection: `Cisco IOS XE Software` in `show version`; registered before
  legacy IOS (whose matcher also accepts XE), so order is load-bearing.
- Commands: version, inventory, ip interface brief, interfaces, lldp detail
  (fallback: brief), cdp detail, ip route, bgp summary, ospf neighbor, vlan
  brief, etherchannel, running-config; DEEP adds mac address-table
  (fallback: `show mac-address-table`), spanning-tree, standby brief.
- Quirks handled: NX-OS serials in CDP Device IDs (`name(SERIAL)`),
  `administratively down` → down, `unassigned` addresses.
- Not yet: VRF-aware routing tables, IPv6, stackwise detail.
- Troubleshooting: check `driver_diagnostics` in device metadata — every
  command attempted, which succeeded, why fallbacks fired.
