"""Canonical device -> verified management endpoint (PR-044A, CONSOLE).

The security of the whole console rests here. Atlas observes a great many
addresses: OSPF router IDs, BGP peer addresses, route next hops, loopbacks,
interface addresses on point-to-point links, and peers it could not resolve
at all. **None of them are management endpoints.** Each proves a protocol
relationship, not that Atlas can log in there.

Exactly one kind of evidence qualifies: Atlas *authenticated to* the address
during discovery and collected the device's own identity from it. That is
not an inference — it is a demonstration, and it is the only reason a device
appears in the topology snapshot with a ``management_ip`` at all.

``discovery.multihop.management_candidate`` applies the same principle when
deciding where recursive discovery may knock. This module is stricter: a
candidate is somewhere Atlas *may try*; a console target is somewhere Atlas
*has already succeeded*.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from ipaddress import ip_address
from typing import Any

from .models import (
    ACTION_AVAILABLE,
    ACTION_CREDENTIAL_REQUIRED,
    ACTION_ENDPOINT_UNKNOWN,
    ACTION_EXPLANATIONS,
    ENDPOINT_VERIFIED_BY_DISCOVERY,
    ConsoleTarget,
)


def _valid_ip(value: Any) -> str | None:
    """An address only if it really is one. Never a hostname, never a guess."""

    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        ip_address(text)
    except ValueError:
        return None
    return text


def _int_port(value: Any, default: int = 22) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def resolve_target(
    device: Mapping[str, Any],
    *,
    network: str,
    scope_id: str,
    username: str | None = None,
    credential_ref: str | None = None,
    credential_name: str | None = None,
) -> ConsoleTarget:
    """Resolve one canonical device record into a console target.

    ``device`` is a topology-snapshot device: it exists only because Atlas
    opened an authenticated session to its ``management_ip``.

    Ineligible is a first-class answer, not an error. The GUI renders the
    reason and offers no SSH action.
    """

    device_id = str(device.get("device_id") or "").strip()
    hostname = str(device.get("hostname") or device_id or "unknown")
    platform = device.get("platform") or None
    vendor = device.get("vendor") or None

    base = ConsoleTarget(
        device_id=device_id,
        hostname=hostname,
        network=network,
        scope_id=scope_id,
        platform=platform,
        vendor=vendor,
    )

    management_ip = _valid_ip(device.get("management_ip"))
    if management_ip is None:
        # Observed, but never logged into. Say exactly that.
        return base

    port = _int_port(device.get("management_port"), 22)
    target = ConsoleTarget(
        device_id=device_id,
        hostname=hostname,
        network=network,
        scope_id=scope_id,
        platform=platform,
        vendor=vendor,
        management_ip=management_ip,
        port=port,
        username=username,
        credential_ref=credential_ref,
        credential_name=credential_name,
        endpoint_evidence=ENDPOINT_VERIFIED_BY_DISCOVERY,
        eligible=True,
        state=ACTION_AVAILABLE,
        reason=ACTION_EXPLANATIONS[ACTION_AVAILABLE],
    )
    if not credential_ref or not username:
        # The endpoint is verified; Atlas simply has nothing to log in with.
        # Still eligible — the operator can choose a credential set.
        return replace(
            target,
            state=ACTION_CREDENTIAL_REQUIRED,
            reason=ACTION_EXPLANATIONS[ACTION_CREDENTIAL_REQUIRED],
        )
    return target


def resolve_targets(
    devices: Iterable[Mapping[str, Any]],
    *,
    network: str,
    scope_id: str,
    username: str | None = None,
    credential_ref: str | None = None,
    credential_name: str | None = None,
) -> tuple[ConsoleTarget, ...]:
    """Every canonical device in a scope, resolved. Order is preserved."""

    return tuple(
        resolve_target(
            device,
            network=network,
            scope_id=scope_id,
            username=username,
            credential_ref=credential_ref,
            credential_name=credential_name,
        )
        for device in devices
    )


def find_target(
    devices: Iterable[Mapping[str, Any]],
    device_id: str,
    *,
    network: str,
    scope_id: str,
    username: str | None = None,
    credential_ref: str | None = None,
    credential_name: str | None = None,
) -> ConsoleTarget | None:
    """The console target for one canonical device id, or ``None``.

    ``None`` means "no such canonical device in this scope" — which is what
    an unresolved peer is. An unresolved peer is an *observation*, not a
    device: it never reaches this function's input, so it can never be
    given an SSH action.
    """

    wanted = str(device_id).strip()
    for device in devices:
        if str(device.get("device_id") or "").strip() == wanted:
            return resolve_target(
                device,
                network=network,
                scope_id=scope_id,
                username=username,
                credential_ref=credential_ref,
                credential_name=credential_name,
            )
    return None
