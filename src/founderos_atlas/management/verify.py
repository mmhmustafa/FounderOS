"""Web-management detection and verification (PR-044B, PORTAL).

The rule that governs everything here: **a listening port is only a
candidate.** Atlas does not call a service verified until it has spoken HTTP
(or TLS+HTTP) and received a response — an open TCP port is a socket, not a
management interface.

Bounded and concurrent by construction: each probe has a short timeout, ports
are checked in parallel, and the whole thing is designed to ride *after* a
device is already discovered, so it adds no material delay to discovery. HTTPS
ports are always tried before HTTP, so a device offering both is verified on
its secure endpoint.

Atlas only ever probes the address it authenticated to over SSH, so a web
server answering there belongs to the canonical device by construction; what
this module adds is that the thing answering is a *web* service.
"""

from __future__ import annotations

import concurrent.futures as futures
import socket
from datetime import datetime, timezone
from typing import Any, Callable

from .certs import inspect_certificate
from .models import (
    DEFAULT_HTTP_PORTS,
    DEFAULT_HTTPS_PORTS,
    EVIDENCE_HTTP_RESPONSE,
    EVIDENCE_PORT_OPEN,
    EVIDENCE_TLS_HTTP_RESPONSE,
    PROTOCOL_HTTP,
    PROTOCOL_HTTPS,
    VERIFICATION_CANDIDATE,
    VERIFICATION_VERIFIED,
    ManagementService,
)


DEFAULT_CONNECT_TIMEOUT = 2.0
DEFAULT_MAX_WORKERS = 8


class WebServiceVerifier:
    """Probe a canonical device's management address for a web interface."""

    def __init__(
        self,
        *,
        https_ports: tuple[int, ...] = DEFAULT_HTTPS_PORTS,
        http_ports: tuple[int, ...] = DEFAULT_HTTP_PORTS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        max_workers: int = DEFAULT_MAX_WORKERS,
        clock: Callable[[], datetime] | None = None,
        # Injectable for tests: probe(address, port, secure, timeout) ->
        # dict|None. None means "not a web service".
        probe: Callable[..., dict[str, Any] | None] | None = None,
        certificate_inspector: Callable[..., Any] | None = None,
    ) -> None:
        self._https_ports = tuple(https_ports)
        self._http_ports = tuple(http_ports)
        self._timeout = float(connect_timeout)
        self._max_workers = int(max_workers)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._probe = probe or _http_probe
        self._inspect = certificate_inspector or inspect_certificate

    def verify(
        self,
        device_id: str,
        address: str,
        *,
        extra_https_ports: tuple[int, ...] = (),
        extra_http_ports: tuple[int, ...] = (),
        known: dict[tuple[str, int], ManagementService] | None = None,
    ) -> tuple[ManagementService, ...]:
        """Every web service found at ``address``, HTTPS first.

        ``known`` (keyed by ``(protocol, port)``) lets first_observed carry
        forward and a certificate change be detected against the last seen
        fingerprint.
        """

        now = self._clock().isoformat(timespec="seconds")
        known = known or {}
        jobs: list[tuple[str, int]] = []
        for port in _dedup(self._https_ports + extra_https_ports):
            jobs.append((PROTOCOL_HTTPS, port))
        for port in _dedup(self._http_ports + extra_http_ports):
            jobs.append((PROTOCOL_HTTP, port))

        results: list[ManagementService] = []
        with futures.ThreadPoolExecutor(
            max_workers=min(self._max_workers, max(1, len(jobs)))
        ) as pool:
            future_map = {
                pool.submit(self._verify_one, device_id, address, proto, port, now, known): (proto, port)
                for proto, port in jobs
            }
            for future in futures.as_completed(future_map):
                service = future.result()
                if service is not None:
                    results.append(service)

        # HTTPS before HTTP; within a protocol, lowest port first — a stable,
        # deterministic order the UI can rely on.
        results.sort(key=lambda s: (0 if s.secure else 1, s.port))
        return tuple(results)

    def _verify_one(
        self,
        device_id: str,
        address: str,
        protocol: str,
        port: int,
        now: str,
        known: dict[tuple[str, int], ManagementService],
    ) -> ManagementService | None:
        secure = protocol == PROTOCOL_HTTPS
        previous = known.get((protocol, port))
        first_observed = previous.first_observed if previous else now

        try:
            response = self._probe(address, port, secure, self._timeout)
        except Exception:  # noqa: BLE001 - unreachable/refused is just absence
            return None
        if response is None:
            # Nothing answered at all — not even an open port worth recording.
            return None

        tls = None
        if secure:
            try:
                tls = self._inspect(address, port, timeout=self._timeout)
            except Exception:  # noqa: BLE001
                tls = None

        answered_http = response.get("answered_http", False)
        if not answered_http:
            # The port is open (or TLS handshook) but did not speak HTTP.
            # That is a CANDIDATE, never verified.
            return ManagementService(
                device_id=device_id,
                address=address,
                protocol=protocol,
                port=port,
                verification=VERIFICATION_CANDIDATE,
                evidence=EVIDENCE_PORT_OPEN,
                first_observed=first_observed,
                last_verified=None,
                tls=tls,
                http_status=response.get("status"),
                server_header=response.get("server"),
                detail="A port answered but not as a web interface.",
            )

        return ManagementService(
            device_id=device_id,
            address=address,
            protocol=protocol,
            port=port,
            verification=VERIFICATION_VERIFIED,
            evidence=EVIDENCE_TLS_HTTP_RESPONSE if secure else EVIDENCE_HTTP_RESPONSE,
            first_observed=first_observed,
            last_verified=now,
            tls=tls,
            http_status=response.get("status"),
            server_header=response.get("server"),
        )


def detect_certificate_change(
    previous: ManagementService | None, current: ManagementService | None
) -> tuple[bool, str | None]:
    """Whether the TLS fingerprint changed between two sightings.

    A changed certificate is not silently accepted anywhere — it is surfaced
    so the operator reviews it, exactly as a changed SSH host key is.
    """

    if previous is None or current is None:
        return False, None
    p = previous.tls.fingerprint_sha256 if previous.tls else None
    c = current.tls.fingerprint_sha256 if current.tls else None
    if p and c and p != c:
        return True, p
    return False, None


def _dedup(values: tuple[int, ...]) -> tuple[int, ...]:
    seen: list[int] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return tuple(seen)


def _http_probe(address: str, port: int, secure: bool, timeout: float) -> dict[str, Any] | None:
    """A minimal HTTP(S) probe. Returns None if nothing is listening.

    Deliberately tiny: a bare ``GET /`` and a read of the status line and a
    couple of headers. Atlas is establishing that a *web server* answers, not
    scraping the page. No credentials are ever sent.
    """

    import http.client
    import ssl as _ssl

    try:
        if secure:
            context = _ssl._create_unverified_context()  # noqa: SLF001
            context.check_hostname = False
            context.verify_mode = _ssl.CERT_NONE
            conn = http.client.HTTPSConnection(
                address, port, timeout=timeout, context=context
            )
        else:
            conn = http.client.HTTPConnection(address, port, timeout=timeout)
        try:
            conn.request("GET", "/", headers={"User-Agent": "Atlas-Portal/1.0"})
            response = conn.getresponse()
            server = response.getheader("Server")
            # Any valid HTTP status line means a web server answered.
            return {
                "answered_http": True,
                "status": response.status,
                "server": server,
            }
        finally:
            conn.close()
    except (_ssl.SSLError,) as error:
        # A TLS endpoint that is not HTTPS still handshook — record the port
        # as a candidate, not verified.
        if secure:
            return {"answered_http": False, "status": None, "server": None}
        return None
    except (socket.timeout, ConnectionError, OSError, http.client.HTTPException):
        return None
