"""The diagnostics export is an explicit allowlist (PR-180 Step 0).

`/settings/diagnostics.json` is an artifact that LEAVES the machine —
pasted into a chat, mailed to support, attached to a ticket. Before
PR-180 it was built from ``{**system_info, ...,
"preferences": preferences.__dict__}``: any field later added to
`collect_system_information` or `WorkspacePreferences` would silently
join a portable artifact. These tests pin the standing rule (§26.1 of
the PR-180 review): the payload is a literal dict of named keys, and it
may never carry a filesystem path, a user account name, a hostname, a
device or management address, or an operator-authored
network/site/profile name.

If you are here because the exact-key-set assertion failed: that is the
test working. Adding a diagnostic field is a deliberate contract
change — update EXPECTED_KEYS in the same commit and justify the field
against the standing rule.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tests.test_web_app import build_client, make_service

# The complete diagnostics contract. Every key deliberate; nothing
# arrives by spread.
EXPECTED_KEYS = frozenset({
    "product",
    "version",
    "display_version",
    "build_commit",
    "workspace_schema_version",
    "workspace_schema_target",
    "authentication_mode",
    "credential_provider",
    "credential_provider_available",
    "tls_enabled",
    "hsts_enabled",
    "trusted_proxy_count",
    "session_mode",
    "logging_level",
    "retention_policy",
    "update_provider",
    "python",
    "profile_count",
    "preferences",
    "generated_at",
})

EXPECTED_PREFERENCE_KEYS = frozenset({
    "timezone",
    "theme",
    "density",
    "retention_days",
    "log_level",
    "state_horizon_minutes",
})


class DiagnosticsContractTests(unittest.TestCase):
    def _payload(self, workdir: Path) -> tuple[dict, str]:
        _, client = build_client(workdir, make_service(workdir))
        response = client.get("/settings/diagnostics.json")
        self.assertEqual(200, response.status_code)
        return response.get_json(), response.get_data(as_text=True)

    def test_the_exact_key_set_is_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = self._payload(Path(tmp))
            self.assertEqual(EXPECTED_KEYS, set(payload))
            self.assertEqual(EXPECTED_PREFERENCE_KEYS,
                             set(payload["preferences"]))

    def test_no_filesystem_path_username_or_address_list_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload, raw = self._payload(Path(tmp))
            # The workspace lives inside `tmp`; not one byte of that
            # path — nor any path-shaped string — may appear.
            self.assertNotIn(tmp.replace("\\", "\\\\"), raw)
            self.assertNotIn(tmp, raw)
            for marker in ("\\\\", "AppData", "/home/", "C:\\\\Users",
                           "%TEMP%"):
                self.assertNotIn(marker, raw, marker)
            # Keys the old spread used to leak, now deliberately absent.
            for gone in ("workspace_root", "output_dir", "history_root",
                         "bind", "bind_observation", "trusted_proxies",
                         "credential_provider_class", "worker_model",
                         "worker_status", "schedule_worker_status",
                         "schedule_worker_last_tick",
                         "schedule_worker_last_error",
                         "telemetry_provider_status",
                         "telemetry_retention", "telemetry_max_facts",
                         "session_expiry"):
                self.assertNotIn(gone, payload, gone)
            # The proxy fact is a COUNT, not a list of addresses.
            self.assertIsInstance(payload["trusted_proxy_count"], int)

    def test_no_secret_material_and_no_python_class_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, raw = self._payload(Path(tmp))
            lowered = raw.lower()
            for token in ("password", "token", "private key", "secret",
                          "api_key"):
                self.assertNotIn(token, lowered, token)
            # The provider is named in operator words, never as a
            # Python class.
            self.assertNotIn("CredentialProvider", raw)

    def test_preferences_are_named_fields_not_dict_spread(self) -> None:
        # updated_at exists on WorkspacePreferences but is not support
        # context; its absence proves the sub-dict is built by name.
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = self._payload(Path(tmp))
            self.assertNotIn("updated_at", payload["preferences"])

    def test_the_export_is_still_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            self._payload(workdir)
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("export-diagnostics", audit)
            # The audit records FIELD NAMES only, never values.
            record = next(
                json.loads(line) for line in audit.splitlines()
                if "export-diagnostics" in line
            )
            self.assertIn("fields", str(record.get("after", "")))


if __name__ == "__main__":
    unittest.main()
