"""The production driver contract (PR-049, POLYGLOT, Part 2).

``ProductionDriver`` extends the proven ``PlatformDriver`` base rather than
replacing it: the probe matcher, parse-only adapter, and canonical-model flow
stay exactly as PR-043 built them. What production platforms add:

- a **command plan with ordered fallbacks** (`CommandSpec`) instead of one
  command per capability;
- **per-attempt honesty**: a device that rejects a command is UNSUPPORTED, a
  transport that breaks is FAILED, an empty answer is SUPPORTED — three
  different facts, never collapsed;
- **partial results survive**: one failed command never discards the evidence
  every other command already produced (only a required capability may end
  the device, because without identity there is no device to attach evidence
  to);
- a **session profile**: which netmiko personality drives the CLI and which
  setup commands disable pagination — chosen by the driver, not hardcoded in
  the transport;
- **collection tiers** (fast/standard/deep) where a skipped capability
  reports NOT_ATTEMPTED by name, so a tier can never silently reduce
  evidence;
- **diagnostics** (Part 16) stamped into canonical device metadata, where the
  Evidence Explorer and device pages already read.
"""

from __future__ import annotations

from dataclasses import replace

from founderos_atlas.discovery.engine import DiscoveryEngine
from founderos_atlas.discovery.exceptions import AtlasDiscoveryError

from .base import CapabilityStatus, DriverDiscovery, PlatformDriver
from .capabilities import (
    CapabilityReport,
    CommandSpec,
    DriverDiagnostics,
    EXPERIMENTAL,
    FAILED,
    NOT_ATTEMPTED,
    SUPPORTED,
    SUPPORTED_WITH_LIMITATIONS,
    TIER_STANDARD,
    UNSUPPORTED,
    tier_includes,
)


# Statuses mapped onto the legacy capability vocabulary, so every existing
# consumer (metadata stamping, sink, dashboards) keeps reading what it always
# read while the richer report travels beside it.
_LEGACY = {
    SUPPORTED: "collected",
    SUPPORTED_WITH_LIMITATIONS: "collected",
    UNSUPPORTED: "unavailable",
    NOT_ATTEMPTED: "not-collected",
    FAILED: "failed",
}


class ProductionDriver(PlatformDriver):
    """A platform driver held to the production contract."""

    # The netmiko personality that knows this platform's prompts, pagination
    # and timing. The transport takes it from the driver — never the reverse.
    netmiko_device_type: str = "cisco_ios"
    # Read-only session preparation (pagination off, width). Failure to run
    # one is tolerated and recorded; none of these may change configuration.
    session_setup: tuple[str, ...] = ()
    maturity: str = EXPERIMENTAL

    # -- contract points a platform implements --------------------------------

    def command_plan(self) -> tuple[CommandSpec, ...]:  # pragma: no cover
        raise NotImplementedError

    def rejects(self, output: str) -> bool:
        """Did the device refuse this command (as opposed to answering it)?

        The default understands the Cisco/vtysh family; platforms with their
        own refusal grammar (Junos, EOS) override it. Refusal is judged from
        the device's words only — an exception is never a refusal.
        """

        folded = (output or "").strip().casefold()
        if not folded:
            return False
        return (
            folded.startswith("% invalid input")
            or folded.startswith("% unknown command")
            or folded.startswith("% incomplete command")
            or "invalid input detected" in folded[:120]
            or "% invalid command" in folded[:120]
        )

    def denied(self, output: str) -> bool:
        """Did the device refuse for lack of privilege? Reported apart from
        unsupported: the command exists, this account may not run it."""

        folded = (output or "").strip().casefold()
        return "permission denied" in folded[:120] or (
            folded.startswith("% authorization failed")
        )

    # Legacy shim: the old interface derives from the new plan, so anything
    # still calling collection_plan() sees the primary commands.
    def collection_plan(self):
        from .base import CapabilitySpec

        return tuple(
            CapabilitySpec(spec.capability, spec.commands[0], required=spec.required)
            for spec in self.command_plan()
        )

    # -- the production flow ---------------------------------------------------

    def discover(
        self,
        transport,
        *,
        management_ip_hint: str | None = None,
        probe_output: str | None = None,
        tier: str = TIER_STANDARD,
        detection: dict | None = None,
    ) -> DriverDiscovery:
        raw: dict[str, str] = {}
        if probe_output is not None:
            raw[self.probe_command] = probe_output
        reports: list[CapabilityReport] = []
        warnings: list[str] = []

        for setup in self.session_setup:
            try:
                transport.execute(setup)
            except Exception as error:  # noqa: BLE001 - tolerated, recorded
                warnings.append(f"session setup {setup!r} failed: {error}"[:160])

        for spec in self.command_plan():
            if not tier_includes(tier, spec.tier):
                reports.append(CapabilityReport(
                    spec.capability, NOT_ATTEMPTED,
                    commands_attempted=(),
                    detail=f"excluded by the {tier} collection tier",
                ))
                continue
            reports.append(self._collect(transport, spec, raw, warnings))

        result = DiscoveryEngine(self.adapter).discover(
            raw, management_ip_hint=management_ip_hint
        )

        diagnostics = DriverDiagnostics(
            platform_id=self.platform_id,
            driver=type(self).__name__,
            maturity=self.maturity,
            detection=dict(detection or {}),
            collection_tier=tier,
            reports=reports,
            warnings=warnings,
        )
        metadata = dict(result.device.metadata)
        metadata["platform_driver"] = {
            "platform_id": self.platform_id,
            "driver": type(self).__name__,
            "capabilities": {
                report.capability: _LEGACY.get(report.status, report.status)
                for report in reports
            },
        }
        metadata["driver_diagnostics"] = diagnostics.to_dict()
        result = replace(result, device=replace(result.device, metadata=metadata))

        legacy = tuple(
            CapabilityStatus(
                report.capability,
                _LEGACY.get(report.status, report.status),
                report.detail[:120],
            )
            for report in reports
        )
        return self.annotate(DriverDiscovery(
            result=result, capabilities=legacy, raw_outputs=raw
        ))

    def _collect(
        self, transport, spec: CommandSpec, raw: dict, warnings: list
    ) -> CapabilityReport:
        attempted: list[str] = []
        for index, command in enumerate(spec.commands):
            attempted.append(command)
            if command in raw:
                output = raw[command]
            else:
                try:
                    output = transport.execute(command) or ""
                except Exception as error:  # noqa: BLE001
                    # THIS attempt broke; the platform said nothing. A
                    # required identity cannot be salvaged, everything else
                    # is preserved partial evidence (Part 5).
                    if spec.required:
                        raise AtlasDiscoveryError(
                            f"required capability '{spec.capability}' failed "
                            f"on {self.display_name}: {error}"
                        ) from error
                    raw.setdefault(command, "")
                    return CapabilityReport(
                        spec.capability, FAILED,
                        command_used=None,
                        commands_attempted=tuple(attempted),
                        detail=str(error)[:160],
                    )
                raw[command] = output

            if self.denied(output):
                return CapabilityReport(
                    spec.capability, FAILED,
                    command_used=None,
                    commands_attempted=tuple(attempted),
                    detail="privilege denied — the account may not run this",
                )
            if self.rejects(output):
                if index + 1 < len(spec.commands):
                    warnings.append(
                        f"{command!r} not recognized; falling back to "
                        f"{spec.commands[index + 1]!r}"
                    )
                    continue
                return CapabilityReport(
                    spec.capability, UNSUPPORTED,
                    command_used=None,
                    commands_attempted=tuple(attempted),
                    detail="the device rejected every command form",
                )

            status = (
                SUPPORTED_WITH_LIMITATIONS if spec.limitation else SUPPORTED
            )
            detail = spec.limitation or ""
            if not output.strip():
                detail = (detail + "; " if detail else "") + \
                    "command executed; the device had nothing to report"
            return CapabilityReport(
                spec.capability, status,
                command_used=command,
                commands_attempted=tuple(attempted),
                detail=detail,
            )
        raise AssertionError("unreachable: CommandSpec guarantees a command")
