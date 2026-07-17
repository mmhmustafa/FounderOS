"""Concrete evidence providers — the adapters behind the port (§3).

These bridge CORTEX to the evidence stores Atlas already has (PR-045 Enterprise
Memory, and in future the Knowledge Graph). They are the *only* place in the
reasoning stack that knows those stores exist; the engine, the calculus, and
every rule see nothing but :class:`Evidence`.

A deliberate safety property: every ``Evidence.text`` produced here is **masked**
(through Enterprise Memory's ``view_*`` path), so a credential never enters the
reasoning layer, a rendered result, or a rule's matching input. The starter
policies match structural directives (``hostname``, ``router bgp``,
``ntp server`` …) which are never secrets, so masking does not affect any
verdict — it only guarantees raw secrets stay in the local blob store.
"""

from __future__ import annotations

from founderos_atlas.enterprise_memory import EnterpriseMemory
from founderos_atlas.enterprise_memory.models import ConfigurationSnapshot

from .evidence import (
    GAP_NOT_COLLECTED,
    STRENGTH_DIRECT,
    Evidence,
    EvidenceGap,
    EvidenceProvenance,
)


# Evidence kinds this provider emits (the open vocabulary, made concrete).
KIND_RUNNING_CONFIG = "running-config"
KIND_ACCESS_TRANSPORT = "access-transport"


class MemoryEvidenceProvider:
    """Evidence about a canonical device drawn from Enterprise Memory.

    Emits two kinds today:

    - ``running-config`` — the latest configuration snapshot (masked), the
      primary evidence for configuration compliance.
    - ``access-transport`` — a synthesized record of how Atlas reached the
      device (e.g. it authenticated over SSH), so a policy like "SSH enabled"
      is grounded in the *observed* transport rather than in config text a
      platform may not express.

    ``as_of`` selects the newest snapshot recorded at or before that instant, so
    reasoning can time-travel over Memory. ``None`` means "latest".
    """

    def __init__(self, memory: EnterpriseMemory) -> None:
        self._memory = memory

    # -- port ---------------------------------------------------------------

    def gather(
        self, subject: str, *, as_of: str | None = None, kinds: tuple[str, ...] = ()
    ) -> tuple[Evidence, ...]:
        want = set(kinds)
        evidence: list[Evidence] = []

        if not want or KIND_RUNNING_CONFIG in want:
            config = self._config_evidence(subject, as_of)
            if config is not None:
                evidence.append(config)

        if not want or KIND_ACCESS_TRANSPORT in want:
            access = self._access_evidence(subject, as_of)
            if access is not None:
                evidence.append(access)

        return tuple(evidence)

    def describe_gaps(
        self, subject: str, *, as_of: str | None = None, kinds: tuple[str, ...] = ()
    ) -> tuple[EvidenceGap, ...]:
        want = set(kinds)
        gaps: list[EvidenceGap] = []
        if not want or KIND_RUNNING_CONFIG in want:
            if self._pick_snapshot(subject, as_of) is None:
                gaps.append(
                    EvidenceGap(
                        kind=KIND_RUNNING_CONFIG,
                        subject=subject,
                        why=GAP_NOT_COLLECTED,
                        detail=(
                            "no configuration snapshot in Enterprise Memory for "
                            "this device (configuration collection is policy-driven)"
                        ),
                    )
                )
        return tuple(gaps)

    # -- internals ----------------------------------------------------------

    def _pick_snapshot(
        self, subject: str, as_of: str | None
    ) -> ConfigurationSnapshot | None:
        snaps = self._memory.configuration_timeline(subject, newest_first=True)
        for snap in snaps:
            if not snap.config_sha256:
                continue
            if as_of is None or (snap.captured_at and snap.captured_at <= as_of):
                return snap
        return None

    def _config_evidence(self, subject: str, as_of: str | None) -> Evidence | None:
        snap = self._pick_snapshot(subject, as_of)
        if snap is None:
            return None
        masked, _masked_count = self._memory.view_configuration(snap.config_sha256)
        if masked is None:
            return None
        return Evidence(
            id=f"config:{snap.config_sha256[:16]}",
            kind=KIND_RUNNING_CONFIG,
            source="cli",
            subject=subject,
            strength=STRENGTH_DIRECT,
            observed_at=snap.captured_at,
            recorded_at=snap.captured_at,
            summary=(
                f"running configuration ({snap.byte_size} bytes, "
                f"{snap.platform or 'unknown platform'})"
            ),
            text=masked,
            provenance=EvidenceProvenance(
                source="cli",
                session_id=snap.discovery_session,
                command="show running-config",
                atlas_version=snap.atlas_version,
            ),
            payload={
                "platform": snap.platform,
                "software_version": snap.software_version,
                "config_sha256": snap.config_sha256,
                "captured_at": snap.captured_at,
                "fingerprint": dict(snap.fingerprint) if snap.fingerprint else None,
            },
        )

    def _access_evidence(self, subject: str, as_of: str | None) -> Evidence | None:
        records = self._memory.get_raw_evidence(subject)
        if not records:
            return None
        transports = sorted({r.transport for r in records if r.transport})
        platforms = sorted({r.platform for r in records if r.platform})
        if not transports:
            return None
        latest = max((r.collected_at for r in records if r.collected_at), default=None)
        lines = ["transport: " + ", ".join(transports)]
        if platforms:
            lines.append("platform: " + ", ".join(platforms))
        return Evidence(
            id=f"access:{subject}",
            kind=KIND_ACCESS_TRANSPORT,
            source="cli",
            subject=subject,
            strength=STRENGTH_DIRECT,
            observed_at=latest,
            recorded_at=latest,
            summary="Atlas authenticated to this device during discovery",
            text="\n".join(lines),
            provenance=EvidenceProvenance(source="cli"),
            payload={"transports": transports, "platforms": platforms},
        )
