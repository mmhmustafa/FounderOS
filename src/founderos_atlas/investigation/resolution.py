"""Entity resolution (PR-167, Part 2).

Turn the names in a question into things Atlas has actually
discovered — or say plainly that it cannot.

Three outcomes per name, and only three:

* RESOLVED  — exactly one site or device matches.
* AMBIGUOUS — several match. Every candidate is reported and the
  investigation stops short of pretending. Choosing one would be a
  guess wearing a fact's clothing.
* UNKNOWN   — nothing matches. Atlas says so, and says what it does
  know, rather than substituting an estate-wide answer.

Sites resolve before devices because an operator naming "Mumbai" means
the site; only if no site matches is the name tried as a device.
"""

from __future__ import annotations

from .models import (
    AMBIGUOUS,
    RESOLVED,
    UNKNOWN,
    ResolvedEntities,
    ResolvedEntity,
)


def _folded(value: object) -> str:
    return str(value or "").strip().casefold()


def site_members(graph, site_id: str) -> tuple[str, ...]:
    """Enterprise ids of the devices assigned to one site."""

    wanted = _folded(site_id)
    return tuple(
        str(device.enterprise_id)
        for device in getattr(graph, "devices", ())
        if _folded(getattr(getattr(device, "site", None), "label", ""))
        == wanted
    )


def _site_candidates(graph, query: str) -> list[str]:
    """Site ids matching a name: exact first, then a contained match.

    Contained matching is what makes "Mumbai" find the site "mumbai-dc"
    — but if it finds two, that is ambiguity, not a ranking problem.
    """

    wanted = _folded(query)
    sites = [
        str(site) for site in getattr(graph, "sites", ()) or ()
        if str(site) not in ("unknown", "ambiguous")
    ]
    exact = [site for site in sites if _folded(site) == wanted]
    if exact:
        return exact
    return [
        site for site in sites
        if wanted and (wanted in _folded(site) or _folded(site) in wanted)
    ]


def resolve_site(graph, query: str) -> ResolvedEntity | None:
    if not str(query or "").strip():
        return None
    candidates = _site_candidates(graph, query)
    if len(candidates) == 1:
        site_id = candidates[0]
        members = site_members(graph, site_id)
        return ResolvedEntity(
            query=query, kind="site", status=RESOLVED,
            identifier=site_id, label=site_id, device_ids=members,
            detail=f"{len(members)} device(s) assigned to this site",
        )
    if len(candidates) > 1:
        return ResolvedEntity(
            query=query, kind="site", status=AMBIGUOUS,
            candidates=tuple(sorted(candidates)),
            detail=(
                f"{len(candidates)} sites match “{query}”. Atlas will not "
                "choose one — name the site exactly."
            ),
        )
    return None


def resolve_device(graph, query: str) -> ResolvedEntity | None:
    """One device by id, hostname, alias, address or serial.

    Uses the federation resolver, which reports ambiguity with its own
    operator-readable reason rather than picking a winner.
    """

    if not str(query or "").strip():
        return None
    try:
        from founderos_atlas.federation.service import (
            resolve_canonical_device,
        )
    except ImportError:  # pragma: no cover - packaging guard
        return None
    device, reason = resolve_canonical_device(graph, query)
    if device is not None:
        site = getattr(getattr(device, "site", None), "label", "") or "unknown"
        return ResolvedEntity(
            query=query, kind="device", status=RESOLVED,
            identifier=str(device.enterprise_id),
            label=str(device.hostname),
            device_ids=(str(device.enterprise_id),),
            detail=f"site: {site}",
        )
    text = str(reason or "")
    if "ambiguous" in text.casefold():
        return ResolvedEntity(
            query=query, kind="device", status=AMBIGUOUS, detail=text,
        )
    return None


def resolve_name_group(graph, query: str) -> ResolvedEntity | None:
    """Devices whose hostname begins with the queried word.

    Many estates encode the location in the hostname
    ("chennai-regional-edge") while Atlas's site inference has not
    assigned sites — on such a graph every device reads "unknown", and
    a site-named question would be unanswerable despite the evidence
    plainly being there.

    This groups by NAMING CONVENTION, which is weaker than an assigned
    site, so the entity says so in its own detail and every answer
    built on it carries that sentence. It is a stated assumption, not a
    silent one, and it only ever fires when no real site matched.
    """

    wanted = _folded(query)
    if len(wanted) < 3:
        return None
    members = []
    labels = []
    for device in getattr(graph, "devices", ()) or ():
        hostname = _folded(getattr(device, "hostname", ""))
        # Word-ish boundary: "chennai" matches "chennai-core" and
        # "chennai.example.net", never "chennaix".
        if hostname.startswith(wanted) and (
            len(hostname) == len(wanted)
            or not hostname[len(wanted)].isalnum()
        ):
            members.append(str(device.enterprise_id))
            labels.append(str(device.hostname))
    if not members:
        return None
    return ResolvedEntity(
        query=query, kind="name-group", status=RESOLVED,
        identifier=wanted, label=query,
        device_ids=tuple(members),
        detail=(
            f"{len(members)} device(s) whose hostname begins with "
            f"“{query}”. Atlas has not assigned sites in this "
            "enterprise, so this grouping is by naming convention, not "
            "by a discovered site."
        ),
    )


def resolve_endpoint(graph, query: str) -> ResolvedEntity | None:
    """A named endpoint: a discovered site, else a device, else a
    hostname-prefix group, else UNKNOWN with an honest reason."""

    if not str(query or "").strip():
        return None
    site = resolve_site(graph, query)
    if site is not None and site.status != UNKNOWN:
        return site
    device = resolve_device(graph, query)
    if device is not None:
        return device
    group = resolve_name_group(graph, query)
    if group is not None:
        return group
    return ResolvedEntity(
        query=query, kind="entity", status=UNKNOWN,
        detail=(
            f"Atlas has not discovered anything called “{query}” — no "
            "site, device, alias or address matches it."
        ),
    )


def resolve(graph, request) -> ResolvedEntities:
    """Resolve everything one request named."""

    source = resolve_endpoint(graph, request.source)
    destination = resolve_endpoint(graph, request.destination)

    sites: list[ResolvedEntity] = []
    named = {
        _folded(item.query) for item in (source, destination) if item
    }
    for name in request.sites:
        if _folded(name) in named:
            continue
        # The same ladder endpoints use: a discovered site, else a
        # hostname grouping. A bare scope name must resolve the same
        # way whether it was written as an endpoint or on its own.
        resolved = resolve_site(graph, name) or resolve_name_group(
            graph, name
        )
        if resolved is not None:
            sites.append(resolved)
            named.add(_folded(name))

    devices: list[ResolvedEntity] = []
    for name in request.devices:
        if _folded(name) in named:
            continue
        resolved = resolve_device(graph, name)
        devices.append(resolved or ResolvedEntity(
            query=name, kind="device", status=UNKNOWN,
            detail=f"No discovered device matches “{name}”.",
        ))
        named.add(_folded(name))

    return ResolvedEntities(
        source=source, destination=destination,
        devices=tuple(devices), sites=tuple(sites),
    )


def devices_in_scope(graph, entities: ResolvedEntities) -> tuple[str, ...]:
    """Every device id the resolved entities put in scope, in order."""

    ids: list[str] = []
    for entity in entities.all():
        if not entity.ok:
            continue
        for device_id in entity.device_ids:
            if device_id not in ids:
                ids.append(device_id)
    return tuple(ids)
