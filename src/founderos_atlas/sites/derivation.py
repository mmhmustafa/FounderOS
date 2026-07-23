"""Derive candidate sites from the hostname convention and the topology.

Atlas assigns a device to a site only from a *declared* convention — it
never invents a site (see `inference.py`). That is the right default for a
curated estate, but it fails the un-curated one: 117 devices named
``<city>-<tier>-<role>`` across 19 cities, with a catalog that names four,
collapse to one unreadable blob and a wall of "Site not identified".

This module supplies the missing signal WITHOUT abandoning the honesty
posture. It reads the hostnames and the observed adjacency and proposes
sites, which the ordinary inference engine then assigns against — so a
device placed into a derived site is still marked low-confidence and
inferred, and an operator can confirm, rename or reject it. Nothing here
overrides a declared site or an operator override; it only fills silence.

Two questions decide the outcome, both answered from evidence, not names:

  Is a prefix a SITE or FABRIC?
    A prefix cluster is a site when its own devices are wired to each
    OTHER — a real branch is internally cohesive. A cluster whose devices
    only reach outward, either to many different sites (an internet edge
    that serves all of them) or to nothing but unresolved core peers (a
    WAN provider-edge mesh), is fabric: it belongs to no one premises, and
    labelling it a site would misdraw the network.

  Where does a FABRIC device belong?
    To the site its links most point at, when one site clearly dominates —
    proximity is the real signal. When its links spread evenly across
    sites, there is no closest, and it stays unidentified rather than
    being assigned by a coin-flip.

Every threshold here was set against a real 117-device, 19-city capture,
not chosen in the abstract.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .models import (
    Site,
    SiteCatalog,
    site_id_for,
)


# A prefix carried by fewer devices than this is too thin to call a site on
# its own — one device sharing a token is coincidence, not a convention.
MIN_CLUSTER_SIZE = 2

# A fabric device is placed only when one neighbouring site holds strictly
# more of its links than any other. A tie is honestly no-answer.
# (No ratio threshold beyond "strictly greatest": a clear plurality is the
# weakest claim worth making, and anything stronger would discard real
# leans the operator would recognise.)


@dataclass(frozen=True)
class DerivedDevice:
    """One device as the deriver sees it: an id and a hostname."""

    device_id: str
    hostname: str


@dataclass(frozen=True)
class DerivationResult:
    """Derived sites, plus the fabric devices placed by adjacency.

    ``catalog`` holds only the DERIVED sites (pattern-matched premises).
    ``fabric_placements`` maps a fabric device id to the site it leans on,
    attached to that site as an explicit assignment so the ordinary engine
    picks it up. ``fabric_unplaced`` is the honest remainder: fabric with
    no clear home, left for the operator or for "Site not identified".
    """

    catalog: SiteCatalog
    fabric_placements: Mapping[str, str]
    fabric_unplaced: tuple[str, ...]
    diagnostics: Mapping[str, str]


def hostname_prefix(hostname: str | None) -> str | None:
    """The leading token of a conventional hostname, or None.

    ``chennai-branch-core`` -> ``chennai``. A name with no separator has no
    convention to read and yields None rather than itself, so a one-off box
    called ``firewall`` never seeds a site.
    """

    text = (hostname or "").strip().casefold()
    if "-" not in text:
        return None
    head = text.split("-", 1)[0]
    return head or None


def derive_sites(
    devices: Iterable[DerivedDevice | Mapping[str, str]],
    edges: Iterable[Mapping[str, object]] = (),
    *,
    existing_catalog: SiteCatalog | None = None,
) -> DerivationResult:
    """Propose sites for devices no declared site already covers.

    ``edges`` are the topology's adjacency records — each carries a
    ``local_device_id`` and a ``remote_hostname`` (the LLDP shape Atlas
    already stores). They decide site-vs-fabric and place fabric devices;
    with no edges the function still clusters by name, treating every
    cluster as a site (there is no evidence to call any of them fabric).
    """

    catalog_devices = [_as_device(item) for item in devices]
    declared = existing_catalog or SiteCatalog()
    declared_prefixes = _declared_prefixes(declared)

    id_to_name = {d.device_id: d.hostname for d in catalog_devices}
    by_prefix: dict[str, list[DerivedDevice]] = defaultdict(list)
    for device in catalog_devices:
        prefix = hostname_prefix(device.hostname)
        if prefix:
            by_prefix[prefix].append(device)

    # Undirected neighbour prefixes for every device, plus a raw degree
    # (edges of any kind, including to unresolved peers). The degree is what
    # tells "no adjacency evidence at all" — trust the name — apart from
    # "has links, but none internal" — a core that only faces outward.
    edge_list = list(edges)
    neighbours = _neighbour_prefixes(edge_list, id_to_name)
    raw_degree = _raw_degree(edge_list, id_to_name)

    site_prefixes: set[str] = set()
    fabric_prefixes: set[str] = set()
    diagnostics: dict[str, str] = {}
    for prefix, members in by_prefix.items():
        if len(members) < MIN_CLUSTER_SIZE:
            diagnostics[prefix] = "too few devices to call a site"
            continue
        classification = _classify(
            prefix, members, neighbours, raw_degree, set(by_prefix)
        )
        diagnostics[prefix] = classification
        if classification == "site":
            site_prefixes.add(prefix)
        else:
            fabric_prefixes.add(prefix)

    # Derived sites: one per site-prefix Atlas has not already declared. A
    # declared site wins outright — the operator's word is not re-derived.
    derived: list[Site] = []
    for prefix in sorted(site_prefixes):
        if prefix in declared_prefixes:
            continue
        derived.append(Site(
            site_id=site_id_for(prefix),
            name=prefix.capitalize(),
            hostname_patterns=(f"{prefix}-*",),
            description="Derived from hostname convention — confirm or rename.",
        ))
    derived_catalog = SiteCatalog(sites=tuple(derived))
    derived_ids = {site.site_id for site in derived}

    # Every device NOT in a site of its own is a placement candidate:
    # fabric-cluster members, a lone shared box, a device with no
    # convention at all. Each goes to the site its links most point at, or
    # stays unidentified when they do not point one way.
    placeable_site_ids = derived_ids | set(declared_prefixes.values())
    placements: dict[str, str] = {}
    unplaced: list[str] = []
    for device in catalog_devices:
        prefix = hostname_prefix(device.hostname)
        if prefix in site_prefixes:
            continue                   # belongs to its own derived site
        if prefix and prefix in declared_prefixes:
            continue                   # a declared site will claim it
        home = _plurality_site(
            neighbours.get(device.device_id, Counter()), site_prefixes,
        )
        site_id = site_id_for(home) if home else None
        if site_id and site_id in placeable_site_ids:
            placements[device.device_id] = site_id
        else:
            unplaced.append(device.device_id)

    return DerivationResult(
        catalog=derived_catalog,
        fabric_placements=placements,
        fabric_unplaced=tuple(sorted(unplaced)),
        diagnostics=diagnostics,
    )


def _as_device(item: DerivedDevice | Mapping[str, str]) -> DerivedDevice:
    if isinstance(item, DerivedDevice):
        return item
    return DerivedDevice(
        device_id=str(item.get("device_id") or item.get("id") or ""),
        hostname=str(item.get("hostname") or ""),
    )


def _declared_prefixes(catalog: SiteCatalog) -> dict[str, str]:
    """{prefix: site_id} for every ``<prefix>-*`` a declared site already
    claims, so derivation never proposes a site the operator has named."""

    claimed: dict[str, str] = {}
    for site in catalog.sites:
        for pattern in site.hostname_patterns:
            token = pattern.strip().casefold()
            if token.endswith("-*"):
                claimed[token[:-2]] = site.site_id
    return claimed


def _neighbour_prefixes(
    edges: Iterable[Mapping[str, object]], id_to_name: Mapping[str, str]
) -> dict[str, Counter]:
    """Per device id, a Counter of its neighbours' hostname prefixes.

    Built UNDIRECTED — LLDP is captured from one end, so a link only shows
    up on the local device's edge, and counting both ends is what lets a
    fabric device's true fan-out be seen from either side.
    """

    name_to_id = {name: did for did, name in id_to_name.items()}
    result: dict[str, Counter] = defaultdict(Counter)
    for edge in edges:
        local_id = str(edge.get("local_device_id") or "")
        remote_name = str(edge.get("remote_hostname") or "")
        local_name = id_to_name.get(local_id)
        if not local_name or not remote_name:
            continue
        local_pref = hostname_prefix(local_name)
        remote_pref = hostname_prefix(remote_name)
        if remote_pref:
            result[local_id][remote_pref] += 1
        remote_id = name_to_id.get(remote_name)
        if remote_id and local_pref:
            result[remote_id][local_pref] += 1
    return result


def _classify(
    prefix: str,
    members: list[DerivedDevice],
    neighbours: Mapping[str, Counter],
    raw_degree: Mapping[str, int],
    all_prefixes: set[str],
) -> str:
    """"site" or "fabric" for one prefix cluster.

    Site when the cluster's own devices are wired to each other — a real
    branch is cohesive. Fabric when it has links but none internal (a core
    that only faces outward), or when it reaches across many sites with
    none dominating (an aggregation edge). No links AT ALL is not fabric:
    with no adjacency to judge, the naming convention is the only evidence
    and it is honoured.
    """

    internal = 0
    external_sites: Counter = Counter()
    for device in members:
        for neighbour_prefix, count in neighbours.get(
            device.device_id, Counter()
        ).items():
            if neighbour_prefix == prefix:
                internal += count
            elif neighbour_prefix in all_prefixes:
                external_sites[neighbour_prefix] += count

    total_degree = sum(raw_degree.get(d.device_id, 0) for d in members)
    if internal == 0:
        if total_degree == 0:
            return "site"              # no evidence; trust the convention
        return "fabric"                # has links, none of them internal
    distinct_external = len(external_sites)
    external_total = sum(external_sites.values())
    if distinct_external >= 3 and external_total > internal:
        return "fabric"                # spans many premises; it is an edge
    return "site"


def _raw_degree(
    edges: Iterable[Mapping[str, object]], id_to_name: Mapping[str, str]
) -> dict[str, int]:
    """Total links touching each device, resolved peer or not.

    Distinguishes a cluster with NO adjacency data (trust the name) from
    one whose links all go to unresolved core peers (fabric).
    """

    name_to_id = {name: did for did, name in id_to_name.items()}
    degree: dict[str, int] = defaultdict(int)
    for edge in edges:
        local_id = str(edge.get("local_device_id") or "")
        if local_id in id_to_name:
            degree[local_id] += 1
        remote_id = name_to_id.get(str(edge.get("remote_hostname") or ""))
        if remote_id:
            degree[remote_id] += 1
    return degree


def _plurality_site(
    neighbour_prefixes: Counter, site_prefixes: set[str]
) -> str | None:
    """The one neighbouring SITE prefix that dominates, or None on a tie.

    Only real site prefixes count — a fabric device's links to other fabric
    or to unresolved peers say nothing about which premises it sits in.
    """

    among_sites = Counter({
        prefix: count for prefix, count in neighbour_prefixes.items()
        if prefix in site_prefixes
    })
    if not among_sites:
        return None
    ranked = among_sites.most_common(2)
    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        return None                    # an even lean is no lean
    return ranked[0][0]
