"""Deterministic, bounded credential candidate resolution.

Given what is safely known about a device before authentication, produce an
ordered list of credential candidates. Precedence (lockout protection —
never spray a generic credential where a targeted one exists):

1. the credential that previously worked for this device;
2. the profile's own credential — but **only first for the seed device(s)**
   the operator pointed the profile at (and, trivially, for legacy profiles
   with no credential sets);
3. scope-matching credential-set entries ordered by **match specificity**
   (explicit device id → exact host/IP or exact hostname → CIDR/hostname
   pattern → vendor/platform → site/role/profile scope), with priority
   (ascending) and then declaration order breaking ties within a class;
4. the profile's own credential, where no better-scoped match came first;
5. unrestricted "general fallback" entries last;
6. bounded to a maximum attempt count, each reference at most once.

The resolver never touches secrets — it deals purely in references. A
legacy profile without credential sets therefore resolves to exactly its
own credential, unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from .memory import CredentialSuccessMemory
from .models import CredentialSet, DeviceContext
from .repository import CredentialSetRepository


DEFAULT_MAX_ATTEMPTS = 3

# Specificity class of the profile's own credential: below every scoped
# match (0-4), above unrestricted general fallbacks (6).
PROFILE_DEFAULT_SPECIFICITY = 5

ATTEMPT_SUCCESS = "success"
ATTEMPT_AUTH_FAILED = "authentication-failed"
ATTEMPT_ERROR = "connection-error"
ATTEMPT_SKIPPED = "skipped-attempt-limit"


@dataclass(frozen=True)
class CredentialCandidate:
    """One credential to try: reference + username, never the secret."""

    credential_ref: str
    username: str
    label: str
    priority: int
    source: str  # "remembered" | "profile-default" | "<set_id>/<entry_id>"


@dataclass(frozen=True)
class CredentialAttempt:
    """Provenance of one authentication attempt. No secret values."""

    host: str
    credential_ref: str
    label: str
    outcome: str


class CredentialResolver:
    """Builds ordered, bounded candidate lists for devices."""

    def __init__(
        self,
        repository: CredentialSetRepository | None = None,
        memory: CredentialSuccessMemory | None = None,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self._repository = repository
        self._memory = memory
        self.max_attempts = max_attempts

    def candidates(
        self,
        context: DeviceContext,
        *,
        set_ids: tuple[str, ...] = (),
        profile_default: CredentialCandidate | None = None,
        default_first: bool = False,
    ) -> tuple[CredentialCandidate, ...]:
        """Ordered candidates for one device, bounded by ``max_attempts``.

        ``default_first`` places the profile's own credential immediately
        after any remembered success — used for the profile's seed devices,
        which the operator explicitly paired with that credential. For every
        other device, better-scoped entries are tried before the generic
        profile credential (specificity class 5) and unrestricted fallbacks
        come last (class 6), so a targeted credential is never preceded by
        a generic one that would burn a failed attempt.
        """

        ordered: list[CredentialCandidate] = []
        seen_refs: set[str] = set()

        def add(candidate: CredentialCandidate) -> None:
            if candidate.credential_ref not in seen_refs:
                seen_refs.add(candidate.credential_ref)
                ordered.append(candidate)

        remembered = self._remembered(context.host)
        if remembered is not None:
            add(remembered)
        if default_first and profile_default is not None:
            add(profile_default)

        ranked: list[tuple[int, int, int, CredentialCandidate]] = []
        sequence = 0
        for credential_set in self._sets(set_ids):
            for entry in credential_set.entries:
                sequence += 1
                if not entry.enabled:
                    continue
                specificity = entry.scope.match_specificity(context)
                if specificity is None:
                    continue
                ranked.append(
                    (
                        specificity,
                        entry.priority,
                        sequence,
                        CredentialCandidate(
                            credential_ref=entry.credential_ref,
                            username=entry.username,
                            label=entry.label,
                            priority=entry.priority,
                            source=f"{credential_set.set_id}/{entry.entry_id}",
                        ),
                    )
                )
        ranked.sort(key=lambda item: item[:3])
        for specificity, _priority, _sequence, candidate in ranked:
            if specificity > PROFILE_DEFAULT_SPECIFICITY and profile_default is not None:
                # Everything from here on is an unrestricted fallback: the
                # profile's own credential outranks it.
                add(profile_default)
            add(candidate)
        if profile_default is not None:
            add(profile_default)
        return tuple(ordered[: self.max_attempts])

    def enrich_context(self, context: DeviceContext) -> DeviceContext:
        """Fill unknown context attributes from memory (hostname seen before)."""

        if self._memory is None or context.hostname is not None:
            return context
        hostname = self._memory.hostname_for(context.host)
        if hostname is None:
            return context
        from dataclasses import replace

        return replace(context, hostname=hostname)

    def record_success(
        self,
        host: str,
        candidate: CredentialCandidate,
        *,
        hostname: str | None = None,
        when: str | None = None,
    ) -> None:
        if self._memory is not None:
            self._memory.record_success(
                host,
                credential_ref=candidate.credential_ref,
                username=candidate.username,
                hostname=hostname,
                when=when,
            )

    # -- internals -------------------------------------------------------

    def _remembered(self, host: str) -> CredentialCandidate | None:
        if self._memory is None:
            return None
        entry = self._memory.recall(host)
        if not entry or not entry.get("credential_ref") or not entry.get("username"):
            return None
        return CredentialCandidate(
            credential_ref=str(entry["credential_ref"]),
            username=str(entry["username"]),
            label="previously successful",
            priority=-1,
            source="remembered",
        )

    def _sets(self, set_ids: tuple[str, ...]) -> tuple[CredentialSet, ...]:
        if self._repository is None or not set_ids:
            return ()
        loaded = self._repository.load()
        return tuple(
            loaded[set_id] for set_id in set_ids if set_id in loaded
        )
