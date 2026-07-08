"""Read-only configuration collection over an Atlas device transport.

Collection only: no analysis, no comparison, no configuration mode, no
write commands. Every command is a plain ``show`` that passes the
transport's read-only allowlist; devices that do not support an optional
command are recorded and skipped, never failed.
"""

from __future__ import annotations

from founderos_atlas.discovery.models import DiscoveryResult
from founderos_atlas.transport import (
    AtlasTransportError,
    ConnectionLostError,
    DeviceTransport,
    PermissionDeniedError,
    UnsupportedPlatformError,
)

from .models import (
    COLLECTION_COMPLETE,
    COLLECTION_PARTIAL,
    STATUS_COLLECTED,
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_UNSUPPORTED,
    CommandOutcome,
    ConfigurationArtifact,
    ConfigurationCollectionError,
)


RUNNING_CONFIG_COMMAND = "show running-config"
OPTIONAL_COMMANDS = (
    "show startup-config",
    "show inventory",
    "show license summary",
    "show module",
)


def collect_configuration(
    transport: DeviceTransport,
    discovery_result: DiscoveryResult,
    *,
    include_optional: bool = True,
    collected_at: str | None = None,
) -> ConfigurationArtifact:
    """Collect the running configuration (and best-effort optional outputs).

    The running configuration is required: any failure to collect it raises
    ``ConfigurationCollectionError``. Optional commands degrade gracefully —
    unsupported, denied, or failed commands become warnings, never errors.
    """

    if not isinstance(transport, DeviceTransport):
        raise TypeError("transport must implement DeviceTransport")
    if not isinstance(discovery_result, DiscoveryResult):
        raise TypeError("discovery_result must be a DiscoveryResult")

    device = discovery_result.device
    outcomes: list[CommandOutcome] = []
    warnings: list[str] = []
    additional: dict[str, str] = {}

    with transport:
        try:
            running_config = _normalize(transport.execute(RUNNING_CONFIG_COMMAND))
        except AtlasTransportError as error:
            raise ConfigurationCollectionError(
                f"Could not collect the running configuration from "
                f"{device.hostname}: {error}"
            ) from error
        if not running_config.strip():
            raise ConfigurationCollectionError(
                f"Device {device.hostname} returned an empty running configuration."
            )
        outcomes.append(CommandOutcome(RUNNING_CONFIG_COMMAND, STATUS_COLLECTED))

        if include_optional:
            for command in OPTIONAL_COMMANDS:
                outcome, output = _collect_optional(transport, device.hostname, command)
                outcomes.append(outcome)
                if outcome.status == STATUS_COLLECTED and output is not None:
                    additional[command] = output
                elif outcome.detail is not None:
                    warnings.append(outcome.detail)
                if outcome.status == STATUS_FAILED:
                    # The session is gone; do not hammer remaining commands.
                    remaining = OPTIONAL_COMMANDS[OPTIONAL_COMMANDS.index(command) + 1 :]
                    for skipped in remaining:
                        detail = f"{skipped} was skipped after the connection was lost"
                        outcomes.append(
                            CommandOutcome(skipped, STATUS_FAILED, detail=detail)
                        )
                        warnings.append(detail)
                    break

    status = (
        COLLECTION_COMPLETE
        if all(outcome.status == STATUS_COLLECTED for outcome in outcomes)
        else COLLECTION_PARTIAL
    )
    return ConfigurationArtifact(
        device_id=device.device_id,
        hostname=device.hostname,
        vendor=device.vendor,
        platform=device.platform,
        os_name=device.os_name,
        os_version=device.os_version,
        management_ip=device.management_ip,
        running_config=running_config,
        additional_outputs=additional,
        commands=tuple(outcomes),
        status=status,
        warnings=tuple(warnings),
        collected_at=collected_at if collected_at else "unrecorded",
    )


def _collect_optional(
    transport: DeviceTransport, hostname: str, command: str
) -> tuple[CommandOutcome, str | None]:
    try:
        output = _normalize(transport.execute(command))
    except UnsupportedPlatformError:
        return (
            CommandOutcome(
                command,
                STATUS_UNSUPPORTED,
                detail=f"{command} is not supported on {hostname}",
            ),
            None,
        )
    except PermissionDeniedError:
        return (
            CommandOutcome(
                command,
                STATUS_DENIED,
                detail=f"{command} was denied on {hostname}; the account lacks privilege",
            ),
            None,
        )
    except (ConnectionLostError, AtlasTransportError) as error:
        return (
            CommandOutcome(
                command,
                STATUS_FAILED,
                detail=f"{command} failed on {hostname}: {error}",
            ),
            None,
        )
    if not output.strip():
        return (
            CommandOutcome(
                command,
                STATUS_EMPTY,
                detail=f"{command} returned no output on {hostname}",
            ),
            None,
        )
    return CommandOutcome(command, STATUS_COLLECTED), output


def _normalize(output: str) -> str:
    """Normalize line endings only; configuration content is never altered."""

    text = output.replace("\r\n", "\n").replace("\r", "\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text
