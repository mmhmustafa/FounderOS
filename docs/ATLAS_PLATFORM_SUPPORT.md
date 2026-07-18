# Atlas Platform Support (POLYGLOT Wave 2)

One driver architecture, many vendors. Every platform below is driven
through the same Production Driver Contract (`platforms/production.py`)
or, where no CLI dialect exists, through an API-native collector
(`collectors/`). Downstream — Topology, Policy, Advisor, Prediction,
Enterprise Memory, the Evidence Explorer — consumes only canonical
models and normalized evidence. **No downstream component branches on a
vendor.**

## Validation vocabulary

- **PRODUCTION** — validated against live devices in a production-like
  environment.
- **TRANSCRIPT VALIDATED** — every parser is exercised against
  sanitized transcripts of realistic device/API output. *No live device
  of this platform was available; production support is deliberately
  NOT claimed.*

## Supported Platforms Matrix

| Platform | Driver / Collector | Transport | Tier | Validation |
|---|---|---|---|---|
| Cisco IOS-XE | `CiscoIOSXEDriver` | SSH (netmiko `cisco_ios`) | Wave 1 | TRANSCRIPT VALIDATED |
| Cisco IOS (classic) | `CiscoIOSDriver` | SSH | Wave 1 | Live-lab validated (CML) |
| Cisco NX-OS | `CiscoNXOSDriver` | SSH (`cisco_nxos`) | Wave 1 | TRANSCRIPT VALIDATED |
| Arista EOS | `AristaEOSDriver` | SSH (`arista_eos`) | Wave 1 | TRANSCRIPT VALIDATED |
| Juniper Junos | `JunosDriver` | SSH (`juniper_junos`) | Wave 1 | TRANSCRIPT VALIDATED |
| FRRouting | `FRRoutingDriver` | SSH (vtysh) | Wave 1 | Live-lab validated |
| **Fortinet FortiOS** | `FortiOSDriver` + `FortiOSRestCollector` | SSH (`fortinet`) + REST | **1** | TRANSCRIPT VALIDATED |
| **Palo Alto PAN-OS** | `PanOsDriver` + `PanOsXmlApiCollector` | SSH (`paloalto_panos`) + XML API | **1** | TRANSCRIPT VALIDATED |
| Aruba CX | `ArubaCXDriver` | SSH (`aruba_aoscx`) | 2 | TRANSCRIPT VALIDATED |
| Cisco WLC (AireOS) | `CiscoWlcDriver` | SSH (`cisco_wlc`) | 2 | TRANSCRIPT VALIDATED |
| VMware NSX | `NsxCollector` | REST (Policy/Manager API) | 2 | TRANSCRIPT VALIDATED |
| F5 BIG-IP | `F5BigIpDriver` | SSH (tmsh) | 3 | TRANSCRIPT VALIDATED |
| Citrix ADC | `CitrixAdcDriver` | SSH (`netscaler`) | 3 | TRANSCRIPT VALIDATED |
| A10 ACOS | `A10AcosDriver` | SSH (`a10`) | 3 | TRANSCRIPT VALIDATED |
| AWS VPC | `AwsVpcCollector` | AWS API payloads (injected client) | 4 | TRANSCRIPT VALIDATED |
| Azure Virtual Network | `AzureVnetCollector` | ARM API payloads | 4 | TRANSCRIPT VALIDATED |
| Google Cloud VPC | `GcpVpcCollector` | Compute API payloads | 4 | TRANSCRIPT VALIDATED |

AtlasLab firewall/switch (lab platforms) remain registered last so a
lab dialect can never shadow a production one.

## Capability matrix (SSH drivers)

Capability states are honest per attempt: `supported`,
`supported-with-limitations`, `unsupported` (the device said so),
`failed` (the transport broke), `not-attempted` (excluded by tier).

| Capability | IOS-XE | NX-OS | EOS | Junos | FortiOS | PAN-OS | Aruba CX | WLC | F5 | Citrix | A10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Identity (hostname/model/serial/version) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Interfaces + addresses | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (self-IPs) | ✓ (NSIP/SNIP/VIP) | ✓ |
| Neighbors (LLDP/CDP) | ✓ | ✓ | ✓ | ✓ | — | ✓ LLDP | ✓ LLDP | ✓ via AP CDP | — | — | — |
| Routes | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | n/a | — | — | — |
| OSPF | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | n/a | — | — | — |
| BGP | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | n/a | — | — | — |
| VRFs | ✓ | ✓ | ✓ | ✓ | — | ✓ (virtual routers) | — | n/a | — | — | — |
| VLANs | ✓ | ✓ | ✓ | ✓ | — | — | ✓ | n/a | — | — | — |
| LAG | ✓ | ✓ | ✓ | ✓ | — | — | ✓ | n/a | — | — | — |
| Configuration snapshot | ✓ | ✓ | ✓ | ✓ | ✓ (deep tier) | ✓ (deep tier) | ✓ (deep tier) | ✓ (deep tier) | — | — | — |
| Firewall evidence (zones/policies/NAT/VPN/HA/virtual-fw) | — | — | — | — | ✓ | ✓ | — | — | — | — | — |
| Wireless evidence (APs/WLANs/redundancy) | — | — | — | — | — | — | — | ✓ | — | — | — |
| ADC evidence (virtual servers) | — | — | — | — | — | — | — | — | ✓ | ✓ | ✓ |
| Raw command outputs preserved | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## Firewall driver architecture

Firewalls are not routers. Routed facts (interfaces, routes, OSPF/BGP)
normalize into the same canonical models as every layer-3 device; what
makes a firewall a firewall normalizes into the vendor-neutral models
in `founderos_atlas/firewall/models.py`:

- **FirewallZone** — segmentation primitive, interface bindings, per
  virtual context.
- **SecurityPolicy** — one ordered rule *summary* (match tuple,
  normalized action, enabled, hit count). FortiOS `accept` and PAN-OS
  `allow` are both canonical `allow`. **Evidence only** — no rule
  judgement, and no full rule analysis in this wave.
- **NatRule** — normalized direction (source/destination/static),
  endpoint names only.
- **VpnTunnel** — identity + observed state. Keys and certificates are
  never represented.
- **VirtualContext** — a VDOM (FortiOS) or vsys (PAN-OS): one physical
  box, many isolated firewalls, one canonical concept.
- **HaPeer** — availability mode (`a-p`/`a-a`), peer identity, sync
  state.

The driver stamps `FirewallEvidence.to_dict()` into
`device.metadata["firewall_evidence"]`. Role classification
(`platforms/classify.py`) reads the normalized summary — never a
vendor name.

## API support (coexisting with SSH)

`platforms/api_collectors.py` merges API evidence into an existing SSH
discovery:

- **FortiOS REST** (`/api/v2/...`): policy set, zones, VPN state.
- **PAN-OS XML API** (`type=op` commands): identity corroboration, VPN
  state, HA.

Contract: the fetcher is injected (already authenticated — Atlas ships
no HTTP client or credentials here); raw responses are preserved under
`api:<path>` beside CLI transcripts; the API's structured answer wins
per section while CLI evidence survives wherever the API had nothing;
an unreachable API is recorded and never damages CLI evidence.

Cloud and NSX collectors are API-native for the same reason and follow
the same raw-preservation rule.

## Platform detection

`registry.identify()` returns platform, confidence, evidence and
alternative candidates. Sources, strongest first:

1. **Probe output** (authoritative): each dialect's identity command —
   `show version`, `get system status`, `show system info`,
   `show sysinfo`, `show sys version`, `show ns version`. A device that
   fails one dialect's probe still gets every other dialect's turn.
2. **Banner/prompt fingerprints** (corroboration): per-driver regexes.
   They add evidence lines and break ties between contesting matchers
   (0.6 → 0.9); a fingerprint alone never selects a driver.
3. **Operator override** (0.95): selects the driver, never erases what
   detection saw.

## Read-only transport policy

The transport allowlist grew with the new dialects and stays an
explicit, audited grammar: `show`, `get` (FortiOS), `display`, `list`
(tmsh), plus the exact session-presentation prefixes `set cli ` (PAN-OS)
and `config paging ` (AireOS). Everything else is refused before it
reaches a device.

## Known limitations

- Every Wave-2 platform is **TRANSCRIPT VALIDATED**; none claims
  production support until validated against live devices.
- FortiOS/PAN-OS firewall **rule analysis is out of scope** by design —
  evidence summaries only.
- FortiOS VDOM inventory reads global-scope output; per-VDOM command
  scoping (`config vdom; edit <vdom>`) is refused by the read-only
  transport, so per-context counts are global approximations until an
  API-scoped collection lands.
- PAN-OS zones are read from the logical-interface table; a zone with
  no interface binding appears only via the rulebase.
- WLC support targets AireOS; Catalyst 9800 (IOS-XE based) detects as
  IOS-XE and collects routed evidence, not wireless evidence.
- Cloud collectors consume injected SDK payloads; Atlas ships no cloud
  SDK, no credentials handling, and no live API client. Cloud network
  records use the adapter-boundary `CloudNetworkRecord` (a VPC has no
  management IP; the strict canonical `NetworkDevice` contract is
  unchanged).
- F5/Citrix/A10 collect identity, addresses and virtual-server
  summaries; pool members, certificates and persistence internals are
  deliberately not collected.
