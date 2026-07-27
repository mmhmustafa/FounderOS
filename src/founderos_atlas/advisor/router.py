"""Deterministic intent routing: which engine answers this question?

PR-164 (INTENT): detection itself now lives in the Operational Intent
Router — ``founderos_atlas.oir`` — Atlas's single orchestration engine.
This module delegates to it (same fixed-order phrase table, moved, not
changed) and keeps the deterministic question PARSERS the engines use.
Questions Atlas cannot answer from evidence still route to the honest
UNKNOWN intent — never to a guess.
"""

from __future__ import annotations

import re
from typing import Iterable


INTENT_HEALTH = "health"
INTENT_CHANGES = "changes"
INTENT_DISCOVERY = "discovery"
INTENT_PATH = "path"
INTENT_PREDICTION = "prediction"
INTENT_COMPASS = "compass"
INTENT_CONTINUE = "continue"
INTENT_SEARCH = "search"
INTENT_ENTERPRISE = "enterprise"
INTENT_INVESTIGATION = "investigation"
INTENT_UNKNOWN = "unknown"


# Words stripped from a search question to leave the query itself.
_SEARCH_STOPWORDS = frozenset(
    "find search for where is show me look up locate the a an device site "
    "interface please can you atlas".split()
)


def route(question: str, *, sites: Iterable[str] = ()):
    """The full OIR routing decision (intent + engine + confidence +
    why). ``sites`` are the enterprise's known site names, used only to
    refine WITHIN a family (e.g. Site Health) — never to guess."""

    from founderos_atlas.oir import detect

    return detect(question, sites=sites)


def classify(question: str) -> str:
    """The engine for one question — deterministic, first match wins.

    Delegates to the OIR catalog, which carries the exact fixed-order
    rule table this module used to hold. Kept for every existing
    caller; ``route()`` is the richer decision.
    """

    return route(question).engine


def search_query(question: str) -> str:
    """The object being searched for, with routing verbs stripped.

    Punctuation is trimmed from token EDGES only — dots inside tokens
    survive, so IP addresses and dotted hostnames stay intact.
    """

    cleaned = re.sub(r"[?!,]", " ", str(question or ""))
    tokens = [
        token.strip(".")
        for token in cleaned.split()
        if token.strip(".").casefold() not in _SEARCH_STOPWORDS
        and token.strip(".")
    ]
    return " ".join(tokens).strip()


def path_endpoints(question: str) -> tuple[str | None, str | None]:
    """Source/destination when the question names them, else Nones.

    Recognized shapes (deterministic regex, no guessing):
    "... from X to Y", "can X reach Y", "X cannot reach Y",
    "path between X and Y".
    """

    cleaned = re.sub(r"[?!,]", " ", str(question or ""))
    for pattern in (
        r"\bfrom\s+(\S+)\s+to\s+(\S+)",
        r"\bcan\s+(\S+)\s+reach\s+(\S+)",
        r"\b(\S+)\s+(?:cannot|can't|cant)\s+reach\s+(\S+)",
        r"\bbetween\s+(\S+)\s+and\s+(\S+)",
        r"\b(\S+)\s+(?:is\s+)?unreachable\s+from\s+(\S+)",
    ):
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            first = match.group(1).strip(".")
            second = match.group(2).strip(".")
            if pattern.endswith("from\\s+(\\S+)"):
                return second, first  # "X unreachable from Y": Y -> X
            return first, second
    return None, None


def discovery_launch(question: str) -> dict | None:
    """Recognize a discovery LAUNCH/RESUME request (vs a summary ask).

    Returns the parsed intent — a CIDR, a resume flag, or a named target
    — so Advisor can guide the engineer to the Discovery Wizard. Advisor
    never runs discovery itself; it points to the workflow (PR-043.2).
    """

    folded = " ".join(str(question or "").casefold().split())
    cidr = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b", question or "")
    launch = any(
        verb in folded
        for verb in ("run discovery", "run a discovery", "start discovery",
                     "scan ", "discover ", "onboard")
    )
    resume = "resume" in folded
    if cidr:
        return {"kind": "subnet", "cidr": cidr.group(1)}
    if resume and "discover" in folded:
        return {"kind": "resume"}
    if launch:
        return {"kind": "launch"}
    return None


def prediction_target(question: str) -> tuple[str | None, str | None]:
    """(device, interface) when the question names them, else Nones.

    Recognized shapes: "... <verb> <interface> on <device>" and
    "... <verb> <device>" for device-level changes.
    """

    cleaned = re.sub(r"[?!,]", " ", str(question or ""))
    match = re.search(
        r"\b(?:disable|shut(?:\s*down)?|shutdown)\s+(\S+)\s+on\s+(\S+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(2).strip("."), match.group(1).strip(".")
    match = re.search(
        r"\b(?:reboot|reload|upgrade)\s+(\S+)", cleaned, flags=re.IGNORECASE
    )
    if match:
        return match.group(1).strip("."), None
    return None, None
