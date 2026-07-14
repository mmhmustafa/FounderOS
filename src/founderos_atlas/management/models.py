"""Normalized management-service model (PR-044B, PORTAL).

Atlas already knows one management service per device: SSH, verified by the
strongest evidence there is — Atlas logged in and the device answered. This
module generalises that idea so a web management interface can be described
with the same honesty.

The distinction that matters throughout:

- **candidate** — something is listening on the port. That is *not* a web
  management interface; it is a socket that accepted a connection.
- **verified** — the port spoke HTTP(S) and answered. Because Atlas only ever
  probes the address it *authenticated to over SSH*, a web server answering
  there belongs to that canonical device by construction. What verification
  adds is that the service is a **web** service, not merely an open port.

Nothing here holds a credential. A management service is an address, a
protocol, and what Atlas can prove about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# -- protocols ---------------------------------------------------------------

PROTOCOL_HTTPS = "https"
PROTOCOL_HTTP = "http"

#: Ports Atlas will look at by default. HTTPS first — always.
DEFAULT_HTTPS_PORTS = (443, 8443, 9443)
DEFAULT_HTTP_PORTS = (80, 8080)

SERVICE_WEB_MANAGEMENT = "web-management"


# -- verification of one service --------------------------------------------

VERIFICATION_VERIFIED = "verified"
VERIFICATION_CANDIDATE = "candidate"
VERIFICATION_FAILED = "failed"
VERIFICATION_UNREACHABLE = "unreachable"
VERIFICATION_OPERATOR = "operator-defined"

#: How a service came to be known.
SOURCE_PROBE = "probe"
SOURCE_OPERATOR = "operator"

#: Evidence strings — what Atlas actually observed. Never a guess.
EVIDENCE_HTTP_RESPONSE = "http-response"
EVIDENCE_TLS_HTTP_RESPONSE = "tls-handshake+http-response"
EVIDENCE_PORT_OPEN = "tcp-port-open"
EVIDENCE_OPERATOR_DEFINED = "operator-defined"


@dataclass(frozen=True)
class TlsCertificate:
    """What the device presented, and what Atlas can say about it.

    ``trusted`` is deliberately conservative: Atlas verifies against the
    system trust store on a second, verifying handshake. A self-signed
    device certificate — the norm on network equipment — is reported as
    untrusted and self-signed, not quietly accepted.
    """

    subject: str | None = None
    issuer: str | None = None
    sans: tuple[str, ...] = ()
    not_before: str | None = None
    not_after: str | None = None
    fingerprint_sha256: str | None = None
    trusted: bool = False
    trust_error: str | None = None
    self_signed: bool = False
    expired: bool = False
    not_yet_valid: bool = False
    hostname_mismatch: bool = False
    version: int | None = None
    serial_number: str | None = None

    @property
    def warnings(self) -> tuple[str, ...]:
        """Operator-facing reasons to look twice before trusting this UI.

        Atlas never suppresses the browser's own TLS warning; these exist so
        the operator is not surprised by it, and so Atlas never implies a
        certificate is fine when it has not checked.
        """

        found: list[str] = []
        if self.expired:
            found.append("The certificate has expired.")
        if self.not_yet_valid:
            found.append("The certificate is not valid yet.")
        if self.self_signed:
            found.append(
                "The certificate is self-signed — common on network equipment, "
                "and not proof of identity."
            )
        if self.hostname_mismatch:
            found.append(
                "The certificate does not name this address, so it does not "
                "prove you are talking to this device."
            )
        if not self.trusted and not self.self_signed:
            found.append(
                "The certificate was not issued by an authority this machine "
                "trusts."
                + (f" ({self.trust_error})" if self.trust_error else "")
            )
        return tuple(found)

    @property
    def summary(self) -> str:
        if self.expired:
            return "Expired"
        if self.self_signed:
            return "Self-signed"
        if self.hostname_mismatch:
            return "Hostname mismatch"
        if self.trusted:
            return "Trusted"
        return "Untrusted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "issuer": self.issuer,
            "sans": list(self.sans),
            "not_before": self.not_before,
            "not_after": self.not_after,
            "fingerprint_sha256": self.fingerprint_sha256,
            "trusted": self.trusted,
            "trust_error": self.trust_error,
            "self_signed": self.self_signed,
            "expired": self.expired,
            "not_yet_valid": self.not_yet_valid,
            "hostname_mismatch": self.hostname_mismatch,
            "version": self.version,
            "serial_number": self.serial_number,
            "summary": self.summary,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "TlsCertificate | None":
        if not value:
            return None
        return cls(
            subject=value.get("subject"),
            issuer=value.get("issuer"),
            sans=tuple(value.get("sans") or ()),
            not_before=value.get("not_before"),
            not_after=value.get("not_after"),
            fingerprint_sha256=value.get("fingerprint_sha256"),
            trusted=bool(value.get("trusted")),
            trust_error=value.get("trust_error"),
            self_signed=bool(value.get("self_signed")),
            expired=bool(value.get("expired")),
            not_yet_valid=bool(value.get("not_yet_valid")),
            hostname_mismatch=bool(value.get("hostname_mismatch")),
            version=value.get("version"),
            serial_number=value.get("serial_number"),
        )


@dataclass(frozen=True)
class ManagementService:
    """One web management endpoint of one canonical device."""

    device_id: str
    address: str
    protocol: str                    # https | http
    port: int
    service_type: str = SERVICE_WEB_MANAGEMENT
    verification: str = VERIFICATION_CANDIDATE
    evidence: str = EVIDENCE_PORT_OPEN
    first_observed: str | None = None
    last_verified: str | None = None
    tls: TlsCertificate | None = None
    source: str = SOURCE_PROBE
    http_status: int | None = None
    server_header: str | None = None
    detail: str | None = None
    # Operator-defined endpoints carry who and why.
    defined_by: str | None = None
    defined_at: str | None = None
    reason: str | None = None

    @property
    def verified(self) -> bool:
        return self.verification in (VERIFICATION_VERIFIED, VERIFICATION_OPERATOR)

    @property
    def secure(self) -> bool:
        return self.protocol == PROTOCOL_HTTPS

    @property
    def operator_defined(self) -> bool:
        return self.source == SOURCE_OPERATOR

    @property
    def url(self) -> str:
        """The URL to open. Never carries a credential.

        The verified protocol and port are preserved exactly: a device on
        8443 is reachable at 8443, not at an assumed 443.
        """

        default = 443 if self.protocol == PROTOCOL_HTTPS else 80
        if self.port == default:
            return f"{self.protocol}://{self.address}"
        return f"{self.protocol}://{self.address}:{self.port}"

    @property
    def certificate_warnings(self) -> tuple[str, ...]:
        return self.tls.warnings if self.tls else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "address": self.address,
            "protocol": self.protocol,
            "port": self.port,
            "service_type": self.service_type,
            "verification": self.verification,
            "evidence": self.evidence,
            "first_observed": self.first_observed,
            "last_verified": self.last_verified,
            "tls": self.tls.to_dict() if self.tls else None,
            "source": self.source,
            "http_status": self.http_status,
            "server_header": self.server_header,
            "detail": self.detail,
            "defined_by": self.defined_by,
            "defined_at": self.defined_at,
            "reason": self.reason,
            "verified": self.verified,
            "secure": self.secure,
            "operator_defined": self.operator_defined,
            "url": self.url,
            "certificate_warnings": list(self.certificate_warnings),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManagementService":
        return cls(
            device_id=str(value["device_id"]),
            address=str(value["address"]),
            protocol=str(value["protocol"]),
            port=int(value["port"]),
            service_type=str(value.get("service_type") or SERVICE_WEB_MANAGEMENT),
            verification=str(value.get("verification") or VERIFICATION_CANDIDATE),
            evidence=str(value.get("evidence") or EVIDENCE_PORT_OPEN),
            first_observed=value.get("first_observed"),
            last_verified=value.get("last_verified"),
            tls=TlsCertificate.from_dict(value.get("tls")),
            source=str(value.get("source") or SOURCE_PROBE),
            http_status=value.get("http_status"),
            server_header=value.get("server_header"),
            detail=value.get("detail"),
            defined_by=value.get("defined_by"),
            defined_at=value.get("defined_at"),
            reason=value.get("reason"),
        )


# -- the action state a device is in ----------------------------------------

STATE_HTTPS_VERIFIED = "verified-https-available"
STATE_HTTP_VERIFIED = "verified-http-available"
STATE_CANDIDATE = "candidate-web-service"
STATE_VERIFICATION_FAILED = "verification-failed"
STATE_CERT_CHANGED = "certificate-changed"
STATE_CERT_EXPIRED = "certificate-expired"
STATE_ENDPOINT_UNKNOWN = "management-endpoint-unknown"
STATE_UNREACHABLE = "service-unreachable"
STATE_CUSTOM_REQUIRED = "custom-endpoint-required"
STATE_NOT_VERIFIED = "not-verified"
STATE_STALE = "verification-stale"

STATE_EXPLANATIONS = {
    STATE_HTTPS_VERIFIED: "Atlas verified an HTTPS management interface here.",
    STATE_HTTP_VERIFIED: (
        "Atlas verified an HTTP management interface here. HTTP is insecure — "
        "anything you type travels in the clear."
    ),
    STATE_CANDIDATE: (
        "A port is open but did not answer as a web interface. An open port is "
        "not a management interface."
    ),
    STATE_VERIFICATION_FAILED: "Atlas could not verify a web interface here.",
    STATE_CERT_CHANGED: (
        "The TLS certificate changed since Atlas last saw it. Review the "
        "fingerprint before trusting this interface."
    ),
    STATE_CERT_EXPIRED: "The device's TLS certificate has expired.",
    STATE_ENDPOINT_UNKNOWN: (
        "Atlas has observed this device but has not verified a management "
        "endpoint."
    ),
    STATE_UNREACHABLE: "Atlas could not reach a web service on this device.",
    STATE_CUSTOM_REQUIRED: (
        "Atlas found no web interface automatically. Define the management URL "
        "if this device has one."
    ),
    STATE_NOT_VERIFIED: "No verified HTTPS service detected.",
    STATE_STALE: "Web service verification is stale. Verify again.",
}


@dataclass(frozen=True)
class WebAccess:
    """Every web management action for one canonical device, resolved.

    This is what the universal device-action macro renders. ``https`` is
    preferred over ``http`` by construction: if a verified HTTPS service
    exists, it is the primary action and HTTP is offered only as an
    explicitly-labelled insecure alternative.
    """

    device_id: str
    hostname: str
    management_ip: str | None = None
    https: ManagementService | None = None
    http: ManagementService | None = None
    candidates: tuple[ManagementService, ...] = ()
    state: str = STATE_ENDPOINT_UNKNOWN
    reason: str = STATE_EXPLANATIONS[STATE_ENDPOINT_UNKNOWN]
    certificate_changed: bool = False
    previous_fingerprint: str | None = None
    verified_at: str | None = None

    @property
    def preferred(self) -> ManagementService | None:
        """HTTPS always wins when both are verified."""

        if self.https is not None and self.https.verified:
            return self.https
        if self.http is not None and self.http.verified:
            return self.http
        return None

    @property
    def has_https(self) -> bool:
        return self.https is not None and self.https.verified

    @property
    def has_http(self) -> bool:
        return self.http is not None and self.http.verified

    @property
    def any_web(self) -> bool:
        return self.has_https or self.has_http

    @property
    def http_only(self) -> bool:
        """True when the ONLY way in is insecure — which the UI must say."""

        return self.has_http and not self.has_https

    def to_dict(self) -> dict[str, Any]:
        preferred = self.preferred
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "management_ip": self.management_ip,
            "https": self.https.to_dict() if self.https else None,
            "http": self.http.to_dict() if self.http else None,
            "candidates": [item.to_dict() for item in self.candidates],
            "state": self.state,
            "reason": self.reason,
            "certificate_changed": self.certificate_changed,
            "previous_fingerprint": self.previous_fingerprint,
            "verified_at": self.verified_at,
            "has_https": self.has_https,
            "has_http": self.has_http,
            "any_web": self.any_web,
            "http_only": self.http_only,
            "preferred_url": preferred.url if preferred else None,
            "https_url": self.https.url if self.has_https else None,
            "http_url": self.http.url if self.has_http else None,
            "tls_summary": (
                self.https.tls.summary
                if self.https and self.https.tls
                else None
            ),
            "certificate_warnings": (
                list(self.https.certificate_warnings) if self.https else []
            ),
        }
