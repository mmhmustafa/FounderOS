"""Canonical device → verified web management (PR-044B, PORTAL).

The security root is the same one the console uses, and reused rather than
re-derived: a web action is offered only for an address Atlas *authenticated
to over SSH during discovery* — the device's ``management_ip``. A router ID,
BGP peer, next hop, unverified loopback, or unresolved peer is never the base
for a web URL, for exactly the reason it is never the base for an SSH session.

``console.resolve.resolve_target`` already decides whether a device has a
verified management endpoint at all. This module builds on that answer: only
where the console says "eligible" does PORTAL even look for a web service, and
the web address it uses is the same ``management_ip`` the console would SSH to.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from founderos_atlas.console.resolve import resolve_target as resolve_console_target

from .models import (
    STATE_ENDPOINT_UNKNOWN,
    STATE_EXPLANATIONS,
    STATE_HTTP_VERIFIED,
    STATE_HTTPS_VERIFIED,
    STATE_NOT_VERIFIED,
    ManagementService,
    WebAccess,
)


def resolve_web_access(
    device: Mapping[str, Any],
    *,
    network: str,
    scope_id: str,
    services: Iterable[ManagementService] = (),
    certificate_changed: bool = False,
    previous_fingerprint: str | None = None,
) -> WebAccess:
    """Resolve one canonical device into its web-management actions.

    ``services`` are the management services already known for this device
    (from the store, or a fresh verification). This function does no network
    I/O — it turns evidence into the action state the GUI renders. Detection
    and TLS live in ``verify.py``.
    """

    console = resolve_console_target(device, network=network, scope_id=scope_id)
    hostname = console.hostname
    device_id = console.device_id

    if not console.eligible or not console.management_ip:
        # No verified management endpoint → no web action, same as SSH.
        return WebAccess(
            device_id=device_id,
            hostname=hostname,
            management_ip=console.management_ip,
            state=STATE_ENDPOINT_UNKNOWN,
            reason=STATE_EXPLANATIONS[STATE_ENDPOINT_UNKNOWN],
        )

    management_ip = console.management_ip

    # Only this device's own services, and only at its verified address.
    # A service record naming another address is not this device's web UI.
    https = None
    http = None
    candidates: list[ManagementService] = []
    verified_at: str | None = None
    for service in services:
        if service.device_id != device_id:
            continue
        if service.address != management_ip and not service.operator_defined:
            # An operator override may legitimately point elsewhere (a
            # dedicated management VIP); an auto-probed service may not.
            continue
        if service.verified:
            if service.secure and (https is None):
                https = service
            elif not service.secure and (http is None):
                http = service
            verified_at = service.last_verified or verified_at
        else:
            candidates.append(service)

    if https is not None:
        state = STATE_HTTPS_VERIFIED
    elif http is not None:
        state = STATE_HTTP_VERIFIED
    else:
        state = STATE_NOT_VERIFIED

    return WebAccess(
        device_id=device_id,
        hostname=hostname,
        management_ip=management_ip,
        https=https,
        http=http,
        candidates=tuple(candidates),
        state=state,
        reason=STATE_EXPLANATIONS[state],
        certificate_changed=certificate_changed,
        previous_fingerprint=previous_fingerprint,
        verified_at=verified_at,
    )
