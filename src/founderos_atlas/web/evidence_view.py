"""Operator-facing derivation over Enterprise Memory (PR-047B, PROOF).

The Evidence page used to report on the storage engine: unique blobs,
deduplicated observations, stored bytes. Every number true, and not one of them
a question a network engineer asks. This module derives what an operator *does*
ask -- what did Atlas collect, from which device and session, did it work, and
what depends on it -- out of the records Enterprise Memory already keeps.

Nothing here changes storage, CORTEX, or the memory API. It is a read-only
derivation, in the same spirit as ``web/confidence.py``: one presentation
decision, made once, where the tests can reach it without a browser.

**On the collection vocabulary.** The store defines four outcomes and discovery
produces three of them (``sink.py`` classifies output as collected / empty /
unavailable; nothing sets ``error``). "Timed out" and "skipped" have no stored
representation at all -- a command that never returns is not recorded, so there
is nothing to render. So this module maps the statuses that exist and does not
invent the ones that don't: a status Atlas cannot observe must not appear as a
row an operator could believe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from founderos_atlas.enterprise_memory.models import (
    COLLECTION_EMPTY,
    COLLECTION_ERROR,
    COLLECTION_OK,
    COLLECTION_UNAVAILABLE,
)


# -- how one command's outcome is spoken to an operator ----------------------

@dataclass(frozen=True)
class StatusDisplay:
    """One collection outcome, in the operator's words.

    ``tone`` drives the badge styling only. ``meaning`` is the sentence shown
    where the operator needs to know what the status actually implies -- an
    empty response in particular reads as a failure to most people, and it
    isn't one.
    """

    label: str
    tone: str          # ok | info | warn | bad
    meaning: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "tone": self.tone, "meaning": self.meaning}


_DISPLAY: Mapping[str, StatusDisplay] = {
    COLLECTION_OK: StatusDisplay(
        "Collected", "ok",
        "The command ran and returned output. Atlas stored it.",
    ),
    COLLECTION_EMPTY: StatusDisplay(
        "Empty", "info",
        "The command executed successfully but returned no output. "
        "That is an answer, not a failure -- the device has nothing to report.",
    ),
    COLLECTION_UNAVAILABLE: StatusDisplay(
        "Unsupported", "warn",
        "The device rejected the command. This platform does not support it, "
        "so Atlas has no evidence of this kind from this device.",
    ),
    COLLECTION_ERROR: StatusDisplay(
        "Failed", "bad",
        "Atlas could not collect this command.",
    ),
}

_UNKNOWN = StatusDisplay(
    "Unknown", "warn",
    "Atlas recorded this evidence with a status it cannot interpret.",
)


def status_display(status: str | None) -> StatusDisplay:
    """The operator-facing rendering of one stored collection status.

    An unrecognised status is reported as Unknown rather than guessed into the
    nearest familiar bucket -- the same rule the reasoning layer follows.
    """

    return _DISPLAY.get(str(status or ""), _UNKNOWN)


def is_collected(status: str | None) -> bool:
    """Did this command return usable output?

    Only ``collected`` counts. An empty response is a successful collection but
    it produced no evidence, so it is not "collected" for the purpose of asking
    "what does Atlas actually know?".
    """

    return status == COLLECTION_OK


def is_failure(status: str | None) -> bool:
    """Did collection fail?

    Deliberately narrow. An **empty** response is not a failure (the command
    ran; the device had nothing to say) and neither is an **unsupported** one
    (the device answered clearly, just not with data). Widening this predicate
    is how a page starts crying wolf about a healthy network -- the same defect
    PR-043 removed from Mission.
    """

    return status == COLLECTION_ERROR


def is_unsupported(status: str | None) -> bool:
    return status == COLLECTION_UNAVAILABLE


# -- the operational summary (Part 2) ----------------------------------------

@dataclass(frozen=True)
class CollectionSummary:
    """What one discovery session actually collected.

    This replaces the storage tiles. Every field answers a question an operator
    has: can I compare anything yet, did Atlas get in, is any device missing a
    configuration, did anything go wrong.
    """

    network: str = ""
    session_id: str = ""
    session_label: str = ""
    devices_reached: int = 0
    devices_authenticated: int = 0
    devices_with_evidence: int = 0
    configurations_collected: int = 0
    commands_attempted: int = 0
    commands_collected: int = 0
    empty_responses: int = 0
    failed_collections: int = 0
    unsupported_commands: int = 0
    warnings: int = 0
    errors: int = 0
    completeness_percent: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "session_id": self.session_id,
            "session_label": self.session_label,
            "devices_reached": self.devices_reached,
            "devices_authenticated": self.devices_authenticated,
            "devices_with_evidence": self.devices_with_evidence,
            "configurations_collected": self.configurations_collected,
            "commands_attempted": self.commands_attempted,
            "commands_collected": self.commands_collected,
            "empty_responses": self.empty_responses,
            "failed_collections": self.failed_collections,
            "unsupported_commands": self.unsupported_commands,
            "warnings": self.warnings,
            "errors": self.errors,
            "completeness_percent": self.completeness_percent,
        }


def completeness_percent(
    attempted: int, failed: int, unsupported: int
) -> int | None:
    """How much of what Atlas tried to collect, it got.

    An **empty** response counts as complete: Atlas asked, the device answered,
    the answer was "nothing". Counting it against completeness would mean a
    healthy lab where LLDP is simply not running could never reach 100% -- the
    page would nag forever about a network with nothing wrong with it.

    Returns ``None`` (Unknown), never 0 or 100, when nothing was attempted.
    A percentage of no attempts is not a measurement.
    """

    if attempted <= 0:
        return None
    complete = attempted - failed - unsupported
    return round(100 * max(0, complete) / attempted)


def collection_summary(
    session: Mapping[str, Any] | None,
    records: Iterable[Mapping[str, Any]],
    snapshots: Iterable[Mapping[str, Any]] = (),
) -> CollectionSummary:
    """Derive one session's operational summary from its stored records.

    ``session`` supplies what only the run itself knows (how many addresses it
    reached, how many authenticated); the records supply everything about what
    came back. Where the two could disagree, the records win -- they are the
    evidence, the session row is a report about it.
    """

    rows = list(records)
    snaps = list(snapshots)
    session = dict(session or {})

    attempted = len(rows)
    collected = sum(1 for r in rows if is_collected(r.get("collection_status")))
    empty = sum(1 for r in rows if r.get("collection_status") == COLLECTION_EMPTY)
    failed = sum(1 for r in rows if is_failure(r.get("collection_status")))
    unsupported = sum(1 for r in rows if is_unsupported(r.get("collection_status")))

    return CollectionSummary(
        network=str(session.get("network") or ""),
        session_id=str(session.get("session_id") or ""),
        session_label=str(session.get("started_at") or session.get("session_id") or ""),
        devices_reached=int(session.get("device_count") or 0),
        devices_authenticated=int(session.get("authenticated_count") or 0),
        devices_with_evidence=len({r.get("device_id") for r in rows if r.get("device_id")}),
        configurations_collected=len({
            s.get("device_id") for s in snaps if s.get("config_sha256")
        }),
        commands_attempted=attempted,
        commands_collected=collected,
        empty_responses=empty,
        failed_collections=failed,
        unsupported_commands=unsupported,
        warnings=int(session.get("warning_count") or 0),
        errors=int(session.get("error_count") or 0),
        completeness_percent=completeness_percent(attempted, failed, unsupported),
    )


# -- the drill-down rows (Part 3) --------------------------------------------

def command_row(record: Mapping[str, Any]) -> dict[str, Any]:
    """One collected command, ready to render.

    The command is the identifier an operator recognises. The content hash is
    carried because it addresses the blob, but it is never the row's name
    (Part 4) -- nobody looks for "0825788d", they look for "show version".
    """

    status = record.get("collection_status")
    display = status_display(status)
    return {
        "command": record.get("command") or "",
        "status": status,
        "status_label": display.label,
        "status_tone": display.tone,
        "status_meaning": display.meaning,
        "collected_at": record.get("collected_at") or "",
        "byte_size": int(record.get("byte_size") or 0),
        "output_size": _human_bytes(int(record.get("byte_size") or 0)),
        "parser_version": record.get("parser_version") or "",
        "transport": record.get("transport") or "",
        "source": record.get("source") or "",
        "platform": record.get("platform") or "",
        "software_version": record.get("software_version") or "",
        "detail": record.get("detail"),
        "content_sha256": record.get("content_sha256") or "",
        "has_output": bool(record.get("content_sha256")),
        "device_id": record.get("device_id") or "",
        "hostname": record.get("hostname") or "",
        "discovery_session": record.get("discovery_session") or "",
    }


def device_rows(
    records: Iterable[Mapping[str, Any]],
    snapshots: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Group evidence by canonical device, one row each.

    Grouping is by ``device_id`` -- the canonical identity Enterprise Memory
    already assigns -- so a device reached at two addresses appears once, not
    twice (the duplicate-device defect PR-043 fixed on Compass).
    """

    by_device: dict[str, dict[str, Any]] = {}
    for record in records:
        device_id = record.get("device_id") or ""
        if not device_id:
            continue
        row = by_device.setdefault(device_id, {
            "device_id": device_id,
            "hostname": record.get("hostname") or device_id,
            "platform": "",
            "software_version": "",
            "commands_attempted": 0,
            "commands_collected": 0,
            "empty_responses": 0,
            "failed_collections": 0,
            "unsupported_commands": 0,
            "configuration": None,
            "has_configuration": False,
            "last_collected_at": "",
        })
        status = record.get("collection_status")
        row["commands_attempted"] += 1
        row["commands_collected"] += 1 if is_collected(status) else 0
        row["empty_responses"] += 1 if status == COLLECTION_EMPTY else 0
        row["failed_collections"] += 1 if is_failure(status) else 0
        row["unsupported_commands"] += 1 if is_unsupported(status) else 0
        row["platform"] = row["platform"] or (record.get("platform") or "")
        row["software_version"] = (
            row["software_version"] or (record.get("software_version") or "")
        )
        collected_at = str(record.get("collected_at") or "")
        if collected_at > row["last_collected_at"]:
            row["last_collected_at"] = collected_at

    for snap in snapshots:
        device_id = snap.get("device_id") or ""
        if not device_id or not snap.get("config_sha256"):
            continue
        row = by_device.setdefault(device_id, {
            "device_id": device_id,
            "hostname": snap.get("hostname") or device_id,
            "platform": snap.get("platform") or "",
            "software_version": snap.get("software_version") or "",
            "commands_attempted": 0, "commands_collected": 0,
            "empty_responses": 0, "failed_collections": 0,
            "unsupported_commands": 0, "configuration": None,
            "has_configuration": False, "last_collected_at": "",
        })
        existing = row.get("configuration")
        if existing is None or str(snap.get("captured_at") or "") >= str(
            existing.get("captured_at") or ""
        ):
            row["configuration"] = dict(snap)
            row["has_configuration"] = True

    for row in by_device.values():
        row["completeness_percent"] = completeness_percent(
            row["commands_attempted"],
            row["failed_collections"],
            row["unsupported_commands"],
        )
        row["configuration_status"] = (
            "Collected" if row["has_configuration"] else "Not collected"
        )

    return tuple(
        sorted(by_device.values(), key=lambda r: str(r["hostname"]).casefold())
    )


# -- what depends on this evidence (Part 6) ----------------------------------

# The command whose output IS the running configuration is the one piece of
# evidence Atlas can trace all the way to a conclusion. The sink stores that
# output twice over -- once as evidence, once as a configuration snapshot --
# from the same text, so the two share a content address (verified against the
# live lab: evidence 811be4512c1e9e39 == snapshot 811be4512c1e9e39). The policy
# provider then cites that snapshot's sha in the Evidence it hands CORTEX, and
# ReasoningResult keeps the whole Evidence object in `evidence_used`. That
# unbroken chain of content addresses -- not a guess, not a name match -- is
# what lets this module say which findings rest on which bytes.
_TRACEABLE_COMMANDS = frozenset({
    "show running-config", "show running-config all", "show run",
})


@dataclass(frozen=True)
class UsedByFinding:
    """One conclusion that consumed a specific piece of evidence."""

    module: str
    title: str
    detail: str = ""
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module, "title": self.title,
            "detail": self.detail, "url": self.url,
        }


@dataclass(frozen=True)
class UsedBy:
    """What Atlas built out of one piece of evidence.

    ``tracked`` is the honest part. It is False when Atlas simply cannot answer
    the question for this kind of evidence -- not when the answer is "nothing".
    The two are different and the page must not blur them: "nothing used this"
    is a finding, "we don't record that" is an admission.
    """

    findings: tuple[UsedByFinding, ...] = ()
    tracked: bool = False
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "tracked": self.tracked,
            "message": self.message,
        }


UNTRACKED_MESSAGE = (
    "Atlas has stored this evidence, but result-level usage tracking is not "
    "available yet for this kind of evidence."
)

NOTHING_USED_MESSAGE = (
    "No current conclusion depends on this evidence."
)


def is_traceable(record: Mapping[str, Any]) -> bool:
    """Can Atlas say what consumed this evidence?

    True only for the running configuration, because that is the only evidence
    whose journey into a conclusion is recorded end to end. Everything else
    (``show version``, LLDP, routes) is parsed into the topology and the parsed
    facts keep no reference back to the record they came from -- so for those,
    honest silence.
    """

    command = str(record.get("command") or "").strip().casefold()
    return command in _TRACEABLE_COMMANDS and bool(record.get("content_sha256"))


def used_by(
    record: Mapping[str, Any],
    *,
    policy_evaluations: Iterable[Mapping[str, Any]] = (),
) -> UsedBy:
    """Which conclusions were produced using this exact evidence.

    ``policy_evaluations`` are ``PolicyEvaluation.to_dict()`` values for this
    record's device. A finding is reported only when its result cites evidence
    carrying this record's content hash -- never because the device matches, or
    the command looks related. A wrong citation would be worse than none: it
    would make the audit trail itself untrustworthy.
    """

    if not is_traceable(record):
        return UsedBy(findings=(), tracked=False, message=UNTRACKED_MESSAGE)

    sha = str(record.get("content_sha256") or "")
    device_id = str(record.get("device_id") or "")
    findings: list[UsedByFinding] = []

    for evaluation in policy_evaluations:
        if str(evaluation.get("device_id") or "") != device_id:
            continue
        result = evaluation.get("result") or {}
        cites = any(
            (item.get("payload") or {}).get("config_sha256") == sha
            for item in (result.get("evidence_used") or [])
        )
        if not cites:
            continue
        policy = evaluation.get("policy") or {}
        findings.append(UsedByFinding(
            module="Policy",
            title=str(policy.get("name") or policy.get("policy_id") or "policy"),
            detail=str(evaluation.get("status_label") or ""),
            url="/policy",
        ))

    # The snapshot and this record are the same bytes, so the configuration
    # history is not an inference -- it is this evidence, under another view.
    findings.append(UsedByFinding(
        module="Configuration",
        title="Configuration history",
        detail="This output is stored as this device's configuration snapshot.",
        url=f"/configuration/{device_id}" if device_id else None,
    ))

    return UsedBy(
        findings=tuple(findings),
        tracked=True,
        message="" if findings else NOTHING_USED_MESSAGE,
    )


# -- normalized facts (Part 5) -----------------------------------------------

def normalized_facts(
    record: Mapping[str, Any],
    *,
    snapshot: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], ...]:
    """The facts Atlas already derived from this evidence -- never new parsing.

    Part 5 is explicit that this PR adds no parsers. So this shows only what is
    already stored beside the record: the provenance the collector recorded, and
    (for a configuration) the fingerprint the snapshot engine already extracted.
    Where Atlas holds nothing, the caller says so rather than showing an empty
    table that implies the evidence was barren.
    """

    facts: list[dict[str, str]] = []

    def add(label: str, value: Any) -> None:
        text = str(value if value is not None else "").strip()
        if text:
            facts.append({"label": label, "value": text})

    add("Hostname", record.get("hostname"))
    add("Platform", record.get("platform"))
    add("Software version", record.get("software_version"))
    add("Platform driver", record.get("platform_driver"))

    # The snapshot engine's fingerprint, exactly as it is stored. These are
    # counts, not inventories -- the fingerprint is deliberately "a cheap
    # structural shape ... no parsing" (fingerprint.py:50), so it knows that a
    # device has three BGP neighbours, not who they are. The labels say
    # "neighbours" rather than "peers" for that reason: naming a count after
    # the list it is not would promise a drill-down that does not exist.
    fingerprint = (snapshot or {}).get("fingerprint") or {}
    if isinstance(fingerprint, Mapping):
        add("Configuration hostname", fingerprint.get("hostname"))
        add("BGP AS", fingerprint.get("bgp_as"))
        for label, key in (
            ("Configuration lines", "line_count"),
            ("Interfaces", "interface_count"),
            ("Loopbacks", "loopback_count"),
            ("BGP neighbours", "bgp_neighbor_count"),
            ("OSPF processes", "ospf_process_count"),
            ("OSPF networks", "ospf_network_count"),
            ("Access lists", "acl_count"),
            ("VRFs", "vrf_count"),
            ("VLANs", "vlan_count"),
            ("Static routes", "static_route_count"),
        ):
            value = fingerprint.get(key)
            # A count of zero is a fact ("this device has no ACLs"); a missing
            # key is not. Only the second is silence.
            if isinstance(value, int):
                add(label, value)

    return tuple(facts)


def _human_bytes(size: int) -> str:
    if size <= 0:
        return "—"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
