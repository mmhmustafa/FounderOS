"""Evidence capture during discovery (PR-045, MEMORY, Part 9).

Memory is written *during* the discovery that already happened — never by a
second SSH session and never by rediscovering. The discovery engine collects
every command's raw output into ``DriverDiscovery.raw_outputs`` and then, today,
discards it after parsing. This sink is the seam that catches it on the way
out and hands it to Enterprise Memory, reusing the one authenticated session.

The sink is deliberately dumb and defensive: it takes what discovery already
has and persists it. A failure to persist must never break a discovery, so
every store call is guarded — memory is a side effect of discovery, not a
precondition for it.
"""

from __future__ import annotations

from typing import Any, Mapping

from .models import (
    COLLECTION_EMPTY,
    COLLECTION_OK,
    COLLECTION_UNAVAILABLE,
    SOURCE_CLI,
)
from .store import EnterpriseMemoryStore


# Commands whose output IS the running configuration, across platforms.
_RUNNING_CONFIG_COMMANDS = frozenset(
    {"show running-config", "show running-config all", "show run"}
)


class EvidenceSink:
    """Persists one discovery's raw evidence and configuration snapshots."""

    def __init__(self, store: EnterpriseMemoryStore, *, discovery_session: str) -> None:
        self._store = store
        self._session = discovery_session
        self.evidence_written = 0
        self.configurations_written = 0

    def capture(
        self,
        *,
        device_id: str,
        hostname: str,
        raw_outputs: Mapping[str, str],
        platform: str = "unknown",
        software_version: str | None = None,
        platform_driver: str | None = None,
        transport: str = "ssh",
        credential_ref: str | None = None,
        discovery_policy: str | None = None,
    ) -> None:
        """Persist every command's raw output for one device.

        ``raw_outputs`` is ``{command: output}`` exactly as the driver
        collected it. The running-config among them also becomes a
        configuration snapshot (a view over the same content blob — no
        double storage). Strong provenance travels with each record.
        """

        for command, output in (raw_outputs or {}).items():
            status = _status_for(output)
            try:
                self._store.store_evidence(
                    device_id=device_id, hostname=hostname, command=command,
                    output=output, collection_status=status,
                    discovery_session=self._session, source=SOURCE_CLI,
                    transport=transport, platform=platform,
                    software_version=software_version,
                    platform_driver=platform_driver,
                )
                self.evidence_written += 1
            except Exception:  # noqa: BLE001 - memory must never break discovery
                continue
            if _is_running_config(command) and (output or "").strip():
                try:
                    snapshot = self._store.store_configuration(
                        device_id=device_id, hostname=hostname,
                        discovery_session=self._session,
                        running_config=output, platform=platform,
                        software_version=software_version,
                        platform_driver=platform_driver,
                        credential_ref=credential_ref,
                        discovery_policy=discovery_policy,
                    )
                    if snapshot is not None:
                        self.configurations_written += 1
                except Exception:  # noqa: BLE001
                    continue


def _is_running_config(command: str) -> bool:
    return str(command or "").strip().casefold() in _RUNNING_CONFIG_COMMANDS


def _status_for(output: str | None) -> str:
    text = output or ""
    if not text.strip():
        return COLLECTION_EMPTY
    folded = text.strip().casefold()
    if folded.startswith("% unknown command") or "invalid input" in folded:
        return COLLECTION_UNAVAILABLE
    return COLLECTION_OK
