"""Pure deterministic exports for Atlas TopologySnapshot values."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .snapshot import TopologySnapshot


class TopologySnapshotExporter:
    def __init__(self, snapshot: TopologySnapshot) -> None:
        if not isinstance(snapshot, TopologySnapshot):
            raise TypeError("snapshot must be a TopologySnapshot")
        self._snapshot = snapshot

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._snapshot.to_dict())

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False,
            allow_nan=False,
        )

    def to_markdown(self) -> str:
        snapshot = self._snapshot
        lines = [
            "# Atlas Topology Snapshot",
            "",
            f"- Snapshot ID: `{snapshot.snapshot_id}`",
            f"- Created at: {snapshot.created_at or 'not recorded'}",
            f"- Devices: {snapshot.device_count}",
            f"- Edges: {snapshot.edge_count}",
            f"- Warnings: {len(snapshot.warnings)}",
            "",
            "## Devices",
            "",
        ]
        if not snapshot.devices:
            lines.append("No devices discovered.")
        for device in snapshot.devices:
            lines.extend(
                (
                    f"### {_markdown(device['hostname'])}",
                    "",
                    f"- Device ID: `{_markdown(device['device_id'])}`",
                    f"- Management IP: {_markdown(device['management_ip'])}",
                    f"- Vendor: {_markdown(device['vendor'])}",
                    f"- Platform: {_markdown(device['platform'])}",
                    f"- Operating system: {_markdown(device['os_name'])} {_markdown(device['os_version'])}",
                    f"- Interfaces: {len(device['interfaces'])}",
                    "",
                )
            )
        lines.extend(("## Edges", ""))
        if not snapshot.edges:
            lines.append("No neighbor edges observed.")
        else:
            lines.extend(("| Local device | Local interface | Remote device | Remote interface | Protocol |", "|---|---|---|---|---|"))
            for edge in snapshot.edges:
                lines.append(
                    "| " + " | ".join(
                        _markdown(value or "-")
                        for value in (
                            edge["local_device_id"], edge["local_interface"],
                            edge["remote_hostname"], edge["remote_interface"], edge["protocol"],
                        )
                    ) + " |"
                )
        lines.extend(("", "## Warnings", ""))
        if not snapshot.warnings:
            lines.append("No reconciliation warnings.")
        else:
            for warning in snapshot.warnings:
                lines.append(
                    f"- **{_markdown(warning['code'])}** on `{_markdown(warning['device_id'])}` "
                    f"field `{_markdown(warning['field'])}`: "
                    f"`{_markdown(warning['existing_value'])}` vs `{_markdown(warning['incoming_value'])}`"
                )
        return "\n".join(lines) + "\n"


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("`", "\\`")
