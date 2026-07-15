"""CORTEX evidence types — the missing shared abstraction (§1.5.1, §3).

Today "evidence" is a ``str`` in root_cause, an ``EvidenceItem`` in Advisor, a
``dict`` in correlation, a ``ConfidenceFactor`` in prediction. There is no one
notion of "a thing Atlas observed, from a source, at a time, with a strength."
This module is that notion, so a rule never has to care whether a fact came
from OSPF, a running-config, or (one day) Syslog.

Two types, both immutable and credential-free by contract:

- :class:`Evidence` — something Atlas observed. Its ``payload`` is normalized
  and never carries a raw secret; the ``text`` a policy matches against is
  masked at the point it enters here.
- :class:`EvidenceGap` — absence as data. "Unknown stays unknown" becomes
  structural: a gap is a first-class return value, not a missing key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# -- evidence strength (the only thing the calculus needs to know) -----------
#
# The bridge from an evidence item to §6's factors: a rule declares it saw a
# ``DIRECT`` observation; the engine prices that as ``direct_observation()``.
# A rule never reasons about the source, only the strength.

STRENGTH_DIRECT = "direct"                # Atlas saw it on the device itself
STRENGTH_CORROBORATING = "corroborating"  # an independent source agrees
STRENGTH_CIRCUMSTANTIAL = "circumstantial"  # indirect / inferred
STRENGTH_ABSENT = "absent"                # recorded non-observation

STRENGTHS = (
    STRENGTH_DIRECT,
    STRENGTH_CORROBORATING,
    STRENGTH_CIRCUMSTANTIAL,
    STRENGTH_ABSENT,
)


# -- why a gap exists (open, small vocabulary) -------------------------------

GAP_NOT_COLLECTED = "not-collected"           # Atlas never gathered it
GAP_UNREACHABLE = "unreachable"               # the device could not be reached
GAP_UNSUPPORTED = "unsupported-platform"      # the platform cannot express it
GAP_NOT_MODELLED = "not-modelled"             # Atlas does not represent this layer


@dataclass(frozen=True)
class EvidenceProvenance:
    """Where a piece of evidence came from — the conclusion-level analogue of
    PR-045R's raw-evidence provenance. References only, never a secret."""

    source: str                       # cli | syslog | snmp | … (PR-045 SOURCE_*)
    session_id: str | None = None
    command: str | None = None
    parser_version: str | None = None
    atlas_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "command": self.command,
            "parser_version": self.parser_version,
            "atlas_version": self.atlas_version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvidenceProvenance":
        return cls(
            source=str(value.get("source") or "cli"),
            session_id=value.get("session_id"),
            command=value.get("command"),
            parser_version=value.get("parser_version"),
            atlas_version=value.get("atlas_version"),
        )


@dataclass(frozen=True)
class Evidence:
    """One thing Atlas observed, normalized across every source.

    ``kind`` is an open vocabulary (``running-config``, ``ospf-neighbor``,
    ``access-transport``, one day ``syslog-event``…). ``text`` is the searchable
    body a rule matches against — already masked, so a rule and everything
    downstream of it can be shown without leaking a credential. ``observed_at``
    is when the *network* showed it; ``recorded_at`` is when *Atlas* learned it
    (the two are distinguished exactly as PR-045R distinguishes them).
    """

    id: str
    kind: str
    source: str
    subject: str                      # canonical device id / relationship / network
    strength: str = STRENGTH_DIRECT
    observed_at: str | None = None
    recorded_at: str | None = None
    summary: str = ""                 # one-line human description
    text: str = ""                    # masked body a rule matches against
    provenance: EvidenceProvenance | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "subject": self.subject,
            "strength": self.strength,
            "observed_at": self.observed_at,
            "recorded_at": self.recorded_at,
            "summary": self.summary,
            "text": self.text,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Evidence":
        prov = value.get("provenance")
        return cls(
            id=str(value["id"]),
            kind=str(value.get("kind") or ""),
            source=str(value.get("source") or "cli"),
            subject=str(value.get("subject") or ""),
            strength=str(value.get("strength") or STRENGTH_DIRECT),
            observed_at=value.get("observed_at"),
            recorded_at=value.get("recorded_at"),
            summary=str(value.get("summary") or ""),
            text=str(value.get("text") or ""),
            provenance=EvidenceProvenance.from_dict(prov) if prov else None,
            payload=dict(value.get("payload") or {}),
        )


@dataclass(frozen=True)
class EvidenceGap:
    """Absence, as a first-class value. This is how ``unknowns`` /
    ``missing_evidence`` / ``unknown_layers`` (three names today) become one
    thing — and how a conclusion can honestly say what it could *not* see."""

    kind: str                         # the evidence kind that is missing
    subject: str
    why: str = GAP_NOT_COLLECTED
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "why": self.why,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EvidenceGap":
        return cls(
            kind=str(value.get("kind") or ""),
            subject=str(value.get("subject") or ""),
            why=str(value.get("why") or GAP_NOT_COLLECTED),
            detail=str(value.get("detail") or ""),
        )
