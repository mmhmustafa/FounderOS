# Cisco NX-OS — Driver Notes

**Maturity: EXPERIMENTAL — TRANSCRIPT-VALIDATED, LIVE VALIDATION PENDING.**
Fixture shapes: Nexus 9300, 10.2(x). Privilege: network-operator suffices for
all reads except some `show running-config` configurations.

- Session: netmiko `cisco_nxos`; `terminal length 0`.
- Detection: `Cisco Nexus Operating System (NX-OS)`.
- The management endpoint prefers mgmt0 in VRF "management"
  (`show ip interface vrf all`); every interface carries its VRF in metadata.
- vPC domain/role/peer-status and port-channel membership are summarized into
  canonical metadata. Feature-gated protocols (e.g. `show hsrp brief` without
  `feature hsrp`) report UNSUPPORTED — a platform fact, never a failure.
- Not yet: per-VRF route parsing detail, vPC consistency checks, FEX.
