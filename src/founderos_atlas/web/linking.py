"""Shared routing, deep-linking, and contextual-action infrastructure.

Every important Atlas object is directly addressable through a stable,
shareable, scope-safe URL, and every entity offers the same contextual
actions in the same order. Pages never hand-build entity URLs or invent
their own action rows: they call ``entity_url`` / build ``EntityAction``
rows and render them through templates/_entity_actions.html. A future
entity kind added HERE automatically behaves like every existing one.

Scope safety
------------
The active scope travels IN the URL (``?scope=<id>``), never only in the
browser session: a copied link reopens the same entity in the same
scope in a fresh browser. ``scoped_url`` appends the scope plus any
state worth preserving (filters, tabs, topology view). The Enterprise
scope is the one exception — it is the default, so ``scope=all`` is
carried explicitly only when the caller asks, keeping canonical URLs
stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode


GLOBAL_SCOPE = "all"


def scoped_url(path: str, scope_id: str | None = None, **params: Any) -> str:
    """``path`` with the scope and any extra state encoded as query params.

    ``None``/empty params are dropped; existing behavior of a bare path is
    preserved when there is nothing to carry. The scope is included even
    when it equals the Enterprise default if the caller passes it — an
    explicitly scoped link must survive being pasted into a browser whose
    session remembers a different scope.
    """

    query: dict[str, str] = {}
    if scope_id:
        query["scope"] = str(scope_id)
    for key, value in params.items():
        if value is None or value == "":
            continue
        query[key] = str(value)
    if not query:
        return path
    return f"{path}?{urlencode(query)}"


# -- Stable entity URLs -------------------------------------------------------
#
# One naming scheme. ``entity_url`` is the only place that knows where an
# entity kind lives, so a future route change is one edit, and tests can
# assert every kind resolves.

def entity_url(kind: str, *, scope_id: str | None = None, **ids: Any) -> str:
    """The stable, shareable URL for one entity.

    Supported kinds and their identifying arguments:

    - ``device``: ``device_id`` (canonical/enterprise id)
    - ``interface``: ``device_id`` + ``interface`` (anchors the device page)
    - ``site``: ``site_id`` (opens the site in the topology viewer page)
    - ``policy``: ``policy_id`` (anchors the policy page)
    - ``policy_failure``: ``policy_id`` + ``hostname``
    - ``discovery_run``: ``record_id``
    - ``change``: none (the change report of the scope)
    - ``incident``: none (the incident report of the scope)
    - ``evidence_record``: ``device_id`` + ``sha``
    - ``evidence_device``: ``device_id``
    - ``configuration``: ``device_id`` (+ optional ``version``)
    - ``prediction``: none (the latest prediction of the scope)
    - ``plan``: ``plan_id``
    - ``investigation``: none (the paths view of the scope)
    - ``topology_focus``: ``focus`` (+ optional ``view``)
    """

    def _id(name: str) -> str:
        value = str(ids.get(name) or "").strip()
        if not value:
            raise ValueError(f"entity_url({kind!r}) requires {name!r}")
        return value

    if kind == "device":
        return scoped_url(f"/devices/{quote(_id('device_id'), safe='')}", scope_id)
    if kind == "interface":
        base = scoped_url(
            f"/devices/{quote(_id('device_id'), safe='')}", scope_id
        )
        return f"{base}#interfaces"
    if kind == "site":
        return scoped_url("/topology", scope_id, site=_id("site_id"))
    if kind == "policy":
        return scoped_url("/policy", scope_id) + f"#policy-{quote(_id('policy_id'), safe='')}"
    if kind == "policy_failure":
        return (
            scoped_url("/policy", scope_id)
            + f"#result-{quote(_id('policy_id'), safe='')}-{quote(_id('hostname'), safe='')}"
        )
    if kind == "discovery_run":
        return scoped_url("/history", scope_id, run=_id("record_id"))
    if kind == "change":
        return scoped_url("/changes", scope_id)
    if kind == "incident":
        return scoped_url("/incidents", scope_id)
    if kind == "evidence_device":
        return scoped_url(
            f"/evidence/device/{quote(_id('device_id'), safe='')}", scope_id
        )
    if kind == "evidence_record":
        return scoped_url(
            f"/evidence/device/{quote(_id('device_id'), safe='')}"
            f"/record/{quote(_id('sha'), safe='')}",
            scope_id,
        )
    if kind == "configuration":
        version = str(ids.get("version") or "").strip()
        return scoped_url(
            f"/configuration/{quote(_id('device_id'), safe='')}",
            scope_id,
            version=version or None,
        )
    if kind == "prediction":
        return scoped_url("/predict", scope_id)
    if kind == "plan":
        return scoped_url(f"/compass/{quote(_id('plan_id'), safe='')}", scope_id)
    if kind == "investigation":
        return scoped_url("/paths", scope_id)
    if kind == "topology_focus":
        return scoped_url(
            "/topology", scope_id,
            focus=_id("focus"), view=str(ids.get("view") or "") or None,
        )
    raise ValueError(f"unknown entity kind {kind!r}")


# -- Contextual actions -------------------------------------------------------

# The canonical order. Every entity renders its available subset of these,
# in this order, through templates/_entity_actions.html — never an ad-hoc
# row of buttons in one page's own order.
ACTION_ORDER = (
    "details",
    "topology",
    "evidence",
    "configuration",
    "policy",
    "investigate",
    "predict",
    "ssh",
    "ssh-copy",
    "compass",
    "copy-link",
)

_ACTION_LABELS = {
    "details": "Details",
    "topology": "Focus in topology",
    "evidence": "Evidence",
    "configuration": "Configuration",
    "policy": "Policy",
    "investigate": "Investigate",
    "predict": "Predict",
    "ssh": "Open SSH console",
    "ssh-copy": "Copy SSH command",
    "compass": "Add to Compass",
    "copy-link": "Copy link",
}


@dataclass(frozen=True)
class EntityAction:
    """One contextual action: a live link, or a stated reason it is not.

    ``available=False`` renders greyed with ``reason`` on the control —
    "Atlas checked, and here is why not" — never a dead button and never
    a silently missing row.
    """

    key: str
    href: str | None = None
    available: bool = True
    reason: str | None = None
    label: str | None = None
    external: bool = False
    # For "ssh-copy": the exact command the button copies (never a secret).
    command: str | None = None

    def __post_init__(self) -> None:
        if self.key not in _ACTION_LABELS:
            raise ValueError(f"unknown action key {self.key!r}")
        if self.available and not self.href and self.key not in ("copy-link", "ssh-copy"):
            raise ValueError(f"available action {self.key!r} requires an href")
        if not self.available and not self.reason:
            raise ValueError(
                f"unavailable action {self.key!r} must explain why"
            )

    @property
    def display_label(self) -> str:
        return self.label or _ACTION_LABELS[self.key]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.display_label,
            "href": self.href,
            "available": self.available,
            "reason": self.reason,
            "external": self.external,
            "command": self.command,
        }


def ordered_actions(actions: list[EntityAction]) -> list[EntityAction]:
    """The canonical presentation order, whatever order the caller built."""

    order = {key: index for index, key in enumerate(ACTION_ORDER)}
    return sorted(actions, key=lambda action: order.get(action.key, 99))


def device_entity_actions(
    *,
    device_id: str | None,
    hostname: str,
    scope_id: str | None = None,
    ssh_target: dict | None = None,
    memory_device_id: str | None = None,
    has_evidence: bool = True,
    has_configuration: bool = True,
    draft_plan_id: str | None = None,
    entity_label: str | None = None,
) -> list[EntityAction]:
    """The standard action set for a device, permission/availability aware.

    Two identifier spaces meet here and are kept honest: the DEVICE page
    is addressed by the stable hostname (or enterprise id), while
    EVIDENCE and CONFIGURATION pages are addressed by the canonical
    memory device id (``memory_device_id``, e.g. ``cisco-ios:gw``).
    ``ssh_target`` is console/resolve.py's target dict (or None when the
    device is not an eligible console target in this scope).
    """

    name = entity_label or hostname
    details_id = hostname or device_id
    record_id = memory_device_id or (ssh_target or {}).get("device_id")
    actions = [
        EntityAction(
            key="details",
            href=entity_url("device", device_id=details_id, scope_id=scope_id)
            if details_id else None,
            available=bool(details_id),
            reason=None if details_id else (
                f"{name} is not a canonical device in this scope"
            ),
            label=f"Details — {name}",
        ),
        EntityAction(
            key="topology",
            href=entity_url("topology_focus", focus=hostname, scope_id=scope_id),
            label=f"Focus {name} in topology",
        ),
        EntityAction(
            key="evidence",
            href=entity_url(
                "evidence_device", device_id=record_id, scope_id=scope_id
            ) if record_id and has_evidence else None,
            available=bool(record_id and has_evidence),
            reason=None if (record_id and has_evidence) else (
                f"no evidence records are stored for {name} in this scope"
            ),
            label=f"Evidence for {name}",
        ),
        EntityAction(
            key="configuration",
            href=entity_url(
                "configuration", device_id=record_id, scope_id=scope_id
            ) if record_id and has_configuration else None,
            available=bool(record_id and has_configuration),
            reason=None if (record_id and has_configuration) else (
                f"no configuration is held for {name} in this scope"
            ),
            label=f"Configuration of {name}",
        ),
        EntityAction(
            key="policy",
            href=scoped_url("/policy", scope_id, device=hostname),
            label=f"Policy verdicts for {name}",
        ),
        EntityAction(
            key="investigate",
            href=scoped_url("/paths", scope_id, device=hostname),
            label=f"Investigate a path from {name}",
        ),
        EntityAction(
            key="predict",
            href=scoped_url("/predict", scope_id, device=hostname),
            label=f"Predict a change on {name}",
        ),
    ]
    if ssh_target and ssh_target.get("eligible"):
        actions.append(EntityAction(
            key="ssh",
            href=f"/console/{quote(str(ssh_target.get('device_id') or device_id or hostname), safe='')}",
            label=f"Open SSH console to {name}",
        ))
        if ssh_target.get("ssh_command"):
            actions.append(EntityAction(
                key="ssh-copy",
                command=str(ssh_target["ssh_command"]),
                label=f"Copy SSH command for {name}",
            ))
    else:
        actions.append(EntityAction(
            key="ssh",
            available=False,
            reason=(ssh_target or {}).get("reason")
            or f"{name} has no verified SSH endpoint in this scope",
        ))
    actions.append(EntityAction(
        key="compass",
        href=scoped_url(
            f"/compass/{quote(draft_plan_id, safe='')}", scope_id,
            device=hostname,
        ) if draft_plan_id else scoped_url("/compass", scope_id, device=hostname),
        label=f"Add {name} to a Compass plan",
    ))
    actions.append(EntityAction(
        key="copy-link",
        href=entity_url("device", device_id=details_id, scope_id=scope_id)
        if details_id else None,
        available=bool(details_id),
        reason=None if details_id else (
            f"{name} has no stable device page to link to"
        ),
        label=f"Copy link to {name}",
    ))
    return ordered_actions(actions)
