"""Identity and authorization model: permissions, roles, principals.

Authorization is a server-side property of every request. Templates may
hide controls a user cannot exercise, but hiding a button is never the
enforcement — the permission table in ``web/authz_map.py`` and the
``before_request`` gate in ``web/security.py`` are.

Permissions are deliberately small, stable strings; roles are named
bundles of permissions. A user holds roles; a request resolves to a
``Principal`` carrying the user's effective permissions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# -- Permissions -------------------------------------------------------------
# Every protected capability in the product. Adding a route means choosing
# one of these (or consciously adding a new one) in web/authz_map.py.

PAGES_VIEW = "pages.view"                # read-only pages and APIs
EVIDENCE_VIEW = "evidence.view"          # raw evidence bytes and records
DISCOVERY_RUN = "discovery.run"          # start discovery, manage jobs
PROFILES_MANAGE = "profiles.manage"      # create/edit/delete profiles
TOPOLOGY_EDIT = "topology.edit"          # site assignments, identity, sites
CREDENTIALS_MANAGE = "credentials.manage"
POLICY_MANAGE = "policy.manage"          # exceptions, ownership assignment
CHANGES_ANNOTATE = "changes.annotate"    # ack/assign/note/suppress, config notes
INVESTIGATE_RUN = "investigate.run"      # incidents, paths, advisor
PREDICT_RUN = "predict.run"
PLANS_EDIT = "plans.edit"                # compass create/extend/analyse
PLANS_APPROVE = "plans.approve"
EXPORT_DATA = "export.data"              # CSV exports, bundles, downloads
CONSOLE_USE = "console.use"              # interactive SSH console
SETTINGS_MANAGE = "settings.manage"      # preferences, backup, restore, reset
USERS_MANAGE = "users.manage"            # accounts, roles, sessions
SYSTEM_ADMIN = "system.admin"            # diagnostics, integrity, retention

ALL_PERMISSIONS = frozenset({
    PAGES_VIEW, EVIDENCE_VIEW, DISCOVERY_RUN, PROFILES_MANAGE,
    TOPOLOGY_EDIT, CREDENTIALS_MANAGE, POLICY_MANAGE, CHANGES_ANNOTATE,
    INVESTIGATE_RUN, PREDICT_RUN, PLANS_EDIT, PLANS_APPROVE, EXPORT_DATA,
    CONSOLE_USE, SETTINGS_MANAGE, USERS_MANAGE, SYSTEM_ADMIN,
})


# -- Roles -------------------------------------------------------------------

ROLE_VIEWER = "viewer"
ROLE_INVESTIGATOR = "investigator"
ROLE_NETWORK_OPERATOR = "network-operator"
ROLE_POLICY_MANAGER = "policy-manager"
ROLE_CREDENTIAL_ADMIN = "credential-admin"
ROLE_SYSTEM_ADMIN = "system-admin"
ROLE_APPROVER = "approver"

ROLE_GRANTS: dict[str, frozenset[str]] = {
    ROLE_VIEWER: frozenset({PAGES_VIEW, EVIDENCE_VIEW}),
    ROLE_INVESTIGATOR: frozenset({
        PAGES_VIEW, EVIDENCE_VIEW, INVESTIGATE_RUN, PREDICT_RUN,
        CHANGES_ANNOTATE, EXPORT_DATA,
    }),
    ROLE_NETWORK_OPERATOR: frozenset({
        PAGES_VIEW, EVIDENCE_VIEW, DISCOVERY_RUN, PROFILES_MANAGE,
        TOPOLOGY_EDIT, CONSOLE_USE, PREDICT_RUN, PLANS_EDIT, EXPORT_DATA,
    }),
    ROLE_POLICY_MANAGER: frozenset({
        PAGES_VIEW, EVIDENCE_VIEW, POLICY_MANAGE, EXPORT_DATA,
    }),
    ROLE_CREDENTIAL_ADMIN: frozenset({PAGES_VIEW, CREDENTIALS_MANAGE}),
    ROLE_SYSTEM_ADMIN: ALL_PERMISSIONS,
    ROLE_APPROVER: frozenset({PAGES_VIEW, EVIDENCE_VIEW, PLANS_APPROVE}),
}

ALL_ROLES = tuple(ROLE_GRANTS)


def permissions_for(roles) -> frozenset[str]:
    """The union of permissions granted by ``roles`` (unknown roles grant
    nothing — a misspelled role must never widen access)."""

    granted: set[str] = set()
    for role in roles:
        granted.update(ROLE_GRANTS.get(str(role), frozenset()))
    return frozenset(granted)


@dataclass(frozen=True)
class Principal:
    """The authenticated identity a request acts as."""

    username: str
    display_name: str
    roles: tuple[str, ...]
    permissions: frozenset[str] = field(default_factory=frozenset)
    session_id: str | None = None
    auth_mode: str = "local"

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    @classmethod
    def for_roles(
        cls,
        *,
        username: str,
        display_name: str | None = None,
        roles,
        session_id: str | None = None,
        auth_mode: str = "local",
    ) -> "Principal":
        role_tuple = tuple(str(role) for role in roles)
        return cls(
            username=username,
            display_name=display_name or username,
            roles=role_tuple,
            permissions=permissions_for(role_tuple),
            session_id=session_id,
            auth_mode=auth_mode,
        )


LOCAL_OPERATOR = Principal.for_roles(
    username="local-operator",
    display_name="Local operator",
    roles=(ROLE_SYSTEM_ADMIN,),
    auth_mode="local",
)
