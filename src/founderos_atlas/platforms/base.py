"""The Platform Driver framework: Atlas discovers platforms, never vendors.

A ``PlatformDriver`` owns everything platform-specific about discovery:
how to recognize the platform from a lightweight probe, which read-only
commands collect each capability, and how to normalize the output into
Atlas's canonical models (``NetworkDevice`` / ``NetworkInterface`` /
``NetworkNeighbor`` via the existing parse-only ``DiscoveryAdapter``
layer). The discovery engine interacts ONLY with this interface;
downstream engines (federation, prediction, path intelligence, Compass,
Advisor, Mission) consume only canonical models and never see a
platform-specific object.

Capabilities never fail a discovery: a daemon that is not configured or
a command a platform does not support is RECORDED, not raised.
Discovery succeeds whenever meaningful evidence is collected.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from founderos_atlas.discovery.adapter import DiscoveryAdapter
from founderos_atlas.discovery.engine import DiscoveryEngine
from founderos_atlas.discovery.exceptions import AtlasDiscoveryError
from founderos_atlas.discovery.models import DiscoveryResult


# The lightweight detection probe. Both current families answer it:
# Cisco IOS/IOS-XE ("Cisco IOS Software, ... Version ...") and FRRouting
# vtysh ("FRRouting X.Y ..."). Drivers for platforms with a different
# probe can declare their own; the detector tries each distinct probe.
DEFAULT_PROBE_COMMAND = "show version"

# Capability states — recorded, never raised.
CAP_COLLECTED = "collected"          # command ran and produced evidence
CAP_EMPTY = "empty"                  # command ran; nothing to report
CAP_NOT_CONFIGURED = "not-configured"  # platform says the feature is off
CAP_UNAVAILABLE = "unavailable"      # command unsupported or failed
CAP_NOT_COLLECTED = "not-collected"  # driver does not collect this yet


@dataclass(frozen=True)
class CapabilitySpec:
    """One capability a driver knows how to collect."""

    name: str          # interfaces | neighbors | routes | ospf | bgp | ...
    command: str
    required: bool = False  # required capabilities fail discovery if absent


@dataclass(frozen=True)
class CapabilityStatus:
    name: str
    state: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "state": self.state, "detail": self.detail}


@dataclass(frozen=True)
class DriverDiscovery:
    """One device's normalized discovery plus its capability report."""

    result: DiscoveryResult
    capabilities: tuple[CapabilityStatus, ...] = ()
    raw_outputs: dict[str, str] = field(default_factory=dict)

    def capability(self, name: str) -> CapabilityStatus | None:
        for status in self.capabilities:
            if status.name == name:
                return status
        return None


class PlatformDriver(ABC):
    """Everything platform-specific, behind one generic interface.

    Subclasses provide identity metadata, a probe matcher, the parse
    adapter, and the capability collection plan; the base class owns the
    generic collect → parse → annotate flow so drivers stay declarative.
    """

    platform_id: str          # "cisco-ios" | "frr" | ...
    display_name: str         # "Cisco IOS / IOS-XE"
    vendor: str
    probe_command: str = DEFAULT_PROBE_COMMAND

    # Optional detection fingerprints (PR: multi-vendor detection). Regex
    # fragments matched case-insensitively against the SSH banner and the
    # CLI prompt when the transport can observe them. Fingerprints add
    # EVIDENCE and break ties between probe matchers; a fingerprint alone
    # never selects a driver — the probe output stays authoritative.
    banner_fingerprints: tuple[str, ...] = ()
    prompt_fingerprints: tuple[str, ...] = ()

    # -- detection -----------------------------------------------------------

    @classmethod
    @abstractmethod
    def matches(cls, probe_output: str) -> bool:
        """Whether the probe output identifies this platform."""

        raise NotImplementedError

    # -- platform specifics ----------------------------------------------------

    @property
    @abstractmethod
    def adapter(self) -> DiscoveryAdapter:
        """The parse-only adapter normalizing output into canonical models."""

        raise NotImplementedError

    @abstractmethod
    def collection_plan(self) -> tuple[CapabilitySpec, ...]:
        """Every capability this driver collects, in execution order."""

        raise NotImplementedError

    def classify_output(self, spec: CapabilitySpec, output: str) -> CapabilityStatus:
        """Map one command's output onto a capability state.

        The default treats vtysh/CLI error markers as not-configured or
        unavailable; drivers refine this per platform.
        """

        stripped = output.strip()
        if not stripped:
            return CapabilityStatus(spec.name, CAP_EMPTY, "no output")
        folded = stripped.casefold()
        if folded.startswith("% unknown command") or "invalid input" in folded:
            return CapabilityStatus(
                spec.name, CAP_UNAVAILABLE, "command not supported"
            )
        if folded.startswith("%"):
            return CapabilityStatus(
                spec.name, CAP_NOT_CONFIGURED, stripped.splitlines()[0][:120]
            )
        return CapabilityStatus(spec.name, CAP_COLLECTED, "")

    def annotate(
        self, discovery: DriverDiscovery
    ) -> DriverDiscovery:  # pragma: no cover - default is identity
        """Hook for drivers to add platform evidence (route counts, BGP
        peers, …) into canonical metadata AFTER parsing."""

        return discovery

    # -- the generic flow --------------------------------------------------------

    def discover(
        self,
        transport,
        *,
        management_ip_hint: str | None = None,
        probe_output: str | None = None,
    ) -> DriverDiscovery:
        """Collect the plan over an OPEN transport, then normalize.

        The probe output is reused (never re-executed); optional
        capabilities that fail are recorded as unavailable instead of
        failing the device.
        """

        raw: dict[str, str] = {}
        if probe_output is not None:
            raw[self.probe_command] = probe_output
        statuses: list[CapabilityStatus] = []
        for spec in self.collection_plan():
            if spec.command in raw:
                statuses.append(self.classify_output(spec, raw[spec.command]))
                continue
            try:
                output = transport.execute(spec.command)
            except Exception as error:  # noqa: BLE001 - recorded, not raised
                if spec.required:
                    raise AtlasDiscoveryError(
                        f"required capability '{spec.name}' failed on "
                        f"{self.display_name}: {error}"
                    ) from error
                statuses.append(
                    CapabilityStatus(
                        spec.name, CAP_UNAVAILABLE, str(error)[:120]
                    )
                )
                raw[spec.command] = ""
                continue
            raw[spec.command] = output
            statuses.append(self.classify_output(spec, output))
        result = DiscoveryEngine(self.adapter).discover(
            raw, management_ip_hint=management_ip_hint
        )
        result = _with_platform_metadata(result, self, tuple(statuses))
        return self.annotate(
            DriverDiscovery(
                result=result, capabilities=tuple(statuses), raw_outputs=raw
            )
        )


def _with_platform_metadata(
    result: DiscoveryResult, driver: PlatformDriver, statuses
) -> DiscoveryResult:
    """Stamp canonical device metadata with platform + capability facts."""

    from dataclasses import replace

    metadata = dict(result.device.metadata)
    metadata["platform_driver"] = {
        "platform_id": driver.platform_id,
        "driver": type(driver).__name__,
        "capabilities": {
            status.name: status.state for status in statuses
        },
    }
    return replace(result, device=replace(result.device, metadata=metadata))
