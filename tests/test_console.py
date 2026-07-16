"""PR-044A (CONSOLE) — Universal Device SSH Access acceptance tests.

An engineer should reach a device's CLI in one click from wherever the device
appears. These tests pin the two things that must not be traded for that
convenience:

- **canonical identity** — a session may only ever be opened to an address
  Atlas *authenticated to*. A router ID, BGP peer, next hop, loopback or
  unresolved peer is a protocol fact, not a way in.
- **the secret** — the password lives in the credential store and reaches
  paramiko. It never reaches a browser, a URL, a log, or a socket frame.

Plus the rest of the spec's checklist: host-key accept/mismatch, auth
failure, timeout, disconnect, idle timeout, concurrency limit, universal
action rendering, Advisor suggestion, Copy SSH Command, FRR vtysh and Cisco
IOS interactive sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.console import (
    ACTION_AVAILABLE,
    ACTION_ENDPOINT_UNKNOWN,
    ConsoleAccessDenied,
    ConsoleAuditLog,
    ConsoleAuthenticationError,
    ConsoleHostKeyBlocked,
    ConsoleHostKeyUnknown,
    ConsoleLimitReached,
    ConsoleSession,
    ConsoleSessionManager,
    ConsoleTimeoutError,
    ConsoleTokenStore,
    HOST_KEY_CHANGED,
    HOST_KEY_KNOWN,
    HOST_KEY_NEW,
    HostKeyStore,
    fingerprint_sha256,
    find_target,
    origin_allowed,
    probe_host_key,
    require_operator,
    resolve_target,
    resolve_targets,
)

from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_profile_isolation import (
    FIXED,
    add_profile,
    full_outputs,
    make_service,
    run_discover,
    scope_dir,
)


PASSWORD = "sup3r-s3cret-pw"
SECRET_MARKER = "sup3r-s3cret-pw"


# -- fixtures ----------------------------------------------------------------


def _device(hostname="core1", management_ip="172.20.20.10", **extra):
    """A canonical device as it appears in a topology snapshot.

    It is in the snapshot because Atlas opened an authenticated session to
    ``management_ip`` and collected its identity — that is the evidence.
    """

    record = {
        "device_id": f"frr:{hostname}",
        "hostname": hostname,
        "management_ip": management_ip,
        "platform": "FRRouting",
        "vendor": "frrouting",
    }
    record.update(extra)
    return record


class _FakeKey:
    def __init__(self, blob: bytes = b"key-material", name: str = "ssh-ed25519"):
        self._blob = blob
        self._name = name

    def asbytes(self) -> bytes:
        return self._blob

    def get_name(self) -> str:
        return self._name


class _FakeChannel:
    def __init__(self, script: bytes = b"core1# "):
        self.sent: list[bytes] = []
        self._pending = bytearray(script)
        self.closed = False
        self.resized: tuple[int, int] | None = None

    def settimeout(self, value):  # noqa: ARG002
        pass

    def recv_ready(self) -> bool:
        return bool(self._pending)

    def recv(self, size: int) -> bytes:
        chunk = bytes(self._pending[:size])
        del self._pending[: len(chunk)]
        return chunk

    def exit_status_ready(self) -> bool:
        return self.closed

    def sendall(self, data: bytes) -> None:
        if self.closed:
            raise OSError("channel closed")
        self.sent.append(data)
        # Echo, like a real terminal would.
        self._pending.extend(data)

    def resize_pty(self, width, height):
        self.resized = (width, height)

    def close(self):
        self.closed = True


class _FakeClient:
    """A paramiko-shaped SSH client that never touches a network."""

    def __init__(self, *, key=None, fail=None, script=b"core1# "):
        self._key = key or _FakeKey()
        self._fail = fail
        self._script = script
        self.policy = None
        self.channel: _FakeChannel | None = None
        self.connected_with: dict | None = None
        self.closed = False

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        if self._fail is not None:
            raise self._fail
        self.connected_with = kwargs
        # Real paramiko consults the policy for an unknown host; the fake
        # always does, which is what exercises Atlas's verification.
        self.policy.missing_host_key(self, kwargs.get("hostname"), self._key)

    def invoke_shell(self, **kwargs):  # noqa: ARG002
        self.channel = _FakeChannel(self._script)
        return self.channel

    def close(self):
        self.closed = True


class _FakeTransport:
    def __init__(self, key=None):
        self._key = key or _FakeKey()
        self.closed = False

    def get_remote_server_key(self):
        return self._key

    def close(self):
        self.closed = True


def _store(tmp: str) -> HostKeyStore:
    return HostKeyStore(Path(tmp) / "known_hosts.json")


# -- canonical resolution ----------------------------------------------------


class CanonicalResolutionTests(unittest.TestCase):
    """Only an address Atlas authenticated to is a way in."""

    def test_verified_management_endpoint_is_eligible(self) -> None:
        target = resolve_target(
            _device(), network="lab", scope_id="lab",
            username="atlas", credential_ref="atlas:profile:lab",
        )
        self.assertTrue(target.eligible)
        self.assertEqual("172.20.20.10", target.management_ip)
        self.assertEqual(ACTION_AVAILABLE, target.state)
        self.assertEqual("authenticated-during-discovery", target.endpoint_evidence)

    def test_device_without_verified_endpoint_is_not_eligible(self) -> None:
        target = resolve_target(
            _device(management_ip=None), network="lab", scope_id="lab",
            username="atlas", credential_ref="ref",
        )
        self.assertFalse(target.eligible)
        self.assertEqual(ACTION_ENDPOINT_UNKNOWN, target.state)
        self.assertIn("has not verified a management endpoint", target.reason)
        self.assertIsNone(target.ssh_command)

    def test_router_id_is_never_used_as_a_management_ip(self) -> None:
        """A router ID proves an OSPF identity, not that anyone can log in."""

        device = _device(management_ip=None)
        device["router_id"] = "10.4.255.11"
        device["metadata"] = {"ospf": {"router_id": "10.4.255.11"}}
        target = resolve_target(device, network="lab", scope_id="lab")
        self.assertFalse(target.eligible)
        self.assertIsNone(target.management_ip)
        self.assertNotIn("10.4.255.11", str(target.to_dict()))

    def test_bgp_peer_address_is_never_used_as_a_management_ip(self) -> None:
        device = _device(management_ip=None)
        device["bgp_neighbors"] = [{"neighbor": "10.4.255.1", "remote_as": "65100"}]
        target = resolve_target(device, network="lab", scope_id="lab")
        self.assertFalse(target.eligible)
        self.assertIsNone(target.management_ip)
        self.assertNotIn("10.4.255.1", str(target.to_dict()))

    def test_loopback_and_interface_addresses_are_never_used(self) -> None:
        device = _device(management_ip=None)
        device["interfaces"] = [
            {"name": "lo", "ip_address": "10.4.255.11/32"},
            {"name": "eth1", "ip_address": "10.4.2.2/30"},
        ]
        target = resolve_target(device, network="lab", scope_id="lab")
        self.assertFalse(target.eligible)
        self.assertIsNone(target.management_ip)

    def test_a_non_address_is_never_accepted_as_an_endpoint(self) -> None:
        target = resolve_target(
            _device(management_ip="not-an-ip"), network="lab", scope_id="lab"
        )
        self.assertFalse(target.eligible)

    def test_unresolved_peer_resolves_to_no_target_at_all(self) -> None:
        """An unresolved peer is an observation, not a device.

        It never enters the canonical device list, so ``find_target`` cannot
        return one — and with no target, the GUI has nothing to render an SSH
        action from.
        """

        devices = [_device()]
        self.assertIsNone(
            find_target(devices, "192.0.2.50", network="lab", scope_id="lab")
        )

    def test_verified_endpoint_without_credential_is_still_eligible(self) -> None:
        """The way in is known; Atlas simply has nothing to log in with."""

        target = resolve_target(_device(), network="lab", scope_id="lab")
        self.assertTrue(target.eligible)
        self.assertEqual("credential-required", target.state)

    def test_resolve_targets_preserves_order(self) -> None:
        devices = [_device("a", "10.0.0.1"), _device("b", "10.0.0.2")]
        targets = resolve_targets(devices, network="lab", scope_id="lab")
        self.assertEqual(["a", "b"], [item.hostname for item in targets])


class CopySshCommandTests(unittest.TestCase):
    def test_command_never_contains_a_password(self) -> None:
        target = resolve_target(
            _device(), network="lab", scope_id="lab",
            username="atlas", credential_ref="ref",
        )
        self.assertEqual("ssh atlas@172.20.20.10", target.ssh_command)
        self.assertNotIn(SECRET_MARKER, target.ssh_command)

    def test_non_standard_port_is_included(self) -> None:
        target = resolve_target(
            _device(management_port=2222), network="lab", scope_id="lab",
            username="atlas", credential_ref="ref",
        )
        self.assertEqual("ssh -p 2222 atlas@172.20.20.10", target.ssh_command)

    def test_ineligible_device_offers_no_command(self) -> None:
        target = resolve_target(
            _device(management_ip=None), network="lab", scope_id="lab"
        )
        self.assertIsNone(target.ssh_command)


# -- security ----------------------------------------------------------------


class OriginTests(unittest.TestCase):
    """WebSockets bypass CORS, so Origin is the whole defence."""

    def test_the_gui_is_allowed(self) -> None:
        self.assertTrue(
            origin_allowed("http://127.0.0.1:8765", host_header="127.0.0.1:8765")
        )

    def test_another_website_is_refused(self) -> None:
        self.assertFalse(
            origin_allowed("https://evil.example", host_header="127.0.0.1:8765")
        )

    def test_a_missing_origin_is_refused(self) -> None:
        """Browsers always send Origin on a WS handshake; absence is not a
        lenient client, it is not a browser."""

        self.assertFalse(origin_allowed(None, host_header="127.0.0.1:8765"))
        self.assertFalse(origin_allowed("", host_header="127.0.0.1:8765"))

    def test_null_and_non_http_origins_are_refused(self) -> None:
        self.assertFalse(origin_allowed("null", host_header="127.0.0.1:8765"))
        self.assertFalse(
            origin_allowed("file://somewhere", host_header="127.0.0.1:8765")
        )

    def test_a_rebound_name_is_refused_unless_configured(self) -> None:
        """DNS rebinding poses as the GUI on a name the GUI does not answer
        to. The Host it was addressed to is what decides."""

        self.assertFalse(
            origin_allowed("http://attacker.test", host_header="127.0.0.1:8765")
        )
        self.assertTrue(
            origin_allowed(
                "http://atlas.internal:8765",
                host_header="127.0.0.1:8765",
                allowed_hosts=("atlas.internal:8765",),
            )
        )


class TokenTests(unittest.TestCase):
    def _clock(self, start):
        state = {"now": start}
        return state, (lambda: state["now"])

    def test_a_token_works_exactly_once(self) -> None:
        store = ConsoleTokenStore()
        token = store.mint(device_id="frr:core1", scope_id="lab", operator="op")
        store.redeem(token.token, device_id="frr:core1")
        with self.assertRaises(ConsoleAccessDenied):
            store.redeem(token.token, device_id="frr:core1")

    def test_a_token_cannot_be_replayed_at_another_device(self) -> None:
        store = ConsoleTokenStore()
        token = store.mint(device_id="frr:access1", scope_id="lab", operator="op")
        with self.assertRaises(ConsoleAccessDenied) as raised:
            store.redeem(token.token, device_id="frr:core1")
        self.assertIn("different device", str(raised.exception))

    def test_an_expired_token_is_refused(self) -> None:
        state, clock = self._clock(datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc))
        store = ConsoleTokenStore(ttl_seconds=30, clock=clock)
        token = store.mint(device_id="frr:core1", scope_id="lab", operator="op")
        state["now"] += timedelta(seconds=31)
        with self.assertRaises(ConsoleAccessDenied):
            store.redeem(token.token, device_id="frr:core1")

    def test_an_unknown_token_is_refused(self) -> None:
        with self.assertRaises(ConsoleAccessDenied):
            ConsoleTokenStore().redeem("made-up", device_id="frr:core1")

    def test_tokens_are_unguessable(self) -> None:
        store = ConsoleTokenStore()
        values = {
            store.mint(device_id="d", scope_id="s", operator="o").token
            for _ in range(50)
        }
        self.assertEqual(50, len(values))
        self.assertTrue(all(len(item) >= 32 for item in values))


class OperatorTests(unittest.TestCase):
    def test_atlas_does_not_claim_an_unauthenticated_user_is_authenticated(self) -> None:
        operator = require_operator()
        self.assertFalse(operator.authenticated)
        self.assertIn("no login yet", operator.basis)

    def test_a_real_user_is_reported_as_authenticated(self) -> None:
        """The seam a future login fills."""

        operator = require_operator(user="mustafa")
        self.assertTrue(operator.authenticated)
        self.assertEqual("mustafa", operator.name)


# -- host keys ---------------------------------------------------------------


class HostKeyTests(unittest.TestCase):
    def test_fingerprint_matches_the_openssh_shape(self) -> None:
        value = fingerprint_sha256(b"key-material")
        self.assertTrue(value.startswith("SHA256:"))
        self.assertNotIn("=", value)          # OpenSSH strips the padding

    def test_first_sight_is_new_and_needs_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verdict = _store(tmp).verify("10.0.0.1", 22, "ssh-ed25519", b"k")
            self.assertEqual(HOST_KEY_NEW, verdict.status)
            self.assertTrue(verdict.needs_acceptance)
            self.assertFalse(verdict.blocked)

    def test_accepted_key_verifies_afterwards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            first = store.verify("10.0.0.1", 22, "ssh-ed25519", b"k")
            store.accept("10.0.0.1", 22, first.key_type, first.fingerprint)
            second = store.verify("10.0.0.1", 22, "ssh-ed25519", b"k")
            self.assertEqual(HOST_KEY_KNOWN, second.status)
            self.assertFalse(second.blocked)

    def test_a_changed_key_is_blocked_and_explained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            first = store.verify("10.0.0.1", 22, "ssh-ed25519", b"original")
            store.accept("10.0.0.1", 22, first.key_type, first.fingerprint)
            verdict = store.verify("10.0.0.1", 22, "ssh-ed25519", b"different")
            self.assertEqual(HOST_KEY_CHANGED, verdict.status)
            self.assertTrue(verdict.blocked)
            self.assertIn("rebuilt, replaced, or intercepted", verdict.message)
            # Both fingerprints are shown, so the operator can compare.
            self.assertNotEqual(verdict.fingerprint, verdict.known_fingerprint)

    def test_the_same_key_on_another_port_is_a_different_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            first = store.verify("10.0.0.1", 22, "ssh-ed25519", b"k")
            store.accept("10.0.0.1", 22, first.key_type, first.fingerprint)
            self.assertEqual(
                HOST_KEY_NEW, store.verify("10.0.0.1", 2222, "ssh-ed25519", b"k").status
            )

    def test_probe_reads_a_key_without_authenticating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verdict = probe_host_key(
                "10.0.0.1", 22, _store(tmp),
                transport_factory=lambda *a: _FakeTransport(),
            )
            self.assertEqual(HOST_KEY_NEW, verdict.status)

    def test_an_override_records_what_it_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.accept("10.0.0.1", 22, "ssh-ed25519", "SHA256:aaa")
            store.accept("10.0.0.1", 22, "ssh-ed25519", "SHA256:bbb")
            entry = store.known_hosts()[0]
            self.assertEqual("SHA256:bbb", entry["fingerprint"])
            self.assertEqual("SHA256:aaa", entry["replaced_fingerprint"])


# -- sessions ----------------------------------------------------------------


class SessionTests(unittest.TestCase):
    def _session(self, tmp, *, client, allow_new=True):
        return ConsoleSession(
            host="10.0.0.1", port=22, username="atlas", password=PASSWORD,
            host_key_store=_store(tmp), allow_new_host_key=allow_new,
            client_factory=lambda: client,
        )

    def test_a_session_connects_and_carries_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _FakeClient(script=b"core1# ")
            session = self._session(tmp, client=client)
            session.connect()
            self.assertTrue(session.connected)
            self.assertEqual(b"core1# ", session.read())
            session.write(b"show version\n")
            self.assertIn(b"show version\n", client.channel.sent)

    def test_the_password_never_survives_on_the_session(self) -> None:
        """A live object must not carry the secret for a repr, a debugger,
        or a crash dump to find."""

        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(tmp, client=_FakeClient())
            session.connect()
            self.assertNotIn(SECRET_MARKER, repr(session))
            self.assertNotIn(
                SECRET_MARKER,
                " ".join(str(value) for value in vars(session).values()),
            )

    def test_repr_leaks_neither_user_nor_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(tmp, client=_FakeClient())
            self.assertNotIn(SECRET_MARKER, repr(session))
            self.assertNotIn("atlas", repr(session))

    def test_an_unknown_host_key_blocks_a_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(tmp, client=_FakeClient(), allow_new=False)
            with self.assertRaises(ConsoleHostKeyUnknown):
                session.connect()

    def test_a_changed_host_key_blocks_a_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            store.accept("10.0.0.1", 22, "ssh-ed25519", "SHA256:something-else")
            session = ConsoleSession(
                host="10.0.0.1", port=22, username="atlas", password=PASSWORD,
                host_key_store=store, allow_new_host_key=True,
                client_factory=lambda: _FakeClient(),
            )
            with self.assertRaises(ConsoleHostKeyBlocked) as raised:
                session.connect()
            self.assertTrue(raised.exception.verdict.blocked)

    def test_authentication_failure_is_operator_safe(self) -> None:
        class AuthenticationException(Exception):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(
                tmp, client=_FakeClient(fail=AuthenticationException("nope"))
            )
            with self.assertRaises(ConsoleAuthenticationError) as raised:
                session.connect()
            message = str(raised.exception)
            self.assertIn("Authentication failed", message)
            self.assertNotIn(SECRET_MARKER, message)
            self.assertNotIn("Traceback", message)

    def test_timeout_is_operator_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(tmp, client=_FakeClient(fail=TimeoutError()))
            with self.assertRaises(ConsoleTimeoutError) as raised:
                session.connect()
            self.assertIn("timed out", str(raised.exception))

    def test_a_refused_connection_explains_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = self._session(tmp, client=_FakeClient(fail=ConnectionRefusedError()))
            with self.assertRaises(Exception) as raised:
                session.connect()
            self.assertIn("refused", str(raised.exception))

    def test_disconnect_closes_the_channel_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _FakeClient()
            session = self._session(tmp, client=client)
            session.connect()
            session.close()
            self.assertFalse(session.connected)
            self.assertTrue(client.closed)
            session.close()          # must not raise

    def test_resize_is_forwarded_and_never_kills_a_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _FakeClient()
            session = self._session(tmp, client=client)
            session.connect()
            session.resize(120, 40)
            self.assertEqual((120, 40), client.channel.resized)

    def test_the_console_does_not_filter_what_the_engineer_types(self) -> None:
        """Atlas's read-only posture governs what ATLAS does on its own.

        A console is a human at a keyboard, in control. 'configure terminal'
        is theirs to type — the read-only transport would have refused it,
        and that is exactly why the console does not reuse it.
        """

        with tempfile.TemporaryDirectory() as tmp:
            client = _FakeClient()
            session = self._session(tmp, client=client)
            session.connect()
            session.write(b"configure terminal\n")
            self.assertIn(b"configure terminal\n", client.channel.sent)


class MultiPlatformTests(unittest.TestCase):
    """The console carries bytes; it does not parse platforms."""

    def _run(self, tmp, script: bytes, command: bytes) -> bytes:
        client = _FakeClient(script=script)
        session = ConsoleSession(
            host="10.0.0.1", port=22, username="atlas", password=PASSWORD,
            host_key_store=_store(tmp), allow_new_host_key=True,
            client_factory=lambda: client,
        )
        session.connect()
        banner = session.read()
        session.write(command)
        return banner

    def test_frrouting_direct_to_vtysh_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            banner = self._run(tmp, b"core1# ", b"show ip bgp summary\n")
            self.assertEqual(b"core1# ", banner)

    def test_cisco_ios_interactive_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            banner = self._run(tmp, b"R1>", b"enable\n")
            self.assertEqual(b"R1>", banner)

    def test_a_plain_linux_shell_works_the_same_way(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            banner = self._run(tmp, b"root@host:~# ", b"ip addr\n")
            self.assertEqual(b"root@host:~# ", banner)


# -- lifecycle ---------------------------------------------------------------


class _StubSession:
    def __init__(self):
        self.closed = False
        self.connected = True

    def close(self):
        self.closed = True
        self.connected = False


class SessionManagerTests(unittest.TestCase):
    def _clock(self, start=None):
        state = {"now": start or datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)}
        return state, (lambda: state["now"])

    def _manager(self, clock, **kwargs):
        return ConsoleSessionManager(clock=clock, **kwargs)

    def _register(self, manager, session=None):
        return manager.register(
            session or _StubSession(),
            device_id="frr:core1", hostname="core1",
            management_ip="10.0.0.1", port=22, username="atlas",
            credential_ref="atlas:profile:lab", operator="op",
        )

    def test_a_registered_session_is_listed(self) -> None:
        _state, clock = self._clock()
        manager = self._manager(clock)
        info = self._register(manager)
        self.assertEqual(1, manager.active_count)
        self.assertEqual("core1", info.hostname)

    def test_session_records_reference_a_credential_never_a_secret(self) -> None:
        _state, clock = self._clock()
        info = self._register(self._manager(clock))
        self.assertEqual("atlas:profile:lab", info.credential_ref)
        self.assertNotIn(SECRET_MARKER, str(info.to_dict()))

    def test_disconnect_closes_and_forgets(self) -> None:
        _state, clock = self._clock()
        manager = self._manager(clock)
        session = _StubSession()
        info = self._register(manager, session)
        manager.close(info.session_id)
        self.assertTrue(session.closed)
        self.assertEqual(0, manager.active_count)

    def test_idle_timeout_ends_an_unattended_session(self) -> None:
        state, clock = self._clock()
        manager = self._manager(clock, idle_timeout_seconds=900)
        session = _StubSession()
        self._register(manager, session)
        state["now"] += timedelta(seconds=899)
        self.assertEqual((), manager.expire_due())
        state["now"] += timedelta(seconds=2)
        ended = manager.expire_due()
        self.assertEqual(1, len(ended))
        self.assertEqual("idle timeout", ended[0].result)
        self.assertTrue(session.closed)

    def test_activity_defers_the_idle_timeout(self) -> None:
        state, clock = self._clock()
        manager = self._manager(clock, idle_timeout_seconds=900)
        info = self._register(manager)
        state["now"] += timedelta(seconds=800)
        manager.touch(info.session_id)          # a keystroke
        state["now"] += timedelta(seconds=800)
        self.assertEqual((), manager.expire_due())

    def test_maximum_duration_ends_even_a_busy_session(self) -> None:
        state, clock = self._clock()
        manager = self._manager(
            clock, idle_timeout_seconds=99999, max_duration_seconds=3600
        )
        info = self._register(manager)
        for _ in range(5):
            state["now"] += timedelta(minutes=15)
            manager.touch(info.session_id)
        ended = manager.expire_due()
        self.assertEqual(1, len(ended))
        self.assertEqual("maximum session duration reached", ended[0].result)

    def test_concurrent_session_limit_is_enforced(self) -> None:
        _state, clock = self._clock()
        manager = self._manager(clock, max_concurrent=2)
        self._register(manager)
        self._register(manager)
        with self.assertRaises(ConsoleLimitReached):
            self._register(manager)
        with self.assertRaises(ConsoleLimitReached):
            manager.check_capacity()

    def test_a_dead_channel_is_reaped(self) -> None:
        """A closed browser tab drops the socket; the SSH session it left
        must not keep holding a VTY line."""

        _state, clock = self._clock()
        manager = self._manager(clock)
        session = _StubSession()
        self._register(manager, session)
        session.connected = False
        ended = manager.expire_due()
        self.assertEqual(1, len(ended))
        self.assertEqual("device disconnected", ended[0].result)

    def test_reconnecting_must_not_stack_sessions_on_one_device(self) -> None:
        """Found by driving the live GUI, not by these tests.

        Clicking Connect twice used to open a SECOND SSH session beside the
        first, leaving the original holding a VTY line on the device. The
        client now closes any existing socket before opening a new one; this
        pins the server-side consequence — two registrations for one device
        are two real sessions, and both count against the limit.
        """

        _state, clock = self._clock()
        manager = self._manager(clock, max_concurrent=2)
        first = _StubSession()
        info = self._register(manager, first)
        self._register(manager, _StubSession())
        self.assertEqual(2, manager.active_count)
        # A stacked session is not free: it consumes the ceiling.
        with self.assertRaises(ConsoleLimitReached):
            self._register(manager)
        # Closing the abandoned one releases both the slot and the VTY line.
        manager.close(info.session_id)
        self.assertTrue(first.closed)
        self.assertEqual(1, manager.active_count)

    def test_close_all_ends_everything(self) -> None:
        _state, clock = self._clock()
        manager = self._manager(clock)
        self._register(manager)
        self._register(manager)
        self.assertEqual(2, manager.close_all())
        self.assertEqual(0, manager.active_count)


class AuditTests(unittest.TestCase):
    def test_connections_are_recorded_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = ConsoleAuditLog(Path(tmp) / "audit.jsonl")
            manager = ConsoleSessionManager(audit=audit)
            info = manager.register(
                _StubSession(), device_id="frr:core1", hostname="core1",
                management_ip="10.0.0.1", port=22, username="atlas",
                credential_ref="atlas:profile:lab", operator="op",
            )
            manager.close(info.session_id)
            entries = audit.entries()
            self.assertEqual(["connected", "disconnected"],
                             [item["event"] for item in entries])
            for entry in entries:
                self.assertEqual("atlas:profile:lab", entry["credential_ref"])
                self.assertNotIn(SECRET_MARKER, str(entry))
                # The spec is explicit: no commands, no output.
                self.assertNotIn("command", entry)
                self.assertNotIn("output", entry)

    def test_a_missing_log_reads_as_empty_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual((), ConsoleAuditLog(Path(tmp) / "none.jsonl").entries())


# -- the product, not the functions -------------------------------------------


def _network():
    r1 = full_outputs("R1", "10.0.0.1", (("SW1", "10.0.0.2"),))
    return ScriptedNetwork(
        {"10.0.0.1": r1, "10.0.0.2": full_outputs("SW1", "10.0.0.2")}
    )


class TopologyViewerActionTests(unittest.TestCase):
    """Clicking a managed node in the topology graph offers a session.

    The graph is an iframe artifact, not a Jinja page, so the universal macro
    cannot reach it — the viewer renders its own actions from the same rule.
    """

    def _viewer_source(self) -> str:
        return (
            Path(__file__).resolve().parents[1]
            / "src/founderos_atlas/visualization/templates/topology.html"
        ).read_text(encoding="utf-8")

    def test_a_managed_node_offers_the_device_actions(self) -> None:
        source = self._viewer_source()
        self.assertIn("nodeActions", source)
        self.assertIn("Open SSH Console", source)
        self.assertIn("/console/", source)
        self.assertIn("Configuration History", source)

    def test_an_unresolved_peer_is_never_offered_a_session(self) -> None:
        """`nodeDetails` returns before `nodeActions` for an observed peer.

        An unresolved peer is a routing observation — Atlas has no verified
        management endpoint for it, so the graph must not imply one.
        """

        source = self._viewer_source()
        unresolved_branch = source.split("if (unresolved) {", 1)[1].split(
            "return html;", 1
        )[0]
        self.assertNotIn("nodeActions", unresolved_branch)
        self.assertNotIn("Open SSH Console", unresolved_branch)
        self.assertIn("has not yet identified a verified management endpoint",
                      unresolved_branch)

    def test_the_standalone_artifact_carries_no_links_into_an_absent_app(self) -> None:
        """The viewer is also a file on disk. Opened directly, there is no
        Atlas around it, so it must not render links to one.

        PR-048A refined the test the viewer applies. The old check was "am I
        in an iframe?" â€” which also stripped every action the moment the
        operator clicked "Open in new tab", even though the same Atlas was
        still serving the page. The right question is "is Atlas serving me?":
        http(s) means yes, file:// means no. The principle this test protects
        is unchanged â€” a disk file gets no links â€” the detection just stopped
        conflating "own tab" with "no application".
        """

        source = self._viewer_source()
        self.assertIn("servedByAtlas", source)
        self.assertIn("window.location.protocol", source)
        self.assertIn("if (!servedByAtlas", source)
        # The old iframe test must not creep back â€” it is how "open in new
        # tab" lost its actions in the first place.
        self.assertNotIn("window.parent !== window", source)


class ConsoleGuiTests(unittest.TestCase):
    """The rendered pages, and the routes behind them."""

    def _client(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        run_discover(workdir, service, _network(), "Lab A", FIXED)
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def test_console_page_offers_discovered_devices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = self._client(Path(tmp)).get("/console")
            page = response.get_data(as_text=True)
            self.assertEqual(200, response.status_code)
            self.assertIn("R1", page)
            self.assertIn("Open SSH Console", page)

    def test_the_universal_action_renders_on_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._client(Path(tmp)).get("/topology").get_data(as_text=True)
            self.assertIn("/console/", page)
            self.assertIn("Copy SSH Command", page)

    def test_the_universal_action_renders_on_the_enterprise_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = self._client(Path(tmp)).get(
                "/topology?scope=all"
            ).get_data(as_text=True)
            self.assertIn("/console/", page)

    def test_the_universal_action_renders_on_configuration(self) -> None:
        """A device with remembered configuration can be opened from there.

        Reading yesterday's config and logging in to check today's state is
        one motion; the action belongs on that page.
        """

        with tempfile.TemporaryDirectory() as tmp:
            from founderos_atlas.web import create_app

            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1", collect_configuration=True)
            run_discover(workdir, service, _network(), "Lab A", FIXED)
            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            page = app.test_client().get("/configuration").get_data(as_text=True)
            self.assertIn("R1", page)
            self.assertIn("/console/", page)

    def test_advisor_suggests_a_console_but_never_connects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            response = client.post(
                "/advisor/ask", data={"question": "Is R1 healthy?"},
                follow_redirects=True,
            )
            page = response.get_data(as_text=True)
            self.assertIn("Devices in this answer", page)
            self.assertIn("/console/", page)
            # A suggestion is a link, not a session.
            self.assertIn("nothing connects or opens until you click", page)

    def test_advisor_never_suggests_a_device_that_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            page = client.post(
                "/advisor/ask", data={"question": "What about ghostrouter99?"},
                follow_redirects=True,
            ).get_data(as_text=True)
            self.assertNotIn("Devices in this answer", page)

    def test_no_page_ever_contains_the_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            for url in ("/console", "/console/dev:r1", "/topology", "/topology?scope=all"):
                page = client.get(url).get_data(as_text=True)
                self.assertNotIn(SECRET_MARKER, page, f"secret leaked on {url}")

    def test_a_token_request_returns_a_token_and_no_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            device_id = self._first_device_id(client)
            response = client.post(
                f"/console/{device_id}/token",
                json={},
                headers={"Origin": "http://localhost", "Host": "localhost"},
            )
            self.assertEqual(200, response.status_code)
            payload = response.get_json()
            self.assertIn("token", payload)
            self.assertNotIn(SECRET_MARKER, response.get_data(as_text=True))
            self.assertNotIn("password", payload)

    def test_a_cross_origin_token_request_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            device_id = self._first_device_id(client)
            response = client.post(
                f"/console/{device_id}/token",
                json={},
                headers={"Origin": "https://evil.example", "Host": "localhost"},
            )
            self.assertEqual(403, response.status_code)

    def test_a_token_request_without_an_origin_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            device_id = self._first_device_id(client)
            response = client.post(f"/console/{device_id}/token", json={})
            self.assertEqual(403, response.status_code)

    def test_an_unknown_device_has_no_console(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            response = client.post(
                "/console/192.0.2.50/token",
                json={},
                headers={"Origin": "http://localhost", "Host": "localhost"},
            )
            self.assertEqual(404, response.status_code)

    def test_every_page_that_renders_the_action_can_run_it(self) -> None:
        """The universal action's behaviour must be as universal as its markup.

        Found in the live GUI: the copy handler lived in atlas-console.js,
        which ONLY the terminal page loads — so Copy SSH Command was dead on
        Console, Topology, Configuration, Device details, Paths and Advisor.
        The handler now loads from base.html on every page.
        """

        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(Path(tmp))
            for url in ("/console", "/topology", "/topology?scope=all"):
                page = client.get(url).get_data(as_text=True)
                self.assertIn("js-copy-ssh", page, f"no copy button on {url}")
                self.assertIn(
                    "atlas-device-actions.js",
                    page,
                    f"copy button on {url} has no handler behind it",
                )

    def test_the_copy_handler_is_not_trapped_in_the_terminal_page_script(self) -> None:
        """Pins the regression at its root: the handler must not live in a
        script only one page loads."""

        static = Path(__file__).resolve().parents[1] / "src/founderos_atlas/web/static"
        console_js = (static / "atlas-console.js").read_text(encoding="utf-8")
        actions_js = (static / "atlas-device-actions.js").read_text(encoding="utf-8")
        self.assertNotIn("js-copy-ssh", console_js)
        self.assertIn("js-copy-ssh", actions_js)

    def test_a_failed_copy_is_never_reported_as_success(self) -> None:
        """The other half of the bug: one callback served BOTH the resolve and
        reject paths, so a refused clipboard write still said "Copied"."""

        static = Path(__file__).resolve().parents[1] / "src/founderos_atlas/web/static"
        actions_js = (static / "atlas-device-actions.js").read_text(encoding="utf-8")
        self.assertNotIn("then(done, done)", actions_js)
        # A rejection must fall back, and say so honestly if that fails too.
        self.assertIn("Press Ctrl+C", actions_js)
        self.assertIn("copyViaTextarea", actions_js)

    def test_sessions_endpoint_lists_nothing_before_any_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            response = self._client(Path(tmp)).get("/console/sessions")
            self.assertEqual(200, response.status_code)
            self.assertEqual([], response.get_json()["sessions"])

    @staticmethod
    def _first_device_id(client) -> str:
        import re

        page = client.get("/console").get_data(as_text=True)
        match = re.search(r'href="/console/([^"/]+)"', page)
        assert match, "no console link rendered"
        return match.group(1)


if __name__ == "__main__":
    unittest.main()
