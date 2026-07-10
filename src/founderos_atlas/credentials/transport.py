"""Transport factory that tries scoped credential candidates safely.

Wraps any base ``DeviceCredentials -> DeviceTransport`` factory. For each
host it resolves an ordered, bounded candidate list and attempts them at
connect time:

- stop at the first successful authentication;
- a credential that fails authentication is never retried on that device
  in the same run;
- attempts are bounded (lockout protection) — exhausting the list raises a
  clear error instead of hammering the account;
- non-authentication failures (timeout, refused, unreachable) abort
  immediately: trying more credentials against an unreachable device only
  adds delay and noise;
- only the credential *reference* that worked is remembered; secrets are
  fetched from the secure provider per attempt and never stored on any
  model, attempt record, or log line.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from founderos_atlas.transport import (
    AtlasTransportError,
    AuthenticationError,
    DeviceCredentials,
    DeviceTransport,
    TransportNotConnectedError,
)
from founderos_atlas.workspace.exceptions import AtlasWorkspaceError

from .models import DeviceContext
from .resolver import (
    ATTEMPT_AUTH_FAILED,
    ATTEMPT_ERROR,
    ATTEMPT_SUCCESS,
    CredentialAttempt,
    CredentialCandidate,
    CredentialResolver,
)


BaseTransportFactory = Callable[[DeviceCredentials], DeviceTransport]
Clock = Callable[[], datetime]


class MultiCredentialTransportFactory:
    """A ``host -> DeviceTransport`` factory with safe credential fallback.

    Collects per-run provenance: ``attempts`` (reference + outcome, never a
    secret) and ``used_refs`` (host -> credential reference that worked).
    ``prime_neighbor`` feeds hostname/platform hints observed via discovery
    protocols into scope matching before Atlas ever connects to the device.
    """

    def __init__(
        self,
        *,
        base_factory: BaseTransportFactory,
        resolver: CredentialResolver,
        credential_provider,
        set_ids: tuple[str, ...] = (),
        profile_id: str | None = None,
        site_hint: str | None = None,
        profile_default: CredentialCandidate | None = None,
        seed_hosts: tuple[str, ...] = (),
        clock: Clock | None = None,
    ) -> None:
        self._base_factory = base_factory
        self._resolver = resolver
        self._provider = credential_provider
        self._set_ids = tuple(set_ids)
        self._profile_id = profile_id
        self._site_hint = site_hint
        self._profile_default = profile_default
        self._seed_hosts = frozenset(seed_hosts)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._hints: dict[str, dict[str, str]] = {}
        self.attempts: list[CredentialAttempt] = []
        self.used_refs: dict[str, str] = {}

    def prime_neighbor(self, neighbor) -> None:
        """Record safe context hints (hostname/platform) for a future host."""

        host = getattr(neighbor, "remote_management_ip", None)
        if not host:
            return
        hints = self._hints.setdefault(host, {})
        hostname = getattr(neighbor, "remote_hostname", None)
        if hostname and "hostname" not in hints:
            hints["hostname"] = str(hostname)
        metadata = getattr(neighbor, "metadata", None) or {}
        platform = metadata.get("platform")
        if platform and "platform" not in hints:
            hints["platform"] = str(platform)

    def __call__(self, host: str) -> DeviceTransport:
        hints = self._hints.get(host, {})
        context = DeviceContext(
            host=host,
            hostname=hints.get("hostname"),
            platform=hints.get("platform"),
            site=self._site_hint,
            profile_id=self._profile_id,
        )
        context = self._resolver.enrich_context(context)
        candidates = self._resolver.candidates(
            context,
            set_ids=self._set_ids,
            profile_default=self._profile_default,
            # The operator explicitly paired the profile credential with its
            # seed devices; everywhere else, scoped credentials go first.
            default_first=host in self._seed_hosts,
        )
        return _MultiCredentialTransport(self, host, candidates, context)

    # -- attempt bookkeeping (called by the transport) ---------------------

    def _record(self, host: str, candidate: CredentialCandidate, outcome: str) -> None:
        self.attempts.append(
            CredentialAttempt(
                host=host,
                credential_ref=candidate.credential_ref,
                label=candidate.label,
                outcome=outcome,
            )
        )

    def _record_success(
        self, host: str, candidate: CredentialCandidate, hostname: str | None
    ) -> None:
        self._record(host, candidate, ATTEMPT_SUCCESS)
        self.used_refs[host] = candidate.credential_ref
        self._resolver.record_success(
            host,
            candidate,
            hostname=hostname,
            when=self._clock().isoformat(timespec="seconds"),
        )


class _MultiCredentialTransport(DeviceTransport):
    """Tries candidates at connect; delegates the session to the winner."""

    def __init__(
        self,
        factory: MultiCredentialTransportFactory,
        host: str,
        candidates: tuple[CredentialCandidate, ...],
        context: DeviceContext,
    ) -> None:
        self._factory = factory
        self.host = host
        self._candidates = candidates
        self._context = context
        self._inner: DeviceTransport | None = None

    def connect(self) -> None:
        if not self._candidates:
            raise AuthenticationError(
                f"No credential applies to {self.host}. Add a credential set "
                "entry whose scope matches this device, or set a profile "
                "credential."
            )
        auth_failures = 0
        for candidate in self._candidates:
            try:
                password = self._factory._provider.get(candidate.credential_ref)
            except AtlasWorkspaceError:
                # A dangling reference must not abort the run; try the next.
                self._factory._record(self.host, candidate, ATTEMPT_ERROR)
                continue
            try:
                inner = self._factory._base_factory(
                    DeviceCredentials(
                        host=self.host,
                        username=candidate.username,
                        password=password,
                    )
                )
                inner.connect()
            except AuthenticationError:
                auth_failures += 1
                self._factory._record(self.host, candidate, ATTEMPT_AUTH_FAILED)
                continue
            except AtlasTransportError:
                # Unreachable/refused/timeout: more credentials cannot help.
                self._factory._record(self.host, candidate, ATTEMPT_ERROR)
                raise
            self._inner = inner
            self._factory._record_success(
                self.host, candidate, self._context.hostname
            )
            return
        raise AuthenticationError(
            f"Authentication failed for {self.host} after "
            f"{auth_failures} credential attempt(s); stopping to protect the "
            "account from lockout. Verify the credentials scoped to this device."
        )

    def disconnect(self) -> None:
        if self._inner is not None:
            self._inner.disconnect()
            self._inner = None

    def execute(self, command: str) -> str:
        if self._inner is None:
            raise TransportNotConnectedError(
                f"Not connected to {self.host}; call connect() first."
            )
        return self._inner.execute(command)
