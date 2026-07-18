"""User accounts for production mode: scrypt-hashed passwords, revisions.

Passwords are hashed with ``hashlib.scrypt`` (stdlib; n=2**14, r=8, p=1)
and a per-user random salt. The file never holds a plaintext secret, and
the hash never leaves this module — verification happens here.

The store carries a catalog ``revision`` for optimistic concurrency and
each account carries ``updated_at``. Writes are atomic replaces guarded
by a per-store lock, matching every other Atlas workspace repository.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import uuid4

from .models import ALL_ROLES

USERS_FILENAME = "users.json"
USERS_SCHEMA_VERSION = "1.0.0"

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 32
_KEY_BYTES = 32


class UserStoreError(ValueError):
    """A user mutation was invalid (bad role, duplicate, empty password)."""


class UserConflictError(RuntimeError):
    """The caller edited an older revision of the user catalog."""


class LastAdministratorError(RuntimeError):
    """The change would leave Atlas without a usable system administrator."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    if not password or len(password) < 12:
        raise UserStoreError("Passwords must be at least 12 characters.")
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_BYTES,
    )
    return (
        f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}"
        f"${salt.hex()}${derived.hex()}"
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, derived_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(derived_hex)),
        )
        return hmac.compare_digest(derived, bytes.fromhex(derived_hex))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class UserAccount:
    username: str
    display_name: str
    roles: tuple[str, ...]
    password_hash: str | None = None      # None => SSO-only account
    disabled: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "roles": list(self.roles),
            "password_hash": self.password_hash,
            "disabled": self.disabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UserAccount":
        return cls(
            username=str(value["username"]),
            display_name=str(value.get("display_name") or value["username"]),
            roles=tuple(str(role) for role in value.get("roles") or ()),
            password_hash=value.get("password_hash"),
            disabled=bool(value.get("disabled")),
            created_at=str(value.get("created_at") or ""),
            updated_at=str(value.get("updated_at") or ""),
        )

    def public_dict(self) -> dict[str, Any]:
        """Everything except the password hash — for pages and exports."""

        data = self.to_dict()
        data.pop("password_hash", None)
        data["has_password"] = bool(self.password_hash)
        return data


_LOCKS: dict[str, RLock] = {}
_LOCKS_GUARD = RLock()


def _lock_for(path: Path) -> RLock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, RLock())


class UserStore:
    """users.json under the workspace root: accounts + catalog revision."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.path = Path(workspace_root) / USERS_FILENAME
        self._lock = _lock_for(self.path)

    # -- reading -----------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "schema_version": USERS_SCHEMA_VERSION,
                "revision": 0, "users": [],
            }
        return json.loads(self.path.read_text(encoding="utf-8"))

    def revision(self) -> int:
        return int(self._read().get("revision") or 0)

    def list(self) -> tuple[UserAccount, ...]:
        return tuple(
            UserAccount.from_dict(item)
            for item in self._read().get("users") or ()
        )

    def get(self, username: str) -> UserAccount | None:
        needle = str(username or "").strip().casefold()
        for account in self.list():
            if account.username.casefold() == needle:
                return account
        return None

    def is_empty(self) -> bool:
        return not self.list()

    # -- writing -----------------------------------------------------------

    def _write(self, users: tuple[UserAccount, ...], revision: int) -> None:
        payload = {
            "schema_version": USERS_SCHEMA_VERSION,
            "revision": revision,
            "users": [account.to_dict() for account in users],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.writing")
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _check_revision(self, expected_revision: int | None) -> int:
        current = self.revision()
        if expected_revision is not None and expected_revision != current:
            raise UserConflictError(
                "The user catalog changed while you were editing "
                f"(revision {current}, you edited {expected_revision}). "
                "Reload and reapply your change."
            )
        return current

    @staticmethod
    def _validate_roles(roles) -> tuple[str, ...]:
        cleaned = tuple(
            str(role).strip() for role in roles if str(role or "").strip()
        )
        unknown = [role for role in cleaned if role not in ALL_ROLES]
        if unknown:
            raise UserStoreError(f"Unknown role(s): {', '.join(unknown)}.")
        if not cleaned:
            raise UserStoreError("An account needs at least one role.")
        return cleaned

    def _is_usable_admin(self, account: UserAccount, *,
                         allow_sso: bool) -> bool:
        """An account that can actually administer Atlas right now:
        enabled, holding system-admin, and able to sign in (a password,
        or SSO when the deployment authenticates at a proxy)."""

        from .models import ROLE_SYSTEM_ADMIN

        return (
            not account.disabled
            and ROLE_SYSTEM_ADMIN in account.roles
            and (bool(account.password_hash) or allow_sso)
        )

    def usable_admin_count(
        self, *, allow_sso: bool = False, excluding: str | None = None,
    ) -> int:
        needle = (excluding or "").casefold()
        return sum(
            1 for account in self.list()
            if account.username.casefold() != needle
            and self._is_usable_admin(account, allow_sso=allow_sso)
        )

    def _guard_last_admin(
        self, before: UserAccount, after, *, allow_sso: bool,
    ) -> None:
        """Refuse any change that converts the LAST usable administrator
        into a non-administrator, a disabled account, or nothing."""

        if not self._is_usable_admin(before, allow_sso=allow_sso):
            return
        if after is not None and self._is_usable_admin(
            after, allow_sso=allow_sso
        ):
            return
        if self.usable_admin_count(
            allow_sso=allow_sso, excluding=before.username
        ) == 0:
            raise LastAdministratorError(
                "This change would leave Atlas without a usable system "
                "administrator. Grant system-admin to another enabled "
                "account first."
            )

    def create(
        self,
        *,
        username: str,
        display_name: str | None = None,
        roles,
        password: str | None = None,
        expected_revision: int | None = None,
    ) -> UserAccount:
        name = str(username or "").strip()
        if not name or not name.replace("-", "").replace(".", "").isalnum():
            raise UserStoreError(
                "Usernames use letters, digits, dots, and dashes."
            )
        with self._lock:
            current = self._check_revision(expected_revision)
            if self.get(name) is not None:
                raise UserStoreError(f"The account {name!r} already exists.")
            stamp = _now()
            account = UserAccount(
                username=name,
                display_name=(display_name or name).strip(),
                roles=self._validate_roles(roles),
                password_hash=hash_password(password) if password else None,
                created_at=stamp, updated_at=stamp,
            )
            self._write((*self.list(), account), current + 1)
            return account

    def update(
        self,
        username: str,
        *,
        display_name: str | None = None,
        roles=None,
        password: str | None = None,
        disabled: bool | None = None,
        expected_revision: int | None = None,
        allow_sso_admins: bool = False,
    ) -> UserAccount:
        with self._lock:
            current = self._check_revision(expected_revision)
            existing = self.get(username)
            if existing is None:
                raise UserStoreError(f"No account named {username!r} exists.")
            updated = replace(
                existing,
                display_name=(
                    display_name.strip() if display_name is not None
                    else existing.display_name
                ),
                roles=(
                    self._validate_roles(roles) if roles is not None
                    else existing.roles
                ),
                password_hash=(
                    hash_password(password) if password
                    else existing.password_hash
                ),
                disabled=disabled if disabled is not None else existing.disabled,
                updated_at=_now(),
            )
            self._guard_last_admin(
                existing, updated, allow_sso=allow_sso_admins
            )
            users = tuple(
                updated if account.username == existing.username else account
                for account in self.list()
            )
            self._write(users, current + 1)
            return updated

    def delete(
        self, username: str, *, expected_revision: int | None = None,
        allow_sso_admins: bool = False,
    ) -> bool:
        with self._lock:
            current = self._check_revision(expected_revision)
            existing = self.get(username)
            if existing is not None:
                self._guard_last_admin(
                    existing, None, allow_sso=allow_sso_admins
                )
            users = self.list()
            remaining = tuple(
                account for account in users
                if account.username.casefold() != str(username).casefold()
            )
            if len(remaining) == len(users):
                return False
            self._write(remaining, current + 1)
            return True

    # -- authentication ----------------------------------------------------

    def authenticate(self, username: str, password: str) -> UserAccount | None:
        """The account, or None. Verification always runs a hash so timing
        does not reveal whether the username exists."""

        account = self.get(username)
        stored = account.password_hash if account else None
        ok = verify_password(
            password or "",
            stored or hash_password("invalid-placeholder-password"),
        )
        if account is None or account.disabled or not stored or not ok:
            return None
        return account


def ensure_recovery_admin(workspace_root) -> str | None:
    """Emergency lockout recovery, driven by environment variables.

    When ``ATLAS_RECOVERY_ADMIN_USER`` and
    ``ATLAS_RECOVERY_ADMIN_PASSWORD`` are both set at startup, the named
    account is created (or reset) as an ENABLED system administrator
    with that password. The password is hashed immediately and never
    stored in clear; the caller audits the event. Operators should set
    the variables, restart, sign in, repair the accounts, then unset
    them — anyone who can set this process's environment already owns
    the host, so this restores access without adding a trust boundary.

    Returns the username when a recovery was applied, else ``None``.
    """

    import os

    from .models import ROLE_SYSTEM_ADMIN

    username = os.environ.get("ATLAS_RECOVERY_ADMIN_USER", "").strip()
    password = os.environ.get("ATLAS_RECOVERY_ADMIN_PASSWORD", "")
    if not username or not password:
        return None
    store = UserStore(workspace_root)
    if store.get(username) is None:
        store.create(
            username=username, roles=(ROLE_SYSTEM_ADMIN,), password=password,
        )
    else:
        store.update(
            username, roles=(ROLE_SYSTEM_ADMIN,), password=password,
            disabled=False,
        )
    return username
