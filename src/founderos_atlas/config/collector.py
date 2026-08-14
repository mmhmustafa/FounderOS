"""Read-only configuration collection over an Atlas device transport.

Collection only: no analysis, no comparison, no configuration mode, no
write commands. Every command is a plain read that passes the transport's
read-only allowlist.

PR-181 rebuilt this module around one invariant:

    A reply becomes a configuration ONLY when the resolved platform
    driver positively confirms it is one. The absence of a recognised
    error is not proof.

The command sent is the one the device's own driver declares — resolved
from the platform identity discovery already stamped into the device's
metadata — never a hardcoded dialect. A device whose driver declares no
configuration command, or whose reply cannot be confirmed, ends in an
honest non-collected artifact instead of a fabricated configuration.
"""

from __future__ import annotations

from typing import Any

from founderos_atlas.discovery.models import DiscoveryResult
from founderos_atlas.transport import (
    AtlasTransportError,
    ConnectionLostError,
    DeviceTransport,
    PermissionDeniedError,
    UnsupportedPlatformError,
)

from .classify import classify_configuration_reply, probe_regions
from .models import (
    COLLECTION_COMPLETE,
    COLLECTION_PARTIAL,
    STATUS_COLLECTED,
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_UNRECOGNISED,
    STATUS_UNSUPPORTED,
    CommandOutcome,
    ConfigurationArtifact,
)


# The legacy default, sent only when no driver can be resolved at all
# (adapter-path discovery, stale metadata). Missing metadata is never
# proof a device lacks configuration support — the classifier judges the
# reply either way.
RUNNING_CONFIG_COMMAND = "show running-config"

# Cisco-dialect enrichment commands. Sent only to devices that speak that
# dialect; on every other platform all four are guaranteed noise.
OPTIONAL_COMMANDS = (
    "show startup-config",
    "show inventory",
    "show license summary",
    "show module",
)

_CISCO_CLI_PLATFORMS = frozenset({"cisco-ios", "cisco-ios-xe", "cisco-nxos"})

# PR-181 deliberate risk containment: these platforms declare no session
# command that can disable output pagination, and no permitted form exists
# under the read-only transport ("config system console" would enter a
# configuration scope). A pager-truncated reply can look exactly like a
# complete configuration, so collection is not attempted until the session
# plumbing exists. This is a limitation of Atlas, stated as one — not a
# fact about the platform.
_PAGER_CONTAINED_PLATFORMS = frozenset({"fortinet-fortios", "aruba-cx"})


def resolve_configuration_driver(
    discovery_result: DiscoveryResult, registry: Any = None
) -> Any | None:
    """The platform driver this device's own discovery identified, or None.

    Resolution uses only data the result already carries —
    ``device.metadata["platform_driver"]["platform_id"]`` — and the
    registry's existing ``driver_for`` seam. No new plumbing.
    """

    metadata = discovery_result.device.metadata or {}
    driver_meta = metadata.get("platform_driver") or {}
    platform_id = None
    if isinstance(driver_meta, dict) or hasattr(driver_meta, "get"):
        platform_id = driver_meta.get("platform_id")
    if not platform_id:
        return None
    if registry is None:
        from founderos_atlas.platforms import default_registry

        registry = default_registry()
    return registry.driver_for(str(platform_id))


def precollection_outcome(
    driver: Any | None,
    device: Any,
    *,
    collected_at: str | None = None,
) -> ConfigurationArtifact | None:
    """The honest outcome decidable BEFORE any transport is opened.

    Returns an artifact for the two cases where sending nothing is the
    correct behaviour, so the caller never authenticates to a device it
    has already decided to collect nothing from. Returns None when
    collection should proceed.
    """

    if driver is None:
        return None
    platform_id = getattr(driver, "platform_id", "")
    display_name = getattr(driver, "display_name", platform_id or "this platform")
    if platform_id in _PAGER_CONTAINED_PLATFORMS:
        return _non_collected_artifact(
            device,
            status=STATUS_UNSUPPORTED,
            detail=(
                f"configuration collection for {display_name} is not yet "
                "available: its output pagination cannot be disabled over "
                "Atlas's read-only transport, and a pager-truncated reply "
                "could be mistaken for a complete configuration; no command "
                "was sent"
            ),
            collected_at=collected_at,
        )
    commands = tuple(getattr(driver, "configuration_commands", tuple)() or ())
    if not commands:
        # A ProductionDriver that authors a command plan and omits
        # CONFIGURATION has declared its position; legacy drivers all
        # declare theirs since PR-181 Step 4.
        return _non_collected_artifact(
            device,
            status=STATUS_UNSUPPORTED,
            detail=(
                f"{display_name} declares no configuration collection "
                "command; nothing was sent"
            ),
            collected_at=collected_at,
        )
    return None


def collect_configuration(
    transport: DeviceTransport,
    discovery_result: DiscoveryResult,
    *,
    include_optional: bool = True,
    collected_at: str | None = None,
    driver: Any | None = None,
    registry: Any = None,
) -> ConfigurationArtifact:
    """Collect the running configuration, or say honestly why not.

    Never raises for device behaviour: refusals, denials, empty and
    unconfirmable replies become honest non-collected artifacts. Transport
    faults during collection become a ``failed`` artifact; a connect-time
    fault propagates to the caller exactly as before.
    """

    if not isinstance(transport, DeviceTransport):
        raise TypeError("transport must implement DeviceTransport")
    if not isinstance(discovery_result, DiscoveryResult):
        raise TypeError("discovery_result must be a DiscoveryResult")

    device = discovery_result.device
    if driver is None:
        driver = resolve_configuration_driver(discovery_result, registry)

    early = precollection_outcome(driver, device, collected_at=collected_at)
    if early is not None:
        return early

    commands = tuple(getattr(driver, "configuration_commands", tuple)() or ()) \
        if driver is not None else ()
    if not commands:
        commands = (RUNNING_CONFIG_COMMAND,)

    outcomes: list[CommandOutcome] = []
    warnings: list[str] = []
    additional: dict[str, str] = {}

    with transport:
        setup_failure = _run_session_setup(transport, driver, warnings)
        if setup_failure is not None:
            return _non_collected_artifact(
                device, status=STATUS_FAILED, detail=setup_failure,
                collected_at=collected_at, warnings=tuple(warnings),
            )

        running_config = ""
        command_used: str | None = None
        last_reply = ""
        saw_unrecognised = False
        saw_unsupported = False
        for command in commands:
            try:
                reply = _normalize(transport.execute(command))
            except PermissionDeniedError as error:
                detail = (
                    f"{command} was denied on {device.hostname}; "
                    "the account lacks privilege"
                )
                outcomes.append(
                    CommandOutcome(command, STATUS_DENIED, detail=detail)
                )
                return _non_collected_artifact(
                    device, status=STATUS_DENIED, detail=detail,
                    collected_at=collected_at, commands=tuple(outcomes),
                    command_used=command, warnings=tuple(warnings),
                )
            except UnsupportedPlatformError as error:
                # The transport recognised a refusal in the reply text.
                # The session is still alive — the next declared form
                # deserves its turn.
                outcomes.append(
                    CommandOutcome(
                        command, STATUS_UNSUPPORTED, detail=str(error)[:160]
                    )
                )
                saw_unsupported = True
                continue
            except (ConnectionLostError, AtlasTransportError) as error:
                detail = f"{command} failed on {device.hostname}: {error}"
                outcomes.append(
                    CommandOutcome(command, STATUS_FAILED, detail=detail[:160])
                )
                return _non_collected_artifact(
                    device, status=STATUS_FAILED, detail=detail,
                    collected_at=collected_at, commands=tuple(outcomes),
                    command_used=command, warnings=tuple(warnings),
                )

            status, detail = classify_configuration_reply(driver, reply)
            if status == STATUS_COLLECTED:
                outcomes.append(CommandOutcome(command, STATUS_COLLECTED))
                running_config = reply
                command_used = command
                break
            outcomes.append(CommandOutcome(command, status, detail=detail))
            if status == STATUS_DENIED:
                return _non_collected_artifact(
                    device, status=STATUS_DENIED, detail=detail,
                    collected_at=collected_at, commands=tuple(outcomes),
                    command_used=command, raw_reply=reply,
                    warnings=tuple(warnings),
                )
            if status == STATUS_UNRECOGNISED:
                saw_unrecognised = True
            elif status == STATUS_UNSUPPORTED:
                saw_unsupported = True
            if reply.strip():
                last_reply = reply

        if command_used is None:
            # The ladder is exhausted without a confirmed configuration.
            # An unconfirmed reply is the more urgent fact than a clean
            # refusal — it travels with the artifact as forensic material.
            if saw_unrecognised:
                status = STATUS_UNRECOGNISED
                detail = (
                    f"no reply from {device.hostname} could be confirmed "
                    "as a configuration"
                )
            elif saw_unsupported:
                status = STATUS_UNSUPPORTED
                detail = (
                    f"{device.hostname} rejected every configuration "
                    "command form"
                )
            else:
                status = STATUS_EMPTY
                detail = (
                    f"{device.hostname} returned no output for any "
                    "configuration command"
                )
            return _non_collected_artifact(
                device, status=status, detail=detail,
                collected_at=collected_at, commands=tuple(outcomes),
                command_used=commands[-1], raw_reply=last_reply,
                warnings=tuple(warnings),
            )

        if include_optional and _wants_cisco_optionals(driver, device):
            for command in OPTIONAL_COMMANDS:
                outcome, output = _collect_optional(
                    transport, driver, device.hostname, command
                )
                outcomes.append(outcome)
                if outcome.status == STATUS_COLLECTED and output is not None:
                    additional[command] = output
                elif outcome.detail is not None:
                    warnings.append(outcome.detail)
                if outcome.status == STATUS_FAILED:
                    # The session is gone; do not hammer remaining commands.
                    remaining = OPTIONAL_COMMANDS[
                        OPTIONAL_COMMANDS.index(command) + 1 :
                    ]
                    for skipped in remaining:
                        detail = (
                            f"{skipped} was skipped after the connection "
                            "was lost"
                        )
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
        command_used=command_used,
    )


def _wants_cisco_optionals(driver: Any | None, device: Any) -> bool:
    if driver is not None:
        return getattr(driver, "platform_id", "") in _CISCO_CLI_PLATFORMS
    return str(getattr(device, "vendor", "")).casefold() == "cisco"


def _run_session_setup(
    transport: DeviceTransport, driver: Any | None, warnings: list[str]
) -> str | None:
    """Run the driver's declared session preparation, tolerating refusal.

    Returns an error description only when the session itself broke —
    a platform that rejects a setup command is recorded and tolerated,
    exactly as discovery tolerates it.
    """

    for command in tuple(getattr(driver, "session_setup", ()) or ()):
        try:
            transport.execute(command)
        except ConnectionLostError as error:
            return f"the session was lost during setup ({command}): {error}"
        except AtlasTransportError as error:
            warnings.append(f"session setup {command!r} failed: {error}"[:160])
        except Exception as error:  # noqa: BLE001 - tolerated, recorded
            warnings.append(f"session setup {command!r} failed: {error}"[:160])
    return None


def _non_collected_artifact(
    device: Any,
    *,
    status: str,
    detail: str,
    collected_at: str | None,
    commands: tuple[CommandOutcome, ...] = (),
    command_used: str | None = None,
    raw_reply: str = "",
    warnings: tuple[str, ...] = (),
) -> ConfigurationArtifact:
    return ConfigurationArtifact(
        device_id=device.device_id,
        hostname=device.hostname,
        vendor=device.vendor,
        platform=device.platform,
        os_name=device.os_name,
        os_version=device.os_version,
        management_ip=device.management_ip,
        running_config="",
        commands=commands,
        status=status,
        warnings=warnings,
        collected_at=collected_at if collected_at else "unrecorded",
        command_used=command_used,
        raw_reply=raw_reply,
        detail=detail,
    )


def _collect_optional(
    transport: DeviceTransport, driver: Any | None, hostname: str, command: str
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
    # PR-181: a text refusal the transport's markers do not recognise must
    # not become a stored artifact file. Probe the reply with the resolved
    # driver's own grammar (or the shared fallback) before accepting it.
    for region in probe_regions(output):
        denied_probe = getattr(driver, "denied", None) if driver else None
        if callable(denied_probe) and denied_probe(region):
            return (
                CommandOutcome(
                    command,
                    STATUS_DENIED,
                    detail=(
                        f"{command} was denied on {hostname}; the account "
                        "lacks privilege"
                    ),
                ),
                None,
            )
        rejects_probe = getattr(driver, "rejects", None) if driver else None
        if callable(rejects_probe):
            if rejects_probe(region):
                return (
                    CommandOutcome(
                        command,
                        STATUS_UNSUPPORTED,
                        detail=f"{command} is not supported on {hostname}",
                    ),
                    None,
                )
        else:
            from .classify import _fallback_rejects

            if _fallback_rejects(region):
                return (
                    CommandOutcome(
                        command,
                        STATUS_UNSUPPORTED,
                        detail=f"{command} is not supported on {hostname}",
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
