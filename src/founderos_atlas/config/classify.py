"""Positive configuration classification (PR-181).

The inversion this module exists for:

    A reply becomes a configuration ONLY when the resolved platform driver
    can positively confirm it is one. Refusal grammar EXPLAINS a rejection;
    it never authorises an acceptance.

Every earlier gate in Atlas asked the weaker question — "does this text
look like a refusal I recognise?" — and accepted anything unrecognised.
That is how a Junos device's "unknown command." became a stored running
configuration with a complete status and zero warnings.

Two measured failure modes shape the probe design:

- Refusal grammars are position-anchored, so a multi-line login banner in
  front of a genuine refusal defeated every classifier in the repository.
  Grammar is therefore probed per line over the FIRST three and LAST three
  non-blank lines, plus the joined tail and the whole reply.
- A valid configuration can quote refusal grammar inside a description or
  banner. The positive test therefore runs FIRST: a document that carries
  configuration structure is a configuration, whatever words it contains.

There is deliberately no minimum-line-count heuristic here: a three-line
Junos stub is a real configuration, and the repository's own Cisco WLC
fixture is five lines. Structure decides, not size.
"""

from __future__ import annotations

from typing import Any

from .models import (
    STATUS_COLLECTED,
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_UNRECOGNISED,
    STATUS_UNSUPPORTED,
)


def probe_regions(reply: str) -> tuple[str, ...]:
    """The regions refusal grammar is probed against, most-anchored first.

    Each of the first three and last three non-blank lines individually
    (a banner cannot push a refusal out of a per-line probe), then the
    joined tail, then the whole reply (a refusal at the top of a long
    usage block is still a refusal).
    """

    lines = [line for line in (reply or "").splitlines() if line.strip()]
    regions: list[str] = []
    regions.extend(lines[:3])
    regions.extend(lines[-3:])
    if lines:
        regions.append("\n".join(lines[-3:]))
    regions.append(reply or "")
    # Order-preserving dedupe: a two-line reply repeats its lines above.
    return tuple(dict.fromkeys(region for region in regions if region.strip()))


def shared_structural_is_configuration(reply: str) -> bool:
    """The shared positive test: does this text carry configuration structure?

    Evidence, cheapest first: the structural fingerprint (hostname or any
    stanza count) and, failing that, extracted configuration facts. Both are
    Cisco/FRR-shaped — platforms whose configuration grammar differs
    (FortiOS, PAN-OS, Junos, Cisco WLC) override ``is_configuration`` on
    their drivers rather than relying on this default.
    """

    if not reply or not reply.strip():
        return False
    from founderos_atlas.enterprise_memory.fingerprint import fingerprint

    print_ = fingerprint(reply)
    if print_ is not None:
        shape = print_.to_dict()
        counts = [
            value for key, value in shape.items()
            if key.endswith("_count") and key != "line_count"
        ]
        if shape.get("hostname") or any(counts):
            return True
    from founderos_atlas.config_memory.extract import extract_facts

    summary = extract_facts(reply).summary()
    return any(
        value for key, value in summary.items() if key != "warnings"
    )


def _driver_is_configuration(driver: Any, reply: str) -> bool:
    probe = getattr(driver, "is_configuration", None)
    if callable(probe):
        return bool(probe(reply))
    return shared_structural_is_configuration(reply)


def _driver_denied(driver: Any, region: str) -> bool:
    probe = getattr(driver, "denied", None)
    if callable(probe):
        return bool(probe(region))
    # Legacy drivers have no denial channel; Atlas does not claim a
    # specificity it cannot establish (a denial reads as a refusal below).
    return False


# The refusal grammar applied when no driver can be consulted at all: the
# transport-family markers plus the two legacy-CLI shell grammars. Bounded
# risk: the positive test has already failed by the time this runs.
_FALLBACK_REFUSALS = (
    "% invalid input",
    "invalid input detected",
    "% unknown command",
    "% invalid command",
    "% incomplete command",
)
_FALLBACK_SHELL_REFUSALS = ("unknown command", "not found")


def _fallback_rejects(region: str) -> bool:
    folded = region.strip().casefold()
    if not folded:
        return False
    if any(marker in folded[:200] for marker in _FALLBACK_REFUSALS):
        return True
    return folded.startswith(_FALLBACK_SHELL_REFUSALS)


def _driver_rejects(driver: Any, region: str) -> bool:
    probe = getattr(driver, "rejects", None)
    if callable(probe):
        return bool(probe(region))
    classify = getattr(driver, "classify_output", None)
    if callable(classify):
        # Legacy PlatformDriver path: reuse the driver's own grammar
        # (including AtlasLab shell overrides) via classify_output.
        from founderos_atlas.platforms.base import CAP_UNAVAILABLE, CapabilitySpec

        spec = CapabilitySpec("configuration", "configuration-probe")
        try:
            return classify(spec, region).state == CAP_UNAVAILABLE
        except Exception:  # noqa: BLE001 - a probe must never break collection
            return _fallback_rejects(region)
    return _fallback_rejects(region)


def classify_configuration_reply(
    driver: Any, reply: str
) -> tuple[str, str]:
    """One typed verdict for a configuration command's reply.

    Returns ``(status, detail)`` with status one of STATUS_COLLECTED /
    STATUS_DENIED / STATUS_UNSUPPORTED / STATUS_EMPTY / STATUS_UNRECOGNISED.
    Ordering is load-bearing and fails closed:

    1. empty / whitespace-only              -> EMPTY
    2. positive confirmation                -> COLLECTED
    3. denial grammar (per region)          -> DENIED
    4. refusal grammar (per region)         -> UNSUPPORTED
    5. everything else                      -> UNRECOGNISED
    """

    if not reply or not reply.strip():
        return STATUS_EMPTY, "the device returned no output"

    if _driver_is_configuration(driver, reply):
        return STATUS_COLLECTED, ""

    regions = probe_regions(reply)
    for region in regions:
        if _driver_denied(driver, region):
            return (
                STATUS_DENIED,
                "the device denied the command; the account lacks privilege",
            )
    for region in regions:
        if _driver_rejects(driver, region):
            return (
                STATUS_UNSUPPORTED,
                "the device rejected the command as not supported",
            )

    lines = sum(1 for line in reply.splitlines() if line.strip())
    return (
        STATUS_UNRECOGNISED,
        f"the device answered {len(reply.encode('utf-8'))} bytes over "
        f"{lines} line(s) that could not be confirmed as a configuration",
    )
