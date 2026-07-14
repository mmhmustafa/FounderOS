"""PR-044B (PORTAL) — Universal Web Management Access acceptance tests.

The companion to the console. Where the console tests pin "only a verified
management endpoint, and never a credential", these pin the same for the web,
plus the honesty the web adds: a listening port is only a candidate, HTTPS is
always preferred, HTTP is always marked insecure, and a certificate is never
called safe when it was not checked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.management import (
    ManagementService,
    ManagementServiceStore,
    PROTOCOL_HTTP,
    PROTOCOL_HTTPS,
    TlsCertificate,
    VERIFICATION_CANDIDATE,
    VERIFICATION_OPERATOR,
    VERIFICATION_VERIFIED,
    WebServiceVerifier,
    detect_certificate_change,
    resolve_web_access,
)
from founderos_atlas.management.models import (
    STATE_HTTPS_VERIFIED,
    STATE_NOT_VERIFIED,
)

from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_profile_isolation import (
    FIXED,
    add_profile,
    full_outputs,
    make_service,
    run_discover,
)


SECRET = "sup3r-s3cret-pw"


def _device(hostname="core1", management_ip="172.20.20.10", **extra):
    record = {
        "device_id": f"frr:{hostname}",
        "hostname": hostname,
        "management_ip": management_ip,
        "platform": "FRRouting",
        "vendor": "frrouting",
    }
    record.update(extra)
    return record


def _verified(device_id, address, protocol, port, tls=None):
    return ManagementService(
        device_id=device_id, address=address, protocol=protocol, port=port,
        verification=VERIFICATION_VERIFIED, last_verified="2026-07-14T00:00:00+00:00",
        tls=tls,
    )


# -- resolution: only a verified endpoint, HTTPS preferred -------------------


class WebResolutionTests(unittest.TestCase):
    def test_verified_https_is_offered(self) -> None:
        access = resolve_web_access(
            _device(), network="lab", scope_id="lab",
            services=[_verified("frr:core1", "172.20.20.10", PROTOCOL_HTTPS, 443)],
        )
        self.assertTrue(access.has_https)
        self.assertEqual(STATE_HTTPS_VERIFIED, access.state)
        self.assertEqual("https://172.20.20.10", access.https.url)

    def test_https_is_preferred_over_http(self) -> None:
        access = resolve_web_access(
            _device(), network="lab", scope_id="lab",
            services=[
                _verified("frr:core1", "172.20.20.10", PROTOCOL_HTTP, 80),
                _verified("frr:core1", "172.20.20.10", PROTOCOL_HTTPS, 443),
            ],
        )
        self.assertTrue(access.has_https)
        self.assertTrue(access.has_http)
        self.assertTrue(access.preferred.secure)
        self.assertFalse(access.http_only)

    def test_http_only_is_flagged_insecure(self) -> None:
        access = resolve_web_access(
            _device(), network="lab", scope_id="lab",
            services=[_verified("frr:core1", "172.20.20.10", PROTOCOL_HTTP, 80)],
        )
        self.assertTrue(access.http_only)
        self.assertFalse(access.has_https)

    def test_custom_https_port_is_preserved_in_the_url(self) -> None:
        access = resolve_web_access(
            _device(), network="lab", scope_id="lab",
            services=[_verified("frr:core1", "172.20.20.10", PROTOCOL_HTTPS, 8443)],
        )
        self.assertEqual("https://172.20.20.10:8443", access.https.url)

    def test_a_candidate_is_never_treated_as_verified(self) -> None:
        candidate = ManagementService(
            device_id="frr:core1", address="172.20.20.10",
            protocol=PROTOCOL_HTTPS, port=443, verification=VERIFICATION_CANDIDATE,
        )
        access = resolve_web_access(
            _device(), network="lab", scope_id="lab", services=[candidate]
        )
        self.assertFalse(access.has_https)
        self.assertFalse(access.any_web)
        self.assertEqual(STATE_NOT_VERIFIED, access.state)

    # -- canonical identity: the security root -------------------------------

    def test_a_device_without_a_verified_endpoint_has_no_web_action(self) -> None:
        access = resolve_web_access(
            _device(management_ip=None), network="lab", scope_id="lab",
            services=[_verified("frr:core1", "10.4.255.11", PROTOCOL_HTTPS, 443)],
        )
        self.assertFalse(access.any_web)
        self.assertIsNone(access.management_ip)

    def test_router_id_is_not_used_as_a_web_address(self) -> None:
        """Even a 'verified' service record at a router ID is rejected —
        it is not the address Atlas authenticated to."""

        device = _device()  # management_ip = 172.20.20.10
        rogue = _verified("frr:core1", "10.4.255.11", PROTOCOL_HTTPS, 443)
        access = resolve_web_access(
            device, network="lab", scope_id="lab", services=[rogue]
        )
        self.assertFalse(access.has_https)
        self.assertNotIn("10.4.255.11", str(access.to_dict()))

    def test_bgp_peer_address_is_not_used_as_a_web_address(self) -> None:
        device = _device()
        rogue = _verified("frr:core1", "10.4.255.1", PROTOCOL_HTTPS, 443)
        access = resolve_web_access(
            device, network="lab", scope_id="lab", services=[rogue]
        )
        self.assertFalse(access.has_https)

    def test_a_service_for_another_device_is_ignored(self) -> None:
        access = resolve_web_access(
            _device(), network="lab", scope_id="lab",
            services=[_verified("frr:edge1", "172.20.20.10", PROTOCOL_HTTPS, 443)],
        )
        self.assertFalse(access.has_https)

    def test_no_credential_ever_appears_in_a_url(self) -> None:
        access = resolve_web_access(
            _device(), network="lab", scope_id="lab",
            services=[_verified("frr:core1", "172.20.20.10", PROTOCOL_HTTPS, 8443)],
        )
        url = access.https.url
        self.assertNotIn("@", url)
        self.assertNotIn(SECRET, url)
        self.assertNotIn("password", url)


# -- TLS certificate honesty -------------------------------------------------


class CertificateTests(unittest.TestCase):
    def _cert(self, **kw):
        base = dict(subject="CN=core1", issuer="CN=core1", fingerprint_sha256="SHA256:aaa")
        base.update(kw)
        return TlsCertificate(**base)

    def test_self_signed_is_reported_not_hidden(self) -> None:
        cert = self._cert(self_signed=True)
        self.assertEqual("Self-signed", cert.summary)
        self.assertTrue(any("self-signed" in w.lower() for w in cert.warnings))

    def test_expired_is_reported(self) -> None:
        cert = self._cert(expired=True, self_signed=True)
        self.assertEqual("Expired", cert.summary)
        self.assertTrue(any("expired" in w.lower() for w in cert.warnings))

    def test_hostname_mismatch_is_reported(self) -> None:
        cert = self._cert(hostname_mismatch=True, self_signed=True)
        self.assertTrue(any("does not name this address" in w for w in cert.warnings))

    def test_an_untrusted_ca_is_reported(self) -> None:
        cert = self._cert(trusted=False, self_signed=False, trust_error="unknown CA")
        self.assertTrue(any("does not trust" in w or "not issued" in w for w in cert.warnings))

    def test_a_trusted_cert_has_no_warnings(self) -> None:
        cert = self._cert(trusted=True)
        self.assertEqual((), cert.warnings)
        self.assertEqual("Trusted", cert.summary)

    def test_certificate_change_is_detected(self) -> None:
        old = _verified("d", "1.2.3.4", PROTOCOL_HTTPS, 443,
                        tls=self._cert(fingerprint_sha256="SHA256:OLD"))
        new = _verified("d", "1.2.3.4", PROTOCOL_HTTPS, 443,
                        tls=self._cert(fingerprint_sha256="SHA256:NEW"))
        changed, previous = detect_certificate_change(old, new)
        self.assertTrue(changed)
        self.assertEqual("SHA256:OLD", previous)

    def test_an_unchanged_certificate_is_not_flagged(self) -> None:
        same = _verified("d", "1.2.3.4", PROTOCOL_HTTPS, 443,
                         tls=self._cert(fingerprint_sha256="SHA256:SAME"))
        changed, _ = detect_certificate_change(same, same)
        self.assertFalse(changed)


# -- the verifier: a port is only a candidate --------------------------------


class VerifierTests(unittest.TestCase):
    def _verifier(self, responses):
        """responses keyed by (port, secure) -> probe dict or None."""

        def probe(address, port, secure, timeout):  # noqa: ARG001
            return responses.get((port, secure))

        return WebServiceVerifier(
            https_ports=(443, 8443), http_ports=(80,),
            probe=probe, certificate_inspector=lambda *a, **k: None,
            clock=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
        )

    def test_an_http_response_verifies_the_service(self) -> None:
        verifier = self._verifier({
            (443, True): {"answered_http": True, "status": 200, "server": "nginx"},
        })
        services = verifier.verify("d", "1.2.3.4")
        https = [s for s in services if s.secure]
        self.assertEqual(1, len(https))
        self.assertEqual(VERIFICATION_VERIFIED, https[0].verification)

    def test_a_port_that_does_not_speak_http_is_only_a_candidate(self) -> None:
        """A TLS handshake with no HTTP behind it is a candidate, never
        verified — an open port is not a management interface."""

        verifier = self._verifier({
            (443, True): {"answered_http": False, "status": None, "server": None},
        })
        services = verifier.verify("d", "1.2.3.4")
        self.assertEqual(1, len(services))
        self.assertEqual(VERIFICATION_CANDIDATE, services[0].verification)

    def test_nothing_listening_yields_no_service(self) -> None:
        verifier = self._verifier({})   # every probe returns None
        self.assertEqual((), verifier.verify("d", "1.2.3.4"))

    def test_https_is_verified_before_http_and_sorted_first(self) -> None:
        verifier = self._verifier({
            (443, True): {"answered_http": True, "status": 200, "server": None},
            (80, False): {"answered_http": True, "status": 200, "server": None},
        })
        services = verifier.verify("d", "1.2.3.4")
        self.assertTrue(services[0].secure)   # HTTPS sorts first

    def test_a_custom_port_is_probed_and_recorded(self) -> None:
        verifier = self._verifier({
            (8443, True): {"answered_http": True, "status": 200, "server": None},
        })
        services = verifier.verify("d", "1.2.3.4")
        self.assertEqual(8443, services[0].port)
        self.assertEqual("https://1.2.3.4:8443", services[0].url)


# -- store + operator-defined endpoints --------------------------------------


class StoreTests(unittest.TestCase):
    def test_operator_endpoint_is_stored_and_marked_as_such(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ManagementServiceStore(Path(tmp) / "svc.json")
            service = store.define_endpoint(
                "frr:core1", url="https://10.1.1.1:8443", protocol="https",
                address="10.1.1.1", port=8443, user="mustafa", reason="lab GUI",
            )
            self.assertEqual(VERIFICATION_OPERATOR, service.verification)
            self.assertTrue(service.operator_defined)
            self.assertEqual("mustafa", service.defined_by)
            self.assertEqual("lab GUI", service.reason)

    def test_operator_endpoint_is_clearly_distinct_from_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ManagementServiceStore(Path(tmp) / "svc.json")
            store.record_services(
                "frr:core1",
                (_verified("frr:core1", "172.20.20.10", PROTOCOL_HTTPS, 443),),
            )
            store.define_endpoint(
                "frr:core1", url="https://10.1.1.1:8443", protocol="https",
                address="10.1.1.1", port=8443, user="mustafa",
            )
            services = store.services_for("frr:core1")
            auto = [s for s in services if not s.operator_defined]
            manual = [s for s in services if s.operator_defined]
            self.assertEqual(1, len(auto))
            self.assertEqual(1, len(manual))

    def test_reverifying_replaces_auto_but_keeps_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ManagementServiceStore(Path(tmp) / "svc.json")
            store.define_endpoint(
                "frr:core1", url="https://10.1.1.1", protocol="https",
                address="10.1.1.1", port=443, user="op",
            )
            store.record_services(
                "frr:core1",
                (_verified("frr:core1", "172.20.20.10", PROTOCOL_HTTPS, 443),),
            )
            store.record_services("frr:core1", ())   # a later probe finds nothing
            services = store.services_for("frr:core1")
            self.assertEqual(1, len(services))
            self.assertTrue(services[0].operator_defined)

    def test_known_index_carries_first_observed_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ManagementServiceStore(Path(tmp) / "svc.json")
            store.record_services(
                "frr:core1",
                (ManagementService(
                    device_id="frr:core1", address="172.20.20.10",
                    protocol=PROTOCOL_HTTPS, port=443,
                    verification=VERIFICATION_VERIFIED,
                    first_observed="2026-07-01T00:00:00+00:00",
                ),),
            )
            index = store.known_index("frr:core1")
            self.assertIn((PROTOCOL_HTTPS, 443), index)
            self.assertEqual(
                "2026-07-01T00:00:00+00:00",
                index[(PROTOCOL_HTTPS, 443)].first_observed,
            )


# -- the rendered product ----------------------------------------------------


def _network():
    r1 = full_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),))
    return ScriptedNetwork(
        {"10.0.0.1": r1, "10.0.0.2": full_outputs("SW1", "10.0.0.2")}
    )


class ManagementGuiTests(unittest.TestCase):
    def _app(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        run_discover(workdir, service, _network(), "Lab A", FIXED)
        app = create_app(
            profile_service=service, output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app

    def _first_device_id(self, client) -> str:
        import re
        from urllib.parse import unquote

        page = client.get("/console").get_data(as_text=True)
        match = re.search(r'href="/console/([^"]+)"', page)
        assert match, "no device rendered"
        return unquote(match.group(1))

    def test_management_page_lists_devices_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(Path(tmp)).test_client()
            page = client.get("/management").get_data(as_text=True)
            self.assertEqual(200, client.get("/management").status_code)
            self.assertIn("R1", page)
            # No web service was verified, so the page says so — no dead button.
            self.assertIn("No verified HTTPS service", page)
            self.assertNotIn("Open HTTPS", page)

    def test_verified_service_renders_the_https_action(self) -> None:
        import json as _json

        from tests.test_profile_isolation import scope_dir

        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            client = app.test_client()
            device_id = self._first_device_id(client)
            # Seed a verified HTTPS service in the scope's store, as a probe
            # would — at the device's real management address.
            from founderos_atlas.management import ManagementServiceStore

            sdir = scope_dir(Path(tmp), "lab-a")
            snap = _json.loads((sdir / "topology_snapshot.json").read_text())
            device = next(d for d in snap["devices"] if d["device_id"] == device_id)
            store = ManagementServiceStore(sdir / "management-services.json")
            store.record_services(
                device_id,
                (_verified(device_id, device["management_ip"], PROTOCOL_HTTPS, 8443),),
            )
            page = client.get("/management").get_data(as_text=True)
            self.assertIn("Open HTTPS", page)
            self.assertIn(":8443", page)

    def test_define_endpoint_requires_atlas_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(Path(tmp)).test_client()
            device_id = self._first_device_id(client)
            cross = client.post(
                f"/management/{device_id}/define",
                json={"url": "https://10.1.1.1"},
                headers={"Origin": "https://evil.example", "Host": "localhost"},
            )
            self.assertEqual(403, cross.status_code)

    def test_define_endpoint_records_operator_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(Path(tmp)).test_client()
            device_id = self._first_device_id(client)
            response = client.post(
                f"/management/{device_id}/define",
                json={"url": "https://10.1.1.1:8443", "reason": "lab"},
                headers={"Origin": "http://localhost", "Host": "localhost"},
            )
            self.assertEqual(200, response.status_code)
            self.assertTrue(response.get_json()["operator_defined"])

    def test_open_is_audited_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self._app(Path(tmp))
            client = app.test_client()
            device_id = self._first_device_id(client)
            client.post(
                f"/management/{device_id}/opened",
                json={"url": "https://1.2.3.4", "protocol": "https"},
                headers={"Origin": "http://localhost", "Host": "localhost"},
            )
            from founderos_atlas.console import ConsoleAuditLog

            log = ConsoleAuditLog(Path(tmp) / ".atlas" / "console-audit.jsonl")
            events = [e["event"] for e in log.entries()]
            self.assertIn("web-management-opened", events)
            for entry in log.entries():
                self.assertNotIn(SECRET, str(entry))
                self.assertNotIn("password", entry)
                self.assertNotIn("cookie", entry)

    def test_no_page_ever_contains_a_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(Path(tmp)).test_client()
            for url in ("/management", "/topology", "/topology?scope=all"):
                self.assertNotIn(SECRET, client.get(url).get_data(as_text=True))

    def test_advisor_suggests_web_but_never_opens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._app(Path(tmp)).test_client()
            page = client.post(
                "/advisor/ask", data={"question": "Is R1 healthy?"},
                follow_redirects=True,
            ).get_data(as_text=True)
            self.assertIn("Devices in this answer", page)
            self.assertIn("nothing connects or opens until you click", page)


if __name__ == "__main__":
    unittest.main()
