# Arista EOS — Driver Notes

**Maturity: EXPERIMENTAL — TRANSCRIPT-VALIDATED, LIVE VALIDATION PENDING.**
Fixture shapes: 7050X, 4.30.x. CLI text only — **eAPI is not required**; it
can arrive later as an alternative transport behind the same command plan.

- Session: netmiko `arista_eos`; `terminal length 0`, width 32767.
- Detection: `Arista <model>` + `Software image version:` — two signals, so a
  Cisco banner can never satisfy it.
- Identity requires TWO commands: `show version` (no hostname on EOS) and
  `show hostname` — both required; the driver says so if either fails.
- Interface briefs carry CIDR addresses; Management1 preferred as endpoint.
- MLAG summarized (domain, peer, state) as SUPPORTED_WITH_LIMITATIONS —
  port-channel detail is stated future work.
- Not yet: eAPI, `show inventory` parsing (collected raw only), VRF routing detail.
