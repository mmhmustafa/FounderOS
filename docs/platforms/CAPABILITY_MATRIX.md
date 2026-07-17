# Capability Matrix (PR-049)

Vocabulary: `platforms/capabilities.py`. Statuses: SUPPORTED /
SUPPORTED_WITH_LIMITATIONS / UNSUPPORTED / NOT_ATTEMPTED / FAILED.
Unsupported is never failed; empty is never failed. Tiers: FAST ⊂ STANDARD ⊂
DEEP; a skipped capability reports NOT_ATTEMPTED.

Planned collection per Wave-1 driver (fixture-proven; live pending):

| Capability | IOS-XE | NX-OS | EOS | Junos |
|---|---|---|---|---|
| identity (required) | ✓ | ✓ | ✓ (+`show hostname`, required) | ✓ |
| interface-addresses (required) | ✓ brief | ✓ `vrf all` | ✓ brief (CIDR) | ✓ terse (units) |
| lldp | ✓ detail→brief | ✓ | ✓ | ✓ |
| cdp | ✓ | ✓ | — | — |
| inventory | ✓ | ✓ | ✓ | ✓ chassis hw |
| routes | ✓ | ✓ vrf all | ✓ vrf all→plain | ✓ (tables observed) |
| bgp / ospf | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ |
| vlan / vrf | ✓ / — | ✓ / ✓ | ✓ / ✓ | — / limited (instances) |
| lag | etherchannel | port-channel + vPC | MLAG (limited) | — |
| configuration | ✓ | ✓ | ✓ | ✓ `| display set` |
| mac-table / stp / fhrp | DEEP | DEEP / DEEP / DEEP* | DEEP / — / — | DEEP / — / — |

`*` NX-OS HSRP requires `feature hsrp`; disabled reports UNSUPPORTED honestly.
