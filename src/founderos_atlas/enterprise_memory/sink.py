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


# The command spellings the sink recognises as a running configuration
# when a capture arrives WITHOUT driver knowledge (legacy callers). With
# driver knowledge, the driver's own declaration is the only authority —
# PR-181 retired this set from that path.
_LEGACY_RUNNING_CONFIG_COMMANDS = frozenset(
    {
        "show running-config",
        "show running-config all",
        "show run",
        "show configuration | display set",
        "show configuration",
    }
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
        configuration_commands: tuple[str, ...] | None = None,
        configuration_check=None,
    ) -> None:
        """Persist every command's raw output for one device.

        ``raw_outputs`` is ``{command: output}`` exactly as the driver
        collected it. A configuration SNAPSHOT is only ever written for a
        command the driver declares as its configuration command
        (``configuration_commands``; the legacy spelling set is the
        fallback for driverless callers) AND whose output the positive
        check confirms is a configuration (PR-181). The raw evidence row
        is written either way — with an honest status — so the forensic
        record of a refused or unconfirmable attempt always survives.
        """

        if configuration_commands is None:
            config_commands = _LEGACY_RUNNING_CONFIG_COMMANDS
        else:
            config_commands = frozenset(
                str(command).strip().casefold()
                for command in configuration_commands
            )
        if configuration_check is None:
            from founderos_atlas.config.classify import (
                shared_structural_is_configuration,
            )

            configuration_check = shared_structural_is_configuration
            verified_by = "pr181:structural-default"
        else:
            verified_by = (
                f"pr181:driver-recogniser"
                + (f" driver={platform_driver}" if platform_driver else "")
            )

        for command, output in (raw_outputs or {}).items():
            is_config_command = (
                str(command or "").strip().casefold() in config_commands
            )
            confirmed = False
            if is_config_command and (output or "").strip():
                try:
                    confirmed = bool(configuration_check(output))
                except Exception:  # noqa: BLE001 - a check must fail closed
                    confirmed = False
            status = _status_for(output)
            if is_config_command and (output or "").strip() and not confirmed:
                # The device answered the configuration command with
                # something that is NOT a configuration. The evidence row
                # says so — never "collected".
                status = COLLECTION_UNAVAILABLE
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
            if is_config_command and confirmed:
                try:
                    snapshot = self._store.store_configuration(
                        device_id=device_id, hostname=hostname,
                        discovery_session=self._session,
                        running_config=output, platform=platform,
                        software_version=software_version,
                        platform_driver=platform_driver,
                        credential_ref=credential_ref,
                        discovery_policy=discovery_policy,
                        collection_status=COLLECTION_OK,
                        command=command,
                        verified_by=verified_by,
                    )
                    if snapshot is not None:
                        self.configurations_written += 1
                except Exception:  # noqa: BLE001
                    continue


def _status_for(output: str | None) -> str:
    text = output or ""
    if not text.strip():
        return COLLECTION_EMPTY
    folded = text.strip().casefold()
    if folded.startswith("% unknown command") or "invalid input" in folded:
        return COLLECTION_UNAVAILABLE
    return COLLECTION_OK
