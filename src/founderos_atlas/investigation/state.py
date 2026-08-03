"""The operational-state provider and its freshness contract (PR-173).

**State is perishable in a way configuration is not.** A three-day-old
running-config is still legitimate evidence of how a device is
configured; a three-day-old ``Established`` is NOT evidence that BGP is
up now. This module is therefore two things and nothing more:

1. A **thin provider** over observations the Enterprise Graph already
   carries — typed, vendor-neutral, provenance-bearing. It collects
   nothing, polls nothing, and never touches a driver: state is as
   fresh as the last discovery, and Atlas says so.
2. The **freshness gate**: every observation set is dated, and an
   observation set older than the workspace's horizon cannot support a
   verdict. Undated observations are STALE — Atlas does not assume
   that unstamped means recent.

Dating is a read-only join. Observation dicts carry ``observed_at``
(when a parser stamps it) and ``observed_by`` (the contributing
profile's name, stamped by the federation builder); the graph's
contributions carry each profile's discovery ``observed_at``. The
provider dates each observation by the first of those that exists —
it never invents a timestamp, and it never modifies the graph.

State evidence must never be confused with configured intent:
``config_memory``'s facts (e.g. a configured HSRP priority) say nothing
about what the network is DOING, and this module never reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


# -- observation kinds (the state vocabulary) ---------------------------------
#
# One name per canonical observation shape. A subject declares which
# kind describes its state (SubjectDescriptor.state_kind); a state rule
# declares which kind it judges. The two meeting is what makes a state
# capability exist — discovered, never declared (PR-172's principle on
# a second axis).

STATE_KIND_BGP_SESSIONS = "bgp-sessions"
STATE_KIND_OSPF_ADJACENCIES = "ospf-adjacencies"
STATE_KIND_INTERFACE_STATUS = "interface-status"

STATE_KINDS = (
    STATE_KIND_BGP_SESSIONS,
    STATE_KIND_OSPF_ADJACENCIES,
    STATE_KIND_INTERFACE_STATUS,
)

# -- freshness (the state-specific step) --------------------------------------

FRESHNESS_FRESH = "fresh"      # within the horizon: a verdict may stand
FRESHNESS_AGEING = "ageing"    # 1-4x horizon: verdict allowed, age STATED
FRESHNESS_STALE = "stale"      # beyond 4x horizon, or undated: no verdict

DEFAULT_HORIZON_MINUTES = 60
_AGEING_MULTIPLIER = 4


@dataclass(frozen=True)
class StateObservations:
    """One device's observations of one kind, dated and attributed.

    ``observed_at`` is the OLDEST date across the items — the honest
    choice: a set is only as current as its stalest member. ``None``
    means at least one item could not be dated at all, and the set
    cannot support a verdict.
    """

    kind: str
    device_id: str
    items: tuple[dict[str, Any], ...]
    observed_at: str | None
    source_commands: tuple[str, ...] = ()

    @property
    def identities(self) -> tuple[str, ...]:
        """Stable identity per item (PR-173, R7): the key a future
        state history will join on. Deterministic, excludes state."""

        rows = []
        for item in self.items:
            if self.kind == STATE_KIND_BGP_SESSIONS:
                rows.append("|".join((
                    self.device_id, "bgp",
                    str(item.get("vrf") or "default"),
                    str(item.get("address_family") or "ipv4-unicast"),
                    str(item.get("peer_address") or ""),
                )))
            elif self.kind == STATE_KIND_OSPF_ADJACENCIES:
                rows.append("|".join((
                    self.device_id, "ospf",
                    str(item.get("vrf") or "default"),
                    str(item.get("address_family") or "ipv4"),
                    str(item.get("neighbor_router_id") or ""),
                    str(item.get("local_interface") or ""),
                )))
            else:
                rows.append("|".join((
                    self.device_id, "interface",
                    str(item.get("name") or ""),
                )))
        return tuple(rows)


def _interface_state(status: str, protocol_status: str) -> str:
    """One canonical word from the graph's two status fields —
    normalisation, never inference: every branch repeats what the
    device said."""

    status_l = status.casefold()
    protocol_l = protocol_status.casefold()
    if "administratively down" in status_l:
        return "admin-down"
    if "down" in status_l or "down" in protocol_l:
        return "down"
    if "up" in status_l:
        return "up"
    return status_l or "unknown"


def _contribution_dates(graph) -> dict[str, str]:
    """profile name -> that contribution's discovery observed_at."""

    dates: dict[str, str] = {}
    for contribution in getattr(graph, "contributions", ()) or ():
        name = str(getattr(contribution, "profile_name", "") or "")
        observed = getattr(contribution, "observed_at", None)
        if name and observed:
            dates[name] = str(observed)
    return dates


def _date_of(item: dict[str, Any], dates: dict[str, str]) -> str | None:
    """One observation's date: its own stamp, else its contribution's.
    Never invented."""

    own = item.get("observed_at")
    if own:
        return str(own)
    return dates.get(str(item.get("observed_by") or ""))


def _oldest(stamps: list[str | None]) -> str | None:
    """The honest date of a SET: its oldest member — or None when any
    member is undated, because an undatable part makes the whole
    undatable for verdict purposes."""

    if not stamps or any(stamp is None for stamp in stamps):
        return None
    return min(stamps)  # ISO-8601 strings order chronologically


def observations_for(graph, device_id: str, kind: str) -> StateObservations:
    """One device's dated observations of one kind, from the graph.

    Read-only: the graph is never modified, no device is contacted.
    An empty ``items`` means Atlas holds no such observations for the
    device — which the caller must treat as absence of evidence (or,
    for a subject-bearing question, as "does not run it"), never as
    health.
    """

    dates = _contribution_dates(graph)

    if kind == STATE_KIND_INTERFACE_STATUS:
        interfaces = (getattr(graph, "interfaces", {}) or {}).get(
            device_id, ()
        ) or ()
        items = []
        stamps: list[str | None] = []
        for interface in interfaces:
            status = str(getattr(interface, "status", "") or "")
            protocol = str(
                getattr(interface, "protocol_status", "") or ""
            )
            row = {
                "name": str(getattr(interface, "name", "") or ""),
                "status": status,
                "protocol_status": protocol,
                # The canonical judgement value a state rule reads.
                # "admin-down" is CONFIGURED intent, kept distinct from
                # a failure — an interface someone shut down on purpose
                # is not unhealthy, and a rule may exclude it by name.
                "state": _interface_state(status, protocol),
                "observed_by": next(
                    iter(getattr(interface, "observed_by", ()) or ()), ""
                ),
            }
            items.append(row)
            stamps.append(_date_of(row, dates))
        return StateObservations(
            kind=kind, device_id=device_id, items=tuple(items),
            observed_at=_oldest(stamps),
            source_commands=("show interfaces",) if items else (),
        )

    from .engines import routing_evidence_for

    evidence = routing_evidence_for(graph, device_id)
    key = (
        "bgp_sessions" if kind == STATE_KIND_BGP_SESSIONS
        else "ospf_adjacencies"
    )
    items = tuple(dict(item) for item in evidence.get(key) or ())
    stamps = [_date_of(item, dates) for item in items]
    commands = tuple(sorted({
        str(item.get("source_command") or "") for item in items
        if item.get("source_command")
    }))
    return StateObservations(
        kind=kind, device_id=device_id, items=items,
        observed_at=_oldest(stamps), source_commands=commands,
    )


# -- the freshness gate -------------------------------------------------------


def state_freshness(
    observed_at: str | None, *, now: str,
    horizon_minutes: int = DEFAULT_HORIZON_MINUTES,
) -> str:
    """FRESH | AGEING | STALE, from a date — never a guess.

    Undated is STALE: Atlas does not assume that unstamped means
    recent. Unparseable dates are stale for the same reason. AGEING
    spans one to four horizons — a verdict is still allowed, but the
    age must be stated in the answer.
    """

    if not observed_at:
        return FRESHNESS_STALE
    try:
        observed = datetime.fromisoformat(str(observed_at))
        reference = datetime.fromisoformat(str(now))
    except ValueError:
        return FRESHNESS_STALE
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    age_minutes = (reference - observed).total_seconds() / 60.0
    if age_minutes < 0:
        # A future-dated observation is a clock problem, not evidence.
        return FRESHNESS_STALE
    if age_minutes <= horizon_minutes:
        return FRESHNESS_FRESH
    if age_minutes <= horizon_minutes * _AGEING_MULTIPLIER:
        return FRESHNESS_AGEING
    return FRESHNESS_STALE


def observation_age_sentence(observed_at: str | None, *, now: str) -> str:
    """The age, in operator words — always stated with a state verdict."""

    if not observed_at:
        return "the observations carry no timestamp"
    try:
        observed = datetime.fromisoformat(str(observed_at))
        reference = datetime.fromisoformat(str(now))
    except ValueError:
        return "the observations carry an unreadable timestamp"
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    minutes = max(0.0, (reference - observed).total_seconds() / 60.0)
    if minutes < 1:
        return "observed less than a minute ago"
    if minutes < 90:
        return f"observed {int(round(minutes))} minute(s) ago"
    hours = minutes / 60.0
    if hours < 36:
        return f"observed {int(round(hours))} hour(s) ago"
    return f"observed {int(round(hours / 24.0))} day(s) ago"


def horizon_minutes_from_preferences(preferences) -> int:
    """The workspace's staleness horizon, defaulted — never crashes on
    an older preferences object."""

    try:
        value = int(getattr(
            preferences, "state_horizon_minutes", DEFAULT_HORIZON_MINUTES,
        ))
    except (TypeError, ValueError):
        return DEFAULT_HORIZON_MINUTES
    return value if 5 <= value <= 10080 else DEFAULT_HORIZON_MINUTES


__all__ = [
    "DEFAULT_HORIZON_MINUTES",
    "FRESHNESS_AGEING",
    "FRESHNESS_FRESH",
    "FRESHNESS_STALE",
    "STATE_KINDS",
    "STATE_KIND_BGP_SESSIONS",
    "STATE_KIND_INTERFACE_STATUS",
    "STATE_KIND_OSPF_ADJACENCIES",
    "StateObservations",
    "horizon_minutes_from_preferences",
    "observation_age_sentence",
    "observations_for",
    "state_freshness",
]
