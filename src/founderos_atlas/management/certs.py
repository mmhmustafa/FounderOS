"""TLS certificate inspection for web management (PR-044B, PORTAL).

Two handshakes, deliberately:

1. A **permissive** handshake that accepts any certificate, so Atlas can read
   what a device with a self-signed cert (the norm on network gear) actually
   presented. Reading a certificate is not trusting it.
2. A **verifying** handshake against the system trust store, whose *result*
   — trusted or the specific reason it was not — is recorded.

Atlas never suppresses the browser's own TLS warning and never claims a
certificate is safe. It reports what it saw: self-signed, expired, mismatched,
untrusted, and the SHA-256 fingerprint so a change can be detected later.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
from datetime import datetime, timezone
from typing import Any

from .models import TlsCertificate


def _parse_cert_time(value: str | None) -> datetime | None:
    if not value:
        return None
    # OpenSSL notAfter format, e.g. "Jun  1 12:00:00 2027 GMT".
    try:
        return datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None


def _name_tuple_to_str(name: Any) -> str | None:
    """Flatten getpeercert()'s ((('commonName','x'),),) into a string."""

    if not name:
        return None
    parts = []
    for rdn in name:
        for key, value in rdn:
            parts.append(f"{key}={value}")
    return ", ".join(parts) if parts else None


def inspect_certificate(
    host: str,
    port: int,
    *,
    timeout: float = 3.0,
    now: datetime | None = None,
    connector=None,
) -> TlsCertificate | None:
    """Inspect the certificate at ``host:port`` without trusting it.

    Returns ``None`` if no TLS handshake could be completed at all (the port
    is not TLS, or is unreachable). Any certificate that IS presented is
    described honestly, trusted or not.

    ``connector`` is injectable for tests: ``connector(host, port, timeout,
    verify) -> (der_bytes, decoded_dict_or_None, trust_error_or_None)``.
    """

    factory = connector or _tls_connect
    # 1. Permissive: read whatever is presented.
    try:
        der, decoded, _ = factory(host, port, timeout, False)
    except Exception:  # noqa: BLE001 - not a TLS endpoint / unreachable
        return None
    if der is None:
        return None

    reference = now or datetime.now(timezone.utc)
    fingerprint = "SHA256:" + hashlib.sha256(der).hexdigest()

    subject = _name_tuple_to_str((decoded or {}).get("subject"))
    issuer = _name_tuple_to_str((decoded or {}).get("issuer"))
    sans = tuple(
        value for kind, value in (decoded or {}).get("subjectAltName", ())
        if kind in ("DNS", "IP Address")
    )
    not_before = (decoded or {}).get("notBefore")
    not_after = (decoded or {}).get("notAfter")
    version = (decoded or {}).get("version")
    serial = (decoded or {}).get("serialNumber")

    nb = _parse_cert_time(not_before)
    na = _parse_cert_time(not_after)
    expired = bool(na and reference > na)
    not_yet_valid = bool(nb and reference < nb)
    self_signed = bool(subject and issuer and subject == issuer)
    hostname_mismatch = _hostname_mismatch(host, subject, sans)

    # 2. Verifying: does the system trust store accept it?
    trusted = False
    trust_error = None
    try:
        _, _, trust_error = factory(host, port, timeout, True)
        trusted = trust_error is None
    except Exception as error:  # noqa: BLE001
        trust_error = _clean_ssl_error(error)
        trusted = False

    return TlsCertificate(
        subject=subject,
        issuer=issuer,
        sans=sans,
        not_before=not_before,
        not_after=not_after,
        fingerprint_sha256=fingerprint,
        trusted=trusted,
        trust_error=trust_error,
        self_signed=self_signed,
        expired=expired,
        not_yet_valid=not_yet_valid,
        hostname_mismatch=hostname_mismatch,
        version=version,
        serial_number=serial,
    )


def _hostname_mismatch(host: str, subject: str | None, sans: tuple[str, ...]) -> bool:
    """Whether the certificate names the address Atlas connected to.

    Conservative: with no SAN and no subject, Atlas cannot say the name
    matches, so it reports a mismatch rather than implying a match it did not
    verify. An exact appearance of the host in a SAN or the subject CN clears
    it — Atlas connects by IP, so this is an appearance check, not full
    RFC 6125 wildcard matching (which the browser will do anyway).
    """

    haystack = list(sans)
    if subject:
        haystack.append(subject)
    if not haystack:
        return True
    return not any(host == item or host in item for item in haystack)


def _clean_ssl_error(error: BaseException) -> str:
    """A short, operator-safe reason a certificate was not trusted."""

    message = str(getattr(error, "verify_message", None) or error)
    # Trim the noisy "[SSL: CERTIFICATE_VERIFY_FAILED] ... (_ssl.c:1000)" tail.
    if "certificate verify failed" in message.lower():
        reason = message.split(":")[-1].split("(")[0].strip()
        return reason or "certificate verify failed"
    return message.split("(")[0].strip()[:120]


def _tls_connect(host: str, port: int, timeout: float, verify: bool):
    """One TLS handshake. Returns (der_bytes, decoded_cert, trust_error)."""

    if verify:
        context = ssl.create_default_context()
        context.check_hostname = False  # we assess mismatch ourselves, honestly
        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=None) as tls:
                    return tls.getpeercert(binary_form=True), None, None
        except ssl.SSLError as error:
            return None, None, _clean_ssl_error(error)
    context = ssl._create_unverified_context()  # noqa: SLF001 - intentional
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=None) as tls:
            der = tls.getpeercert(binary_form=True)
            decoded = _decode_der(der)
            return der, decoded, None


def _decode_der(der: bytes | None) -> dict[str, Any] | None:
    """Decode a DER certificate into the getpeercert()-style dict.

    getpeercert() only returns a decoded dict for a *verified* peer, so for
    the permissive handshake Atlas decodes the DER itself.
    """

    if not der:
        return None
    try:
        # Python's ssl exposes this via a private helper; fall back to the
        # cryptography library only if it is present.
        import ssl as _ssl

        if hasattr(_ssl, "_ssl") and hasattr(_ssl._ssl, "_test_decode_cert"):
            import tempfile

            pem = ssl.DER_cert_to_PEM_cert(der)
            with tempfile.NamedTemporaryFile(
                "w", suffix=".pem", delete=False
            ) as handle:
                handle.write(pem)
                path = handle.name
            try:
                return _ssl._ssl._test_decode_cert(path)  # noqa: SLF001
            finally:
                import os

                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception:  # noqa: BLE001
        pass
    return _decode_with_cryptography(der)


def _decode_with_cryptography(der: bytes) -> dict[str, Any] | None:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes  # noqa: F401
    except ImportError:
        return None
    try:
        cert = x509.load_der_x509_certificate(der)
        subject = tuple(
            (("commonName" if a.oid._name == "commonName" else a.oid._name, a.value),)
            for a in cert.subject
        )
        issuer = tuple(
            (("commonName" if a.oid._name == "commonName" else a.oid._name, a.value),)
            for a in cert.issuer
        )
        sans: list[tuple[str, str]] = []
        try:
            ext = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            for name in ext.value:
                sans.append(("DNS", str(name.value)))
        except x509.ExtensionNotFound:
            pass
        return {
            "subject": subject,
            "issuer": issuer,
            "subjectAltName": tuple(sans),
            "notBefore": cert.not_valid_before_utc.strftime("%b %d %H:%M:%S %Y GMT"),
            "notAfter": cert.not_valid_after_utc.strftime("%b %d %H:%M:%S %Y GMT"),
            "version": cert.version.value,
            "serialNumber": format(cert.serial_number, "x"),
        }
    except Exception:  # noqa: BLE001
        return None
