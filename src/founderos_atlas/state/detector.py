"""Deterministic operational state detection between two topology snapshots.

Operational intelligence answers a question topology and configuration
comparison cannot: what changed in the *running state* of the network — an
interface that went down, a protocol that dropped, an address that moved —
even when the saved configuration is byte-for-byte identical.

Interfaces are compared by name within devices matched across snapshots by
hostname. Interface state already lives inside every ``TopologySnapshot``
(collected from ``show ip interface brief``), so no extra collection is
required.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from founderos_atlas.topology import TopologySnapshot

from .models import (
    CHANGE_ADDED,
    CHANGE_MODIFIED,
    CHANGE_REMOVED,
    EVENT_DEGRADATION,
    EVENT_FAILURE,
    EVENT_INFORMATIONAL,
    EVENT_RECOVERY,
    FIELD_INTERFACE,
    FIELD_IP,
    FIELD_PROTOCOL,
    FIELD_STATUS,
    StateChange,
    StateChangeReport,
)


_DOWN_STATES = frozenset({"down", "administratively_down"})
_UNKNOWN = frozenset({"", "unknown", "none", "unassigned"})

_STATUS_DOWN_RECOMMENDATION = (
    "Check cable, remote device, interface errors and spanning-tree."
)
_PROTOCOL_DOWN_RECOMMENDATION = (
    "Check line protocol, keepalives, and layer-2 connectivity on the link."
)
_ADMIN_DOWN_RECOMMENDATION = (
    "Confirm the administrative shutdown was planned."
)
_RECOVERED_RECOMMENDATION = "No action required; the interface recovered."
_IP_RECOMMENDATION = "Verify the interface readdressing was planned."
_NEW_INTERFACE_RECOMMENDATION = (
    "Confirm the new interface is an expected addition."
)
_REMOVED_INTERFACE_RECOMMENDATION = (
    "Verify whether the interface removal was planned; a missing interface "
    "can indicate hardware failure or a removed module."
)


class OperationalStateDetector:
    """Compare two snapshots and classify every operational state change."""

    def compare(
        self,
        previous: TopologySnapshot | Mapping[str, Any],
        current: TopologySnapshot | Mapping[str, Any],
        *,
        previous_ref: str = "previous",
        current_ref: str = "current",
    ) -> StateChangeReport:
        previous_devices = _devices_by_hostname(_as_dict(previous, "previous"))
        current_devices = _devices_by_hostname(_as_dict(current, "current"))
        changes: list[StateChange] = []
        for key in sorted(set(previous_devices) & set(current_devices)):
            hostname = str(current_devices[key]["hostname"])
            changes.extend(
                _device_interface_changes(
                    hostname, previous_devices[key], current_devices[key]
                )
            )
        return StateChangeReport(
            previous_ref=previous_ref,
            current_ref=current_ref,
            changes=tuple(changes),
        )


def _device_interface_changes(
    hostname: str, before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[StateChange]:
    before_ifaces = _interfaces_by_name(before)
    after_ifaces = _interfaces_by_name(after)
    changes: list[StateChange] = []

    for name in sorted(set(before_ifaces) | set(after_ifaces)):
        previous = before_ifaces.get(name)
        current = after_ifaces.get(name)
        display = str((current or previous)["name"])
        if previous is None:
            changes.append(
                StateChange(
                    hostname=hostname,
                    interface=display,
                    field=FIELD_INTERFACE,
                    severity="low",
                    event=EVENT_INFORMATIONAL,
                    change_type=CHANGE_ADDED,
                    description=f"{hostname} interface {display} was newly detected",
                    recommendation=_NEW_INTERFACE_RECOMMENDATION,
                    current_value=_status_label(current),
                )
            )
            continue
        if current is None:
            changes.append(
                StateChange(
                    hostname=hostname,
                    interface=display,
                    field=FIELD_INTERFACE,
                    severity="medium",
                    event=EVENT_DEGRADATION,
                    change_type=CHANGE_REMOVED,
                    description=f"{hostname} interface {display} is no longer present",
                    recommendation=_REMOVED_INTERFACE_RECOMMENDATION,
                    previous_value=_status_label(previous),
                )
            )
            continue
        changes.extend(_interface_field_changes(hostname, display, previous, current))
    return changes


def _interface_field_changes(
    hostname: str, name: str, previous: Mapping[str, Any], current: Mapping[str, Any]
) -> list[StateChange]:
    changes: list[StateChange] = []

    old_status = _norm(previous.get("status"))
    new_status = _norm(current.get("status"))
    if old_status and new_status and old_status != new_status:
        changes.append(
            _status_change(hostname, name, FIELD_STATUS, old_status, new_status)
        )

    old_proto = _norm(previous.get("protocol_status"))
    new_proto = _norm(current.get("protocol_status"))
    if old_proto and new_proto and old_proto != new_proto:
        changes.append(
            _status_change(hostname, name, FIELD_PROTOCOL, old_proto, new_proto)
        )

    old_ip = _known(previous.get("ip_address"))
    new_ip = _known(current.get("ip_address"))
    if old_ip and new_ip and old_ip != new_ip:
        changes.append(
            StateChange(
                hostname=hostname,
                interface=name,
                field=FIELD_IP,
                severity="medium",
                event=EVENT_INFORMATIONAL,
                change_type=CHANGE_MODIFIED,
                description=(
                    f"{hostname} interface {name} IP address changed from "
                    f"{previous['ip_address']} to {current['ip_address']}"
                ),
                recommendation=_IP_RECOMMENDATION,
                previous_value=str(previous["ip_address"]),
                current_value=str(current["ip_address"]),
            )
        )
    return changes


def _status_change(
    hostname: str, name: str, field: str, old: str, new: str
) -> StateChange:
    label = "status" if field == FIELD_STATUS else "line protocol"
    if new == "down":
        severity, event = "high", EVENT_FAILURE
        recommendation = (
            _STATUS_DOWN_RECOMMENDATION
            if field == FIELD_STATUS
            else _PROTOCOL_DOWN_RECOMMENDATION
        )
    elif new == "administratively_down":
        severity, event = "medium", EVENT_DEGRADATION
        recommendation = _ADMIN_DOWN_RECOMMENDATION
    else:
        severity, event = "low", EVENT_RECOVERY
        recommendation = _RECOVERED_RECOMMENDATION
    return StateChange(
        hostname=hostname,
        interface=name,
        field=field,
        severity=severity,
        event=event,
        change_type=CHANGE_MODIFIED,
        description=(
            f"{hostname} interface {name} {label} changed from "
            f"{old.replace('_', ' ')} to {new.replace('_', ' ')}"
        ),
        recommendation=recommendation,
        previous_value=old,
        current_value=new,
    )


def _as_dict(value: TopologySnapshot | Mapping[str, Any], name: str) -> dict[str, Any]:
    if isinstance(value, TopologySnapshot):
        return value.to_dict()
    if isinstance(value, Mapping):
        data = dict(value)
        if not isinstance(data.get("devices"), list):
            raise ValueError(
                f"{name} snapshot must contain a 'devices' list; "
                "is this a topology_snapshot.json file?"
            )
        return data
    raise TypeError(f"{name} snapshot must be a TopologySnapshot or a mapping")


def _devices_by_hostname(snapshot: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(device.get("hostname", "")).casefold(): dict(device)
        for device in snapshot.get("devices") or ()
    }


def _interfaces_by_name(device: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(interface.get("name", "")).casefold(): dict(interface)
        for interface in device.get("interfaces") or ()
        if interface.get("name")
    }


def _status_label(interface: Mapping[str, Any] | None) -> str | None:
    if interface is None:
        return None
    status = _norm(interface.get("status"))
    return status or None


def _norm(value: Any) -> str:
    text = str(value).strip().casefold() if value is not None else ""
    return "" if text in _UNKNOWN else text


def _known(value: Any) -> str:
    text = str(value).strip().casefold() if value is not None else ""
    return "" if text in _UNKNOWN else text
