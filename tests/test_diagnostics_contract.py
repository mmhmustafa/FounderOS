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
# arrives by spread. (PR-180 Step 3 added the identity/state block —
# _notice, prerelease, fingerprints, last_discovery,
# failed_attempts_since_success, host_platform — as a DELIBERATE
# contract change, which is exactly the workflow this pin forces.)
EXPECTED_KEYS = frozenset({
    "_notice",
    "product",
    "version",
    "display_version",
    "prerelease",
    "build_commit",
    "workspace_schema_version",
    "workspace_schema_target",
    "workspace_fingerprint",
    "active_scope_fingerprint",
    "active_scope_kind",
    "last_discovery",
    "failed_attempts_since_success",
    "host_platform",
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

# last_discovery is built by LITERAL construction from named fields —
# never by serializing the job record — so a future DiscoveryJob field
# cannot ride into the artifact.
EXPECTED_LAST_DISCOVERY_KEYS = frozenset({
    "status",
    "finished_at",
    "profile_fingerprint",
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
        # The WHOLE artifact — including the _notice — stays clean of
        # secret-indicating substrings, so any naive scanner a support
        # contact runs over it stays quiet too.
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

    def test_notice_is_the_first_key_and_states_the_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload, raw = self._payload(Path(tmp))
            self.assertIn("no filesystem paths", payload["_notice"])
            self.assertIn("support contact you contacted first",
                          payload["_notice"])
            # jsonify sorts keys and "_" precedes every letter, so the
            # artifact opens with its own description.
            self.assertLess(raw.index('"_notice"'),
                            raw.index('"active_scope_fingerprint"'))

    def test_fingerprints_are_stable_nonreversible_and_workspace_bound(self) -> None:
        import re

        with tempfile.TemporaryDirectory() as tmp_a, \
                tempfile.TemporaryDirectory() as tmp_b:
            first, _ = self._payload(Path(tmp_a))
            second_client_payload, _ = self._payload(Path(tmp_a))
            other, _ = self._payload(Path(tmp_b))
            for key in ("workspace_fingerprint", "active_scope_fingerprint"):
                self.assertRegex(first[key], r"^[0-9a-f]{12}$", key)
                # Stable across exports from one workspace...
                self.assertEqual(first[key], second_client_payload[key], key)
            # ...and different across workspaces.
            self.assertNotEqual(first["workspace_fingerprint"],
                                other["workspace_fingerprint"])
            # The fingerprint is not the path in disguise.
            self.assertNotIn(first["workspace_fingerprint"], tmp_a)

    def test_last_discovery_is_literal_and_fingerprinted(self) -> None:
        import json as _json

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            # A persisted job history from a prior process: one success
            # then one failure, newest first after restore.
            jobs_path = workdir / "out" / ".atlas" / "jobs.json"
            jobs_path.parent.mkdir(parents=True, exist_ok=True)
            jobs_path.write_text(_json.dumps({"jobs": [
                {
                    "job_id": "aaaaaaaaaaaa", "profile_id": "hyderabad",
                    "profile_name": "Hyderabad", "management_ip": "10.0.0.1",
                    "status": "completed",
                    "completed_at": "2026-08-13T10:00:00+00:00",
                },
                {
                    "job_id": "bbbbbbbbbbbb", "profile_id": "hyderabad",
                    "profile_name": "Hyderabad", "management_ip": "10.0.0.1",
                    "status": "failed",
                    "completed_at": "2026-08-14T10:00:00+00:00",
                    "error": "Authentication failed for 10.0.0.1.",
                },
            ]}), encoding="utf-8")
            payload, raw = self._payload(workdir)
            self.assertIsNotNone(payload["last_discovery"])
            self.assertEqual(EXPECTED_LAST_DISCOVERY_KEYS,
                             set(payload["last_discovery"]))
            self.assertEqual("failed", payload["last_discovery"]["status"])
            self.assertEqual(1, payload["failed_attempts_since_success"])
            # The profile appears ONLY as a fingerprint — its id and
            # display name stay out of the artifact, as does the
            # management address the job record carries.
            self.assertRegex(payload["last_discovery"]["profile_fingerprint"],
                             r"^[0-9a-f]{12}$")
            self.assertNotIn("hyderabad", raw.lower())
            self.assertNotIn("Hyderabad", raw)
            self.assertNotIn("10.0.0.1", raw)

    def test_host_platform_is_the_pinned_expression(self) -> None:
        import platform

        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = self._payload(Path(tmp))
            self.assertEqual(
                f"{platform.system()} {platform.release()}",
                payload["host_platform"],
            )

    def test_forbidden_identity_calls_never_enter_diagnostic_sources(self) -> None:
        # §6 amendment: these four calls are forbidden by name in any
        # diagnostic surface — a hostname or login name must never be
        # computable into the artifact.
        web = Path(__file__).resolve().parents[1] / "src" / "founderos_atlas" / "web"
        for name in ("routes.py", "system_info.py"):
            body = (web / name).read_text(encoding="utf-8")
            for forbidden in ("platform.node(", "platform.uname(",
                              "socket.gethostname(", "os.getlogin("):
                self.assertNotIn(forbidden, body, f"{forbidden} in {name}")

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
