"""Deterministic topology and inventory change detection between snapshots.

This is operational change intelligence over ``TopologySnapshot`` content —
not configuration diff. Devices are matched across snapshots by identity
(hostname, then serial number, then management IP, then device ID) so a
renamed device is reported as a rename, not as one removal plus one arrival.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from founderos_atlas.topology import TopologySnapshot

from .models import (
    CATEGORY_DEVICE,
    CATEGORY_DISCOVERY,
    CATEGORY_HOSTNAME,
    CATEGORY_INTERFACE,
    CATEGORY_MANAGEMENT_IP,
    CATEGORY_NEIGHBOR,
    CATEGORY_OS_VERSION,
    CATEGORY_PLATFORM,
    Change,
    ChangeReport,
)


_UNKNOWN = frozenset({"", "unknown", "none"})


class ChangeDetector:
    """Compare two snapshots and classify every meaningful change."""

    def compare(
        self,
        previous: TopologySnapshot | Mapping[str, Any],
        current: TopologySnapshot | Mapping[str, Any],
    ) -> ChangeReport:
        previous_data = _as_dict(previous, "previous")
        current_data = _as_dict(current, "current")
        pairs, new_devices, removed_devices = _match_devices(
            previous_data["devices"], current_data["devices"]
        )

        changes: list[Change] = []
        for device in new_devices:
            hostname = str(device["hostname"])
            changes.append(
                Change(
                    category=CATEGORY_DEVICE,
                    severity="low",
                    description=f"{hostname} was discovered for the first time",
                    recommendation=(
                        f"Confirm {hostname} is an expected addition to the network."
                    ),
                    subject=hostname,
                )
            )
        for device in removed_devices:
            hostname = str(device["hostname"])
            changes.append(
                Change(
                    category=CATEGORY_DEVICE,
                    severity="high",
                    description=f"{hostname} is no longer discovered",
                    recommendation=(
                        f"Verify reachability, power, and SSH access for {hostname} "
                        f"({device['management_ip']})."
                    ),
                    subject=hostname,
                )
            )
        for before, after in pairs:
            changes.extend(_device_attribute_changes(before, after))

        changes.extend(
            _neighbor_changes(previous_data, current_data, pairs, new_devices, removed_devices)
        )
        changes.extend(_discovery_failures(current_data))

        return ChangeReport(
            previous_snapshot_id=str(previous_data.get("snapshot_id", "unknown")),
            current_snapshot_id=str(current_data.get("snapshot_id", "unknown")),
            changes=tuple(changes),
            metadata={"deterministic": True, "comparison": "topology-and-inventory"},
        )


def _as_dict(value: TopologySnapshot | Mapping[str, Any], name: str) -> dict[str, Any]:
    if isinstance(value, TopologySnapshot):
        return value.to_dict()
    if isinstance(value, Mapping):
        data = dict(value)
        if not isinstance(data.get("devices"), list) or not isinstance(data.get("edges"), list):
            raise ValueError(
                f"{name} snapshot must contain 'devices' and 'edges' lists; "
                "is this a topology_snapshot.json file?"
            )
        return data
    raise TypeError(f"{name} snapshot must be a TopologySnapshot or a mapping")


def _match_devices(
    previous: list[Mapping[str, Any]], current: list[Mapping[str, Any]]
) -> tuple[
    list[tuple[Mapping[str, Any], Mapping[str, Any]]],
    list[Mapping[str, Any]],
    list[Mapping[str, Any]],
]:
    """Pair devices across snapshots by hostname, serial, management IP, device ID."""

    remaining = list(current)
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    removed: list[Mapping[str, Any]] = []

    def take(match_key) -> Mapping[str, Any] | None:
        for index, candidate in enumerate(remaining):
            if match_key(candidate):
                return remaining.pop(index)
        return None

    for device in previous:
        hostname = str(device["hostname"]).casefold()
        serial = _known(device.get("serial_number"))
        management_ip = _known(device.get("management_ip"))
        device_id = str(device["device_id"]).casefold()
        matched = take(lambda item: str(item["hostname"]).casefold() == hostname)
        if matched is None and serial:
            matched = take(lambda item: _known(item.get("serial_number")) == serial)
        if matched is None and management_ip:
            matched = take(
                lambda item: _known(item.get("management_ip")) == management_ip
            )
        if matched is None:
            matched = take(lambda item: str(item["device_id"]).casefold() == device_id)
        if matched is None:
            removed.append(device)
        else:
            pairs.append((device, matched))
    return pairs, remaining, removed


def _device_attribute_changes(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[Change]:
    hostname = str(after["hostname"])
    changes: list[Change] = []
    if str(before["hostname"]).casefold() != str(after["hostname"]).casefold():
        changes.append(
            Change(
                category=CATEGORY_HOSTNAME,
                severity="medium",
                description=f"{before['hostname']} was renamed to {after['hostname']}",
                recommendation=(
                    f"Confirm the rename of {before['hostname']} was intentional and "
                    "update documentation."
                ),
                subject=hostname,
                field="hostname",
                previous_value=str(before["hostname"]),
                current_value=str(after["hostname"]),
            )
        )
    comparisons = (
        (
            "management_ip", CATEGORY_MANAGEMENT_IP, "medium",
            f"Verify the readdressing of {hostname} was planned and update "
            "management tooling.",
        ),
        (
            "platform", CATEGORY_PLATFORM, "high",
            f"Verify whether {hostname} hardware was replaced; review inventory "
            "and support contracts.",
        ),
        (
            "os_version", CATEGORY_OS_VERSION, "medium",
            f"Confirm the operating system change on {hostname} matches a planned "
            "upgrade window.",
        ),
    )
    for field_name, category, severity, recommendation in comparisons:
        previous_value = _known(before.get(field_name))
        current_value = _known(after.get(field_name))
        if previous_value and current_value and previous_value != current_value:
            changes.append(
                Change(
                    category=category,
                    severity=severity,
                    description=(
                        f"{hostname} {field_name.replace('_', ' ')} changed from "
                        f"{before[field_name]} to {after[field_name]}"
                    ),
                    recommendation=recommendation,
                    subject=hostname,
                    field=field_name,
                    previous_value=str(before[field_name]),
                    current_value=str(after[field_name]),
                )
            )
    before_interfaces = len(before.get("interfaces") or ())
    after_interfaces = len(after.get("interfaces") or ())
    if before_interfaces != after_interfaces:
        changes.append(
            Change(
                category=CATEGORY_INTERFACE,
                severity="low",
                description=(
                    f"{hostname} interface count changed from "
                    f"{before_interfaces} to {after_interfaces}"
                ),
                recommendation=(
                    f"Review interface inventory on {hostname} for added or "
                    "removed modules."
                ),
                subject=hostname,
                field="interface_count",
                previous_value=str(before_interfaces),
                current_value=str(after_interfaces),
            )
        )
    return changes


def _neighbor_changes(
    previous_data: Mapping[str, Any],
    current_data: Mapping[str, Any],
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
    new_devices: list[Mapping[str, Any]],
    removed_devices: list[Mapping[str, Any]],
) -> list[Change]:
    # Renamed devices must not surface as neighbor churn: previous hostnames
    # are translated to their current names before link sets are compared.
    rename_map = {
        str(before["hostname"]).casefold(): str(after["hostname"])
        for before, after in pairs
    }
    previous_links = _logical_links(previous_data, rename_map)
    current_links = _logical_links(current_data, {})
    new_hostnames = {str(device["hostname"]).casefold() for device in new_devices}
    removed_hostnames = {str(device["hostname"]).casefold() for device in removed_devices}

    changes: list[Change] = []
    for key, (host_a, host_b) in sorted(previous_links.items()):
        if key in current_links:
            continue
        if {host_a.casefold(), host_b.casefold()} & removed_hostnames:
            continue  # already reported as a removed device
        changes.append(
            Change(
                category=CATEGORY_NEIGHBOR,
                severity="medium",
                description=f"{host_a} lost neighbor {host_b}",
                recommendation=(
                    f"Verify physical connectivity or CDP between {host_a} "
                    f"and {host_b}."
                ),
                subject=host_a,
                field="neighbor",
                previous_value=host_b,
            )
        )
    for key, (host_a, host_b) in sorted(current_links.items()):
        if key in previous_links:
            continue
        if {host_a.casefold(), host_b.casefold()} & new_hostnames:
            continue  # already reported as a new device
        changes.append(
            Change(
                category=CATEGORY_NEIGHBOR,
                severity="low",
                description=f"{host_a} gained neighbor {host_b}",
                recommendation=(
                    f"Confirm the new adjacency between {host_a} and {host_b} "
                    "is expected."
                ),
                subject=host_a,
                field="neighbor",
                current_value=host_b,
            )
        )
    return changes


def _logical_links(
    snapshot: Mapping[str, Any], rename_map: Mapping[str, str]
) -> dict[tuple, tuple[str, str]]:
    """Undirected link set keyed by endpoint pairs; values keep display names."""

    hostname_by_id = {
        str(device["device_id"]): str(device["hostname"])
        for device in snapshot["devices"]
    }
    links: dict[tuple, tuple[str, str]] = {}
    for edge in snapshot["edges"]:
        local = hostname_by_id.get(
            str(edge["local_device_id"]), str(edge["local_device_id"])
        )
        remote = str(edge["remote_hostname"])
        local = rename_map.get(local.casefold(), local)
        remote = rename_map.get(remote.casefold(), remote)
        endpoints = sorted((local, remote), key=str.casefold)
        key = (endpoints[0].casefold(), endpoints[1].casefold())
        links.setdefault(key, (endpoints[0], endpoints[1]))
    return links


def _discovery_failures(current_data: Mapping[str, Any]) -> list[Change]:
    failed_hosts = (current_data.get("metadata") or {}).get("failed_hosts") or ()
    changes = []
    for host in sorted(str(value) for value in failed_hosts):
        changes.append(
            Change(
                category=CATEGORY_DISCOVERY,
                severity="medium",
                description=f"Discovery failed for {host}",
                recommendation=(
                    f"Verify reachability, SSH availability, and credentials "
                    f"for {host}."
                ),
                subject=host,
                field="discovery",
            )
        )
    return changes


def _known(value: Any) -> str:
    text = str(value).strip().casefold() if value is not None else ""
    return "" if text in _UNKNOWN else text
