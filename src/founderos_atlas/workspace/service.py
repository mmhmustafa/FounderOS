"""Profile service: the reusable backend for both the CLI and the future GUI.

All profile and credential business logic lives here. The CLI is a thin
adapter over these methods; PR-031's local web GUI will call the same
methods directly, with no CLI invocation and no duplicated logic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .credentials import CredentialProvider, resolve_credential_provider
from .exceptions import (
    AtlasWorkspaceError,
    CredentialStoreUnavailableError,
    DuplicateProfileError,
    InvalidProfileError,
)
from .models import (
    DiscoveryProfile,
    credential_ref_for,
    profile_id_for,
)
from .repository import ProfileRepository


Clock = Callable[[], datetime]


@dataclass(frozen=True)
class ResolvedDiscoveryInputs:
    """Everything the discovery pipeline needs, resolved from a profile."""

    profile_name: str
    management_ip: str
    username: str
    password: str
    max_depth: int
    max_devices: int
    collect_configuration: bool
    profile_id: str = ""
    # PR-033 entry-point semantics (defaults preserve legacy behavior).
    seeds: tuple[str, ...] = ()
    boundary: object | None = None  # BoundaryPolicy when configured
    credential_sets: tuple[str, ...] = ()
    site_hint: str | None = None
    credential_ref: str = ""
    # PR-044 (MEMORY): the profile's configuration collection policy. None
    # means "use the legacy collect_configuration boolean".
    collection_policy: str | None = None
    collection_schedule_hours: int = 24
    last_discovery: str | None = None


class ProfileService:
    """Create, read, update, delete profiles and resolve their credentials."""

    def __init__(
        self,
        repository: ProfileRepository | None = None,
        credential_provider: CredentialProvider | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository if repository is not None else ProfileRepository()
        self._credentials = (
            credential_provider
            if credential_provider is not None
            else resolve_credential_provider()
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def repository(self) -> ProfileRepository:
        return self._repository

    @property
    def credential_provider(self) -> CredentialProvider:
        """The secure store; exposed for multi-credential resolution."""

        return self._credentials

    # -- read ---------------------------------------------------------------

    def list_profiles(
        self, *, include_archived: bool = False
    ) -> tuple[DiscoveryProfile, ...]:
        """Discovery profiles. Archived observation points are excluded by
        default (they take no part in active discovery or enterprise
        aggregation); management views pass ``include_archived=True``."""

        profiles = self._repository.list()
        if include_archived:
            return profiles
        return tuple(profile for profile in profiles if not profile.archived)

    def get_profile(self, name: str) -> DiscoveryProfile:
        return self._repository.get(name)

    # -- create -------------------------------------------------------------

    def add_profile(
        self,
        *,
        name: str,
        management_ip: str,
        username: str,
        password: str,
        site: str | None = None,
        max_depth: int = 1,
        max_devices: int = 10,
        collect_configuration: bool = False,
        description: str | None = None,
        seeds: tuple[str, ...] = (),
        boundary=None,
        credential_sets: tuple[str, ...] = (),
        site_hint: str | None = None,
        domain_hint: str | None = None,
    ) -> DiscoveryProfile:
        if not isinstance(name, str) or not name.strip():
            raise InvalidProfileError("A profile name is required.")
        if self._repository.exists(name):
            raise DuplicateProfileError(f"A profile named {name.strip()!r} already exists.")
        # A profile needs a way in — its own credential, or a credential set.
        # Sets alone are sufficient: their entries carry their own usernames and
        # passwords, and the resolver has always accepted them without a
        # profile default. Demanding a password anyway made an operator retype
        # a credential they had already saved.
        own_credential = bool(username.strip()) and bool(password)
        if not own_credential and not credential_sets:
            raise InvalidProfileError(
                "A profile needs a way to authenticate: a username and password, "
                "or at least one credential set."
            )
        if own_credential and not password:
            raise InvalidProfileError("A password is required to save a profile.")
        profile_id = self._unique_profile_id(name)
        # No own credential -> no secret to store, and no reference to one.
        credential_ref = credential_ref_for(profile_id) if own_credential else ""
        if own_credential:
            self._ensure_credential_store()
        now = self._now()
        profile = DiscoveryProfile(
            profile_id=profile_id,
            name=name,
            management_ip=management_ip,
            username=username,
            credential_ref=credential_ref,
            site=site,
            max_depth=max_depth,
            max_devices=max_devices,
            collect_configuration=collect_configuration,
            created_at=now,
            updated_at=now,
            last_discovery=None,
            description=description,
            seeds=tuple(seeds),
            boundary=boundary,
            credential_sets=tuple(credential_sets),
            site_hint=site_hint,
            domain_hint=domain_hint,
        )
        if not own_credential:
            # Credential-set-only: there is no secret of this profile's own to
            # store, and nothing to roll back if the write fails.
            self._repository.add(profile)
            return profile
        # Store the secret first; if it fails, no dangling metadata is left.
        self._credentials.save(credential_ref, password)
        try:
            self._repository.add(profile)
        except Exception:
            self._credentials.delete(credential_ref)
            raise
        return profile

    # -- update -------------------------------------------------------------

    def update_profile(
        self,
        name: str,
        *,
        new_name: str | None = None,
        management_ip: str | None = None,
        username: str | None = None,
        password: str | None = None,
        site: str | None = None,
        clear_site: bool = False,
        max_depth: int | None = None,
        max_devices: int | None = None,
        collect_configuration: bool | None = None,
        description: str | None = None,
        seeds: tuple[str, ...] | None = None,
        boundary=None,
        clear_boundary: bool = False,
        credential_sets: tuple[str, ...] | None = None,
        site_hint: str | None = None,
        domain_hint: str | None = None,
        collection_policy: str | None = None,
        collection_schedule_hours: int | None = None,
    ) -> DiscoveryProfile:
        """Update a profile in place; ``new_name`` renames it.

        A rename keeps the stable ``profile_id`` (and therefore the stored
        credential and every piece of scoped discovery history).

        Every field not passed is PRESERVED — including ``archived`` and the
        PR-044 collection policy. An edit must never silently un-archive a
        profile or reset how it collects configuration.
        """

        existing = self._repository.get(name)
        updated = DiscoveryProfile(
            profile_id=existing.profile_id,
            name=new_name if new_name and new_name.strip() else existing.name,
            management_ip=management_ip if management_ip is not None else existing.management_ip,
            username=username if username is not None else existing.username,
            # Giving a password to a set-only profile mints its first
            # reference; it had none, so there was none to reuse.
            credential_ref=(
                existing.credential_ref
                or (credential_ref_for(existing.profile_id) if password else "")
            ),
            site=None if clear_site else (site if site is not None else existing.site),
            max_depth=max_depth if max_depth is not None else existing.max_depth,
            max_devices=max_devices if max_devices is not None else existing.max_devices,
            collect_configuration=(
                collect_configuration
                if collect_configuration is not None
                else existing.collect_configuration
            ),
            created_at=existing.created_at,
            updated_at=self._now(),
            last_discovery=existing.last_discovery,
            description=description if description is not None else existing.description,
            seeds=tuple(seeds) if seeds is not None else existing.seeds,
            boundary=(
                None if clear_boundary
                else (boundary if boundary is not None else existing.boundary)
            ),
            credential_sets=(
                tuple(credential_sets)
                if credential_sets is not None
                else existing.credential_sets
            ),
            site_hint=site_hint if site_hint is not None else existing.site_hint,
            domain_hint=domain_hint if domain_hint is not None else existing.domain_hint,
            # Preserved unless explicitly changed (see the docstring).
            archived=existing.archived,
            collection_policy=(
                collection_policy
                if collection_policy is not None
                else existing.collection_policy
            ),
            collection_schedule_hours=(
                collection_schedule_hours
                if collection_schedule_hours is not None
                else existing.collection_schedule_hours
            ),
        )
        if password:
            self._ensure_credential_store()
            # `updated` carries the reference — freshly minted when a set-only
            # profile is given its first password of its own.
            self._credentials.save(updated.credential_ref, password)
        self._repository.replace(existing.name, updated)
        return updated

    # -- archive / duplicate (PR-043.9) -------------------------------------

    def archive_profile(self, name: str, *, archived: bool = True) -> DiscoveryProfile:
        """Archive (or restore) an observation point without deleting it.

        Archiving removes the profile from active discovery and enterprise
        aggregation; the Network and Enterprise Knowledge it contributed
        to are untouched and its artifacts remain on disk."""

        existing = self._repository.get(name)
        updated = replace(existing, archived=archived, updated_at=self._now())
        self._repository.save(updated)
        return updated

    def duplicate_profile(
        self, name: str, *, new_name: str | None = None
    ) -> DiscoveryProfile:
        """Clone an observation point's discovery method and settings under
        a new identity, copying its credential.

        The clone is a NEW observation point (its own ``profile_id`` and
        scope); it observes the same estate, so Atlas will flag it as a
        duplicate-network candidate once both have discovered — never
        merging automatically (Part 3)."""

        source = self._repository.get(name)
        target_name = (new_name or f"{source.name} (copy)").strip()
        if not target_name:
            raise InvalidProfileError("A profile name is required.")
        if self._repository.exists(target_name):
            raise DuplicateProfileError(
                f"A profile named {target_name!r} already exists."
            )
        profile_id = self._unique_profile_id(target_name)
        # A set-only source has no secret of its own, so the clone gets no
        # reference to one either — a reference to a secret that was never
        # stored is worse than no reference at all.
        credential_ref = credential_ref_for(profile_id) if source.credential_ref else ""
        now = self._now()
        clone = replace(
            source,
            profile_id=profile_id,
            name=target_name,
            credential_ref=credential_ref,
            created_at=now,
            updated_at=now,
            last_discovery=None,   # the clone has not discovered yet
            archived=False,
        )
        # Copy the secret to the clone's own reference; the clone is
        # independent, so deleting either never affects the other. A set-only
        # source has no secret to copy.
        password = None
        if source.credential_ref:
            try:
                password = self._credentials.get(source.credential_ref)
            except AtlasWorkspaceError:
                password = None
        if password:
            self._ensure_credential_store()
            self._credentials.save(credential_ref, password)
        try:
            self._repository.add(clone)
        except Exception:
            if password:
                self._credentials.delete(credential_ref)
            raise
        return clone

    # -- delete -------------------------------------------------------------

    def delete_profile(self, name: str) -> DiscoveryProfile:
        """Remove only this observation profile and its credential.

        The Network and Enterprise Knowledge are derived views over the
        remaining profiles — a network still observed by another profile
        survives this deletion (PR-043.9, Part 4)."""

        removed = self._repository.delete(name)
        # A set-only profile stored no secret of its own; there is nothing to
        # delete, and asking the store to forget an empty reference is a bug,
        # not a no-op. The credential SET is untouched either way — it belongs
        # to the operator, not to this profile.
        if removed.credential_ref:
            self._credentials.delete(removed.credential_ref)
        return removed

    # -- discovery integration ---------------------------------------------

    def resolve_discovery_inputs(self, name: str) -> ResolvedDiscoveryInputs:
        profile = self._repository.get(name)
        # A profile may authenticate purely from credential sets. Then it has
        # no credential of its own and no reference to one — asking the store
        # for the secret behind an empty reference is not a lookup, it is a
        # bug. The resolver takes it from here: `profile_default` is optional,
        # and the sets carry their own usernames and passwords.
        password = (
            self._credentials.get(profile.credential_ref)
            if profile.credential_ref
            else ""
        )
        return ResolvedDiscoveryInputs(
            profile_name=profile.name,
            management_ip=profile.management_ip,
            username=profile.username,
            password=password,
            max_depth=profile.max_depth,
            max_devices=profile.max_devices,
            collect_configuration=profile.collect_configuration,
            profile_id=profile.profile_id,
            seeds=profile.seeds,
            boundary=profile.boundary,
            credential_sets=profile.credential_sets,
            site_hint=profile.site_hint or profile.site,
            credential_ref=profile.credential_ref,
            collection_policy=profile.collection_policy,
            collection_schedule_hours=profile.collection_schedule_hours,
            last_discovery=profile.last_discovery,
        )

    def record_discovery(self, name: str, when: datetime | str | None = None) -> DiscoveryProfile:
        profile = self._repository.get(name)
        timestamp = (
            when.isoformat(timespec="seconds")
            if isinstance(when, datetime)
            else (when or self._now())
        )
        updated = replace(profile, last_discovery=timestamp, updated_at=self._now())
        self._repository.save(updated)
        return updated

    # -- internals ----------------------------------------------------------

    def _unique_profile_id(self, name: str) -> str:
        """A stable, filesystem-safe id no existing profile already uses.

        Distinct names can slug to the same value ("Lab A" / "Lab-A"), and a
        renamed profile keeps its original id — so uniqueness must be checked
        against ids, not names. Deterministic: first free ``slug``/``slug-N``.
        """

        taken = {profile.profile_id for profile in self._repository.list()}
        base = profile_id_for(name)
        candidate, suffix = base, 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _ensure_credential_store(self) -> None:
        if not self._credentials.available():
            raise CredentialStoreUnavailableError(
                "No secure credential store is available. Install one with: "
                "pip install founderos-runtime[credentials]"
            )

    def _now(self) -> str:
        return self._clock().isoformat(timespec="seconds")
