"""Credential set management: the reusable backend for GUI and automation.

Secrets go straight into the secure credential provider; the repository
stores only entries with references. Deleting an entry deletes its secret.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from founderos_atlas.workspace.exceptions import InvalidProfileError

from .models import CredentialEntry, CredentialScope, CredentialSet, slugify
from .repository import CredentialSetRepository


Clock = Callable[[], datetime]

CREDSET_REF_PREFIX = "atlas-credset"


def entry_credential_ref(set_id: str, entry_id: str) -> str:
    return f"{CREDSET_REF_PREFIX}:{set_id}:{entry_id}"


class CredentialSetService:
    def __init__(
        self,
        repository: CredentialSetRepository,
        credential_provider,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._provider = credential_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def list_sets(self) -> tuple[CredentialSet, ...]:
        return self._repository.list()

    def add_entry(
        self,
        *,
        set_name: str,
        label: str,
        username: str,
        password: str,
        priority: int = 100,
        scope: CredentialScope | None = None,
        rotation_due_at: str | None = None,
        expires_at: str | None = None,
    ) -> CredentialSet:
        """Add one credential entry, creating its set on first use."""

        if not isinstance(set_name, str) or not set_name.strip():
            raise InvalidProfileError("A credential set name is required.")
        if not isinstance(label, str) or not label.strip():
            raise InvalidProfileError("A credential label is required.")
        if not isinstance(username, str) or not username.strip():
            raise InvalidProfileError("A username is required.")
        if not password:
            raise InvalidProfileError("A password is required.")
        set_id = slugify(set_name, "credential-set")
        existing = self._repository.get(set_id)
        taken = {entry.entry_id for entry in existing.entries} if existing else set()
        base_entry_id = slugify(label, "credential")
        entry_id, suffix = base_entry_id, 2
        while entry_id in taken:
            entry_id = f"{base_entry_id}-{suffix}"
            suffix += 1
        credential_ref = entry_credential_ref(set_id, entry_id)
        # Store the secret first; roll it back if metadata persistence fails.
        self._provider.save(credential_ref, password)
        entry = CredentialEntry(
            entry_id=entry_id,
            label=label.strip(),
            username=username.strip(),
            credential_ref=credential_ref,
            priority=priority,
            scope=scope or CredentialScope(),
            created_at=self._clock().isoformat(timespec="seconds"),
            rotation_due_at=(rotation_due_at or None),
            expires_at=(expires_at or None),
        )
        updated = CredentialSet(
            set_id=set_id,
            name=existing.name if existing else set_name.strip(),
            description=existing.description if existing else None,
            entries=(*(existing.entries if existing else ()), entry),
        )
        try:
            self._repository.save(updated)
        except Exception:
            self._provider.delete(credential_ref)
            raise
        return updated

    def delete_entry(self, set_id: str, entry_id: str) -> None:
        existing = self._repository.get(set_id)
        if existing is None:
            return
        remaining = tuple(
            entry for entry in existing.entries if entry.entry_id != entry_id
        )
        removed = tuple(
            entry for entry in existing.entries if entry.entry_id == entry_id
        )
        if remaining:
            self._repository.save(
                CredentialSet(
                    set_id=existing.set_id,
                    name=existing.name,
                    description=existing.description,
                    entries=remaining,
                )
            )
        else:
            self._repository.delete(set_id)
        for entry in removed:
            self._provider.delete(entry.credential_ref)

    def mark_success(self, set_id: str, entry_id: str) -> None:
        """Stamp last-successful-use on an entry (metadata only)."""

        existing = self._repository.get(set_id)
        if existing is None:
            return
        when = self._clock().isoformat(timespec="seconds")
        from dataclasses import replace
        entries = tuple(replace(
            entry,
            last_success=when if entry.entry_id == entry_id else entry.last_success,
            last_used=when if entry.entry_id == entry_id else entry.last_used,
            last_failure=None if entry.entry_id == entry_id else entry.last_failure,
            last_failure_reason=None if entry.entry_id == entry_id else entry.last_failure_reason,
        ) for entry in existing.entries)
        self._repository.save(
            CredentialSet(
                set_id=existing.set_id,
                name=existing.name,
                description=existing.description,
                entries=entries,
            )
        )

    def test_store_access(self, set_id: str, entry_id: str) -> bool:
        """Verify the referenced secret is readable without returning it.

        This deliberately does not claim device authentication succeeded: no
        target is required and the secret never leaves the provider boundary.
        """
        from dataclasses import replace
        existing = self._repository.get(set_id)
        if existing is None:
            raise InvalidProfileError("The credential set does not exist.")
        target = next((e for e in existing.entries if e.entry_id == entry_id), None)
        if target is None:
            raise InvalidProfileError("The credential entry does not exist.")
        when = self._clock().isoformat(timespec="seconds")
        try:
            secret = self._provider.get(target.credential_ref)
            ok = bool(secret)
        except Exception:
            ok = False
        finally:
            secret = None
        entries = tuple(replace(
            entry,
            last_used=when if entry.entry_id == entry_id else entry.last_used,
            last_test_status=("store-readable" if ok else "store-unavailable")
                if entry.entry_id == entry_id else entry.last_test_status,
            last_failure_reason=(None if ok else "Secure provider could not read the reference")
                if entry.entry_id == entry_id else entry.last_failure_reason,
            last_failure=(None if ok else when)
                if entry.entry_id == entry_id else entry.last_failure,
        ) for entry in existing.entries)
        self._repository.save(CredentialSet(
            set_id=existing.set_id, name=existing.name,
            description=existing.description, entries=entries,
        ))
        return ok
