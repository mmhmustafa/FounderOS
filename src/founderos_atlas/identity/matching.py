"""Configurable, vendor-neutral device identity matching rules.

Rules are pure predicates over two ``DeviceIdentity`` values. The resolver
applies them in order; the first rule that matches merges two observations
into one cluster. New vendors extend matching by appending rules — never by
editing existing ones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .canonical import (
    DeviceIdentity,
    is_bare_hostname,
    normalize_hostname,
    short_hostname,
)


class MatchRule(ABC):
    """One reason two identities describe the same physical device."""

    name: str = "match-rule"

    @abstractmethod
    def matches(self, first: DeviceIdentity, second: DeviceIdentity) -> bool:
        raise NotImplementedError


class SerialNumberMatch(MatchRule):
    name = "serial-number"

    def matches(self, first: DeviceIdentity, second: DeviceIdentity) -> bool:
        if first.serial_number is None or second.serial_number is None:
            return False
        return first.serial_number.casefold() == second.serial_number.casefold()


class ManagementIPMatch(MatchRule):
    name = "management-ip"

    def matches(self, first: DeviceIdentity, second: DeviceIdentity) -> bool:
        return bool(set(first.management_ips) & set(second.management_ips))


class HostnameMatch(MatchRule):
    """Normalized hostname equality, plus bare-name == FQDN-first-label.

    ``R1`` matches ``r1``, ``R1.`` and ``R1.atlas.local``. Two FQDNs in
    different domains (``web.prod.local`` vs ``web.dev.local``) never match:
    at least one side must be a bare name for label matching to apply.
    """

    name = "hostname"

    def matches(self, first: DeviceIdentity, second: DeviceIdentity) -> bool:
        for a in first.hostnames:
            for b in second.hostnames:
                if _hostnames_match(a, b):
                    return True
        return False


class ExtraIdentifierMatch(MatchRule):
    """Exact match on a named extra identifier (chassis ID, system MAC, UUID...).

    The extension point for vendor-specific identity: register the identifier
    in device metadata and append ``ExtraIdentifierMatch("<key>")`` to the
    resolver's rules.
    """

    def __init__(self, key: str) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-empty string")
        self.key = key.strip()
        self.name = f"identifier:{self.key}"

    def matches(self, first: DeviceIdentity, second: DeviceIdentity) -> bool:
        a = first.extra_identifiers.get(self.key)
        b = second.extra_identifiers.get(self.key)
        if not a or not b:
            return False
        return a.casefold() == b.casefold()


def _hostnames_match(a: str, b: str) -> bool:
    na, nb = normalize_hostname(a), normalize_hostname(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if is_bare_hostname(a) and short_hostname(b) == na:
        return True
    if is_bare_hostname(b) and short_hostname(a) == nb:
        return True
    return False


DEFAULT_MATCH_RULES: tuple[MatchRule, ...] = (
    SerialNumberMatch(),
    ManagementIPMatch(),
    HostnameMatch(),
)
