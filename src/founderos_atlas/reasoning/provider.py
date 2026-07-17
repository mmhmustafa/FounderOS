"""CORTEX evidence port — the source-agnostic seam (§3, §10).

The engine must not know that SSH, or a graph, or a JSON file exists. It knows
only :class:`Evidence`. A new evidence source (Syslog, SNMP, NetFlow,
telemetry) becomes a new provider implementing this port — never an engine
change. That is the whole test of the design in §10: adding Syslog must touch
zero lines of the engine, the calculus, or any rule.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .evidence import Evidence, EvidenceGap


@runtime_checkable
class EvidenceProvider(Protocol):
    """A source of evidence about a subject, at a point in time.

    Implementations gather from exactly one place (the Knowledge Graph,
    Enterprise Memory, one day a syslog collector) and normalize to
    :class:`Evidence`. They also report what they could *not* find as
    :class:`EvidenceGap` — absence is a return value here, not an omission.
    """

    def gather(
        self, subject: str, *, as_of: str | None = None, kinds: tuple[str, ...] = ()
    ) -> tuple[Evidence, ...]:
        """Evidence about ``subject`` as of ``as_of`` (None = latest). ``kinds``
        narrows to specific evidence kinds; empty means "everything you have"."""
        ...

    def describe_gaps(
        self, subject: str, *, as_of: str | None = None, kinds: tuple[str, ...] = ()
    ) -> tuple[EvidenceGap, ...]:
        """The evidence this provider could not supply for ``subject`` — so a
        conclusion can say honestly what it did not see."""
        ...
