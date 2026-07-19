"""The single authoritative endpoint → permission table.

``web/security.py`` consults this table on every request, before any
view runs. An endpoint that is not listed here is DENIED — adding a
route without consciously choosing its permission fails closed, and a
test asserts the table stays complete so the failure is caught at
development time, not by an operator.

``PUBLIC`` marks the few endpoints that must work without a principal:
the login page itself, liveness/readiness probes, and static assets.
"""

from __future__ import annotations

from founderos_atlas.access.models import (
    CHANGES_ANNOTATE,
    CONSOLE_USE,
    CREDENTIALS_MANAGE,
    DISCOVERY_RUN,
    EVIDENCE_VIEW,
    EXPORT_DATA,
    INVESTIGATE_RUN,
    PAGES_VIEW,
    PLANS_APPROVE,
    PLANS_EDIT,
    POLICY_MANAGE,
    PREDICT_RUN,
    PROFILES_MANAGE,
    SETTINGS_MANAGE,
    SYSTEM_ADMIN,
    TOPOLOGY_EDIT,
    USERS_MANAGE,
)

PUBLIC = "public"

ENDPOINT_PERMISSIONS: dict[str, str] = {
    # -- infrastructure ----------------------------------------------------
    "static": PUBLIC,
    "login": PUBLIC,
    "login_submit": PUBLIC,
    "logout": PUBLIC,          # needs a session to do anything, never a role
    "healthz": PUBLIC,
    "readyz": PUBLIC,

    # -- read-only pages and APIs ------------------------------------------
    "dashboard": PAGES_VIEW,
    "profiles": PAGES_VIEW,
    "profile_new": PROFILES_MANAGE,
    "profile_edit": PROFILES_MANAGE,
    "discovery": PAGES_VIEW,
    "discovery_wizard": DISCOVERY_RUN,
    "discovery_console": PAGES_VIEW,
    "api_discovery_job_get": PAGES_VIEW,
    "api_discovery_job_list": PAGES_VIEW,
    "api_discovery_execution_demo": PAGES_VIEW,
    "policy_page": PAGES_VIEW,
    "policy_result_page": PAGES_VIEW,
    "timeline_page": PAGES_VIEW,
    "audit_page": PAGES_VIEW,
    "configuration_page": PAGES_VIEW,
    "configuration_device": PAGES_VIEW,
    "topology": PAGES_VIEW,
    "api_topology_counts": PAGES_VIEW,
    "api_health": PAGES_VIEW,
    "api_topology_curation": PAGES_VIEW,
    "history": PAGES_VIEW,
    "changes": PAGES_VIEW,
    "changes_compare": PAGES_VIEW,
    "predict_page": PAGES_VIEW,
    "paths_page": PAGES_VIEW,
    "compass_page": PAGES_VIEW,
    "compass_plan_page": PAGES_VIEW,
    "advisor_page": PAGES_VIEW,
    "api_search": PAGES_VIEW,
    "device_details": PAGES_VIEW,
    "incidents": PAGES_VIEW,
    "settings": PAGES_VIEW,
    "preferences_display_level": PAGES_VIEW,
    "api_ui_preference_get": PAGES_VIEW,
    "api_ui_preference_set": PAGES_VIEW,
    "device_actions_api": PAGES_VIEW,
    "management_index": PAGES_VIEW,
    "artifacts": PAGES_VIEW,
    "inbox": PAGES_VIEW,
    "inbox_update": PAGES_VIEW,     # operators act on their own inbox

    # -- evidence ----------------------------------------------------------
    "evidence_page": EVIDENCE_VIEW,
    "evidence_device_page": EVIDENCE_VIEW,
    "evidence_record_page": EVIDENCE_VIEW,
    "memory_page": EVIDENCE_VIEW,
    "memory_session_page": EVIDENCE_VIEW,
    "memory_device_page": EVIDENCE_VIEW,
    "memory_evidence_view": EVIDENCE_VIEW,
    "evidence_saved_filter_create": EVIDENCE_VIEW,
    "evidence_saved_filter_rename": EVIDENCE_VIEW,
    "evidence_saved_filter_delete": EVIDENCE_VIEW,

    # -- exports (data leaves the system) ----------------------------------
    "evidence_record_download": EXPORT_DATA,
    "evidence_device_bundle": EXPORT_DATA,
    "evidence_session_bundle": EXPORT_DATA,
    "memory_evidence_download": EXPORT_DATA,
    "evidence_config_download": EXPORT_DATA,
    "memory_config_download": EXPORT_DATA,
    "evidence_bulk_export": EXPORT_DATA,
    "policy_export": EXPORT_DATA,
    "audit_export": EXPORT_DATA,
    "changes_export": EXPORT_DATA,
    "configuration_export_redacted": EXPORT_DATA,
    "configuration_export": EXPORT_DATA,

    # -- discovery ---------------------------------------------------------
    "discovery_wizard_draft_save": DISCOVERY_RUN,
    "discovery_wizard_draft_cancel": DISCOVERY_RUN,
    "discovery_wizard_preview": DISCOVERY_RUN,
    "discovery_wizard_start": DISCOVERY_RUN,
    "discovery_run": DISCOVERY_RUN,
    "api_discovery_job_create": DISCOVERY_RUN,
    "api_discovery_job_cancel": DISCOVERY_RUN,

    # -- profiles ----------------------------------------------------------
    "profile_create": PROFILES_MANAGE,
    "profile_update": PROFILES_MANAGE,
    "profile_delete": PROFILES_MANAGE,
    "profile_duplicate": PROFILES_MANAGE,
    "profile_archive": PROFILES_MANAGE,
    "profile_test": PROFILES_MANAGE,

    # -- credentials -------------------------------------------------------
    "credentials": CREDENTIALS_MANAGE,
    "credentials_add": CREDENTIALS_MANAGE,
    "credentials_delete": CREDENTIALS_MANAGE,
    "credentials_test": CREDENTIALS_MANAGE,
    "credentials_test_connection": CREDENTIALS_MANAGE,

    # -- policy ------------------------------------------------------------
    "policy_exception_grant": POLICY_MANAGE,
    "policy_exception_revoke": POLICY_MANAGE,
    "policy_assign": POLICY_MANAGE,

    # -- topology and identity curation ------------------------------------
    "api_assign_topology_site": TOPOLOGY_EDIT,
    "api_revert_topology_site": TOPOLOGY_EDIT,
    "api_undo_topology_site": TOPOLOGY_EDIT,
    "topology_identity_resolve": TOPOLOGY_EDIT,
    "topology_identity_revert": TOPOLOGY_EDIT,
    "topology_identity_undo": TOPOLOGY_EDIT,
    "api_resolve_peer_identity": TOPOLOGY_EDIT,
    "api_revert_peer_identity": TOPOLOGY_EDIT,
    "api_undo_peer_identity": TOPOLOGY_EDIT,
    "api_update_topology_site": TOPOLOGY_EDIT,
    "management_define": TOPOLOGY_EDIT,

    # -- annotations -------------------------------------------------------
    "changes_annotate": CHANGES_ANNOTATE,
    "configuration_annotation": CHANGES_ANNOTATE,

    # -- analysis ----------------------------------------------------------
    "predict_run": PREDICT_RUN,
    "paths_run": INVESTIGATE_RUN,
    "api_paths_trace": INVESTIGATE_RUN,
    "incidents_run": INVESTIGATE_RUN,
    "incidents_bulk": INVESTIGATE_RUN,
    "advisor_ask_route": INVESTIGATE_RUN,
    "api_advisor_ask": INVESTIGATE_RUN,

    # -- compass -----------------------------------------------------------
    "compass_new": PLANS_EDIT,
    "compass_archive": PLANS_EDIT,
    "continue_working_clear": PAGES_VIEW,
    "compass_add_change": PLANS_EDIT,
    "compass_remove_change": PLANS_EDIT,
    "compass_analyse": PLANS_EDIT,
    "compass_approve": PLANS_APPROVE,
    "compass_readiness": PLANS_EDIT,
    "compass_reorder": PLANS_EDIT,
    "compass_dependencies": PLANS_EDIT,
    "compass_submit": PLANS_EDIT,
    "compass_schedule": PLANS_EDIT,
    "compass_execution": PLANS_EDIT,
    "compass_cab_export": EXPORT_DATA,

    # -- lifecycle: incidents, advisor, paths, entity APIs ------------------
    "api_entities": PAGES_VIEW,
    "api_device_interfaces": PAGES_VIEW,
    "incident_case_page": PAGES_VIEW,
    "incident_case_action": INVESTIGATE_RUN,
    "incident_case_link": INVESTIGATE_RUN,
    "advisor_feedback": INVESTIGATE_RUN,
    "advisor_conversation_delete": INVESTIGATE_RUN,
    "advisor_conversation_rename": INVESTIGATE_RUN,
    "advisor_conversation_export": EXPORT_DATA,
    "paths_compare": PAGES_VIEW,

    # -- console -----------------------------------------------------------
    "console_index": CONSOLE_USE,
    "console_page": CONSOLE_USE,
    "console_token": CONSOLE_USE,
    "console_hostkey": CONSOLE_USE,
    "console_hostkey_accept": CONSOLE_USE,
    "console_sessions": CONSOLE_USE,
    "console_disconnect": CONSOLE_USE,
    "console_attach": CONSOLE_USE,
    "management_verify": CONSOLE_USE,
    "management_opened": CONSOLE_USE,

    # -- administration ----------------------------------------------------
    "settings_update": SETTINGS_MANAGE,
    "settings_reset": SETTINGS_MANAGE,
    "system_information": SYSTEM_ADMIN,
    "settings_diagnostics": SYSTEM_ADMIN,
    "settings_retention": SYSTEM_ADMIN,
    "settings_retention_execute": SYSTEM_ADMIN,
    "system_update": SYSTEM_ADMIN,
    "settings_backup": SYSTEM_ADMIN,
    "settings_restore": SYSTEM_ADMIN,
    "system_integrity": SYSTEM_ADMIN,
    "users_page": USERS_MANAGE,
    "users_create": USERS_MANAGE,
    "users_update": USERS_MANAGE,
    "users_delete": USERS_MANAGE,
}


def permission_for_endpoint(endpoint: str | None) -> str | None:
    """The required permission, PUBLIC, or None (=> deny) for an endpoint."""

    if endpoint is None:
        return None
    return ENDPOINT_PERMISSIONS.get(endpoint)
