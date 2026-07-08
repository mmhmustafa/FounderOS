# Atlas Device Identity

Canonical device identity resolution: each physical device appears exactly
once in Atlas, no matter how many ways discovery sources name it.

## The problem

Real networks identify the same device differently per source:

| Source | Identifier |
| --- | --- |
| `show version` | `R1` |
| CDP neighbor advertisement | `R1.atlas.local` |
| Operator input | `r1`, `R1.` |
| Interface tables | management IP, loopback IP |
| Inventory | serial number, chassis ID, system MAC, UUID |

Without resolution, `R1` and `R1.atlas.local` render as two nodes and the
two directional CDP observations (`R1 → SW1`, `SW1 → R1`) render as two
connections.

## Canonical Identity

`DeviceIdentity` collects every identifier observed for one observation or
neighbor reference. `CanonicalDevice` is the merged result of a cluster:
one canonical hostname, all aliases, all management IPs, the serial number,
vendor/platform/OS facts, and the discovery history (observed device IDs and
sources). Nothing is destroyed — every original value survives as an alias
or in metadata.

The canonical hostname is the *bare* form (`R1`, not `R1.atlas.local`),
chosen deterministically: bare names beat FQDNs, fewer labels beat more,
then shorter, then stable string order. Original casing of the chosen value
is preserved.

Hostname normalization (`normalize_hostname`) lowercases, trims, and strips
trailing dots, so `R1`, `r1`, `R1.` and the first label of `R1.atlas.local`
all normalize to `r1` — for **matching only**; display keeps original case.

## Identity Resolution

`IdentityResolver` clusters observations with union-find over configurable
`MatchRule` predicates, applied in order:

1. `SerialNumberMatch` — exact serial number
2. `ManagementIPMatch` — any shared management IP
3. `HostnameMatch` — normalized equality, or bare name == FQDN first label

The FQDN rule requires one side to be a bare name: `web.prod.local` and
`web.dev.local` never merge (no false merges across domains). If two
*different* clusters would collapse to the same short display name, each
keeps its full name so distinct devices never share a label.

Neighbor references that match no discovered device cluster among
themselves as *observed-only* devices, so `SW9` and `SW9.atlas.local` seen
from two different neighbors still become one placeholder node.

### Extending matching (future vendors)

Rules are pure predicates — extension means appending, never editing:

```python
from founderos_atlas.identity import ExtraIdentifierMatch, DEFAULT_MATCH_RULES, IdentityResolver

resolver = IdentityResolver(rules=(*DEFAULT_MATCH_RULES, ExtraIdentifierMatch("chassis_id")))
```

`ExtraIdentifierMatch` reads identifiers (chassis ID, system MAC, UUID, …)
that adapters place in device metadata under recognized keys; any future
vendor adapter participates by populating metadata, with no changes here.

## Relationship Reconciliation

`IdentityResolution.canonicalize(results)` rewrites discovery results onto
canonical hostnames — device hostnames and neighbor references alike — and
records originals (`observed_hostname`, `observed_remote_hostname`,
`identity.aliases`) in metadata. The existing `TopologyReconciler` then
merges observations of the same device naturally, and the topology viewer
collapses the two directional observations of one physical link
(`R1 → SW1` and `SW1 → R1`) into a single displayed connection with both
interface ends. The `TopologySnapshot` keeps directed edges unchanged — the
versioned contract is untouched; only presentation merges them.

```
R1 ──────── SW1        two devices, one relationship
```

Aliases stay available in the viewer's node details panel.
