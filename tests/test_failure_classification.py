"""Typed failure classification (PR-179 Step 1).

The defect this pins shut: Atlas raised rich, operator-safe typed
failures and the job layer flattened nearly all of them into
"Discovery failed unexpectedly". The classifier trusts an exception's
own message ONLY when its exact class is explicitly allowlisted —
inheritance grants nothing, foreign text never reaches the operator,
and internal defects finally log their traceback.
"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path


class ClassifierAllowlistTests(unittest.TestCase):
    def _classify(self, error):
        from founderos_atlas.web.failures import classify

        return classify(error, profile_name="Hyderabad",
                        management_ip="10.0.0.1")

    def test_credential_not_found_keeps_its_own_words_and_action(self) -> None:
        """The architecture's flagship case: Atlas KNEW and said nothing."""

        from founderos_atlas.workspace.exceptions import CredentialNotFoundError

        verdict = self._classify(CredentialNotFoundError(
            "No stored credential was found for this profile. "
            "Update the profile to set the password again."
        ))
        self.assertEqual("user-correctable", verdict.failure_class)
        self.assertIn("No stored credential", verdict.operator_message)
        self.assertEqual("Edit the profile", verdict.next_action_label)
        self.assertEqual("/profiles", verdict.next_action_href)
        self.assertEqual("credential-missing", verdict.diagnostic_code)
        self.assertEqual("warning", verdict.severity)

    def test_authentication_error_distinguishes_reached_but_refused(self) -> None:
        from founderos_atlas.transport.exceptions import AuthenticationError

        verdict = self._classify(AuthenticationError(
            "Authentication failed for 10.0.0.1 after 3 credential "
            "attempt(s); stopping to protect the account from lockout. "
            "Verify the credentials scoped to this device."
        ))
        self.assertEqual("user-correctable", verdict.failure_class)
        self.assertIn("protect the account from lockout",
                      verdict.operator_message)
        self.assertEqual("/credentials", verdict.next_action_href)

    def test_unreachable_is_environmental_not_internal(self) -> None:
        from founderos_atlas.transport.exceptions import (
            ConnectionLostError, ConnectionTimeoutError, SSHUnavailableError,
        )

        for error, code in (
            (SSHUnavailableError("No SSH service is reachable on 10.0.0.9:22"),
             "ssh-unavailable"),
            (ConnectionTimeoutError("10.0.0.9 did not answer a reachability "
                                    "probe on any management port"),
             "connection-timeout"),
            (ConnectionLostError("The connection to 10.0.0.9 was lost while "
                                 "running 'show version'."),
             "connection-lost"),
        ):
            verdict = self._classify(error)
            self.assertEqual("environmental", verdict.failure_class, code)
            self.assertEqual(code, verdict.diagnostic_code)
            self.assertEqual("warning", verdict.severity)
            self.assertIn("10.0.0.9", verdict.operator_message)

    def test_unsupported_platform_is_neutral_from_both_hierarchies(self) -> None:
        from founderos_atlas.platforms.registry import (
            UnsupportedPlatformError as DiscoveryUnsupported,
        )
        from founderos_atlas.transport.exceptions import (
            UnsupportedPlatformError as TransportUnsupported,
        )

        for error in (
            DiscoveryUnsupported(
                "Unsupported platform detected. Platform detected: Unknown "
                "(probe replied: 'FooOS v9'). Supported drivers: Cisco IOS."
            ),
            TransportUnsupported(
                "Unsupported device platform 'foo'. Supported platforms: "
                "cisco_ios."
            ),
        ):
            verdict = self._classify(error)
            self.assertEqual("unsupported", verdict.failure_class)
            self.assertEqual("neutral", verdict.severity,
                             "unsupported is not an Atlas fault")
            self.assertIn("upported", verdict.operator_message)

    def test_privilege_refusal_is_distinct_from_credential_rejection(self) -> None:
        from founderos_atlas.transport.exceptions import PermissionDeniedError

        verdict = self._classify(PermissionDeniedError(
            "Device 10.0.0.1 denied 'show running-config'. The account "
            "lacks the privilege required to run it."
        ))
        self.assertEqual("privilege-refused", verdict.diagnostic_code)
        self.assertIn("lacks the privilege", verdict.operator_message)

    def test_dependency_and_storage_classes(self) -> None:
        from founderos_atlas.transport.exceptions import TransportDependencyError
        from founderos_atlas.workspace.exceptions import WorkspaceCorruptedError

        dependency = self._classify(TransportDependencyError(
            "Netmiko is required for live SSH discovery. Install it with: "
            "pip install netmiko"
        ))
        self.assertEqual("transport-dependency-missing",
                         dependency.diagnostic_code)
        self.assertIn("pip install netmiko", dependency.operator_message)

        corrupted = self._classify(WorkspaceCorruptedError(
            r"The annotations file C:\Users\ops\.atlas\ws\annotations.json "
            "could not be read: Expecting value: line 1 column 1"
        ))
        self.assertEqual("storage-integrity", corrupted.failure_class)
        self.assertEqual("/system/integrity", corrupted.next_action_href)
        # Its message names filesystem paths — canonical copy only.
        self.assertNotIn("C:\\Users", corrupted.operator_message)
        self.assertNotIn("annotations.json", corrupted.operator_message)

    def test_inheritance_grants_no_trust(self) -> None:
        """A subclass — however plausible — is NOT the allowlisted class.
        Foreign wrappers must never ride in on inheritance."""

        from founderos_atlas.transport.exceptions import AuthenticationError

        class VendorAuthenticationError(AuthenticationError):
            pass

        secret = "password=SuperSecret123 leaked by a vendor library"
        verdict = self._classify(VendorAuthenticationError(secret))
        self.assertNotIn("SuperSecret123", verdict.operator_message)
        self.assertNotIn("password=", verdict.operator_message)

    def test_a_wrapper_yields_to_its_typed_cause(self) -> None:
        """The live pipeline strips types: ``raise CliError(str(error))
        from error`` (founderos_runtime/cli/commands.py) — measured on
        the pr179 world, where a seed-connect AuthenticationError
        arrived at the job layer as CliError and classified INTERNAL.
        The typed original still sits on the explicit-cause chain, and
        it is the very instance the audited raise site created — so the
        exact-type trust decision is identical there."""

        from founderos_runtime.cli.exceptions import CliError
        from founderos_atlas.transport.exceptions import AuthenticationError
        from founderos_atlas.workspace.exceptions import (
            CredentialNotFoundError,
        )

        def wrap(cause):
            try:
                try:
                    raise cause
                except type(cause) as inner:
                    raise CliError(str(inner)) from inner
            except CliError as wrapper:
                return wrapper

        auth = wrap(AuthenticationError(
            "Authentication failed for 10.0.0.1 after 1 credential "
            "attempt(s); stopping to protect the account from lockout."
        ))
        verdict = self._classify(auth)
        self.assertEqual("user-correctable", verdict.failure_class)
        self.assertEqual("authentication-failed", verdict.diagnostic_code)
        self.assertIn("protect the account from lockout",
                      verdict.operator_message)
        self.assertEqual("/credentials", verdict.next_action_href)

        # The flagship case, wrapped exactly as the live credential
        # resolution path wraps it (commands.py catches the workspace
        # error and re-raises CliError from it).
        missing = wrap(CredentialNotFoundError(
            "No stored credential was found for this profile. "
            "Update the profile to set the password again."
        ))
        verdict = self._classify(missing)
        self.assertEqual("credential-missing", verdict.diagnostic_code)
        self.assertEqual("/profiles", verdict.next_action_href)

    def test_a_wrapped_hostile_subclass_is_still_not_trusted(self) -> None:
        """The exact-type rule holds at every depth of the cause chain."""

        from founderos_runtime.cli.exceptions import CliError
        from founderos_atlas.transport.exceptions import AuthenticationError

        class VendorAuthenticationError(AuthenticationError):
            pass

        secret = "password=SuperSecret123 from a vendor library"
        try:
            try:
                raise VendorAuthenticationError(secret)
            except VendorAuthenticationError as inner:
                raise CliError("wrapped: " + str(inner)) from inner
        except CliError as wrapper:
            verdict = self._classify(wrapper)
        self.assertNotIn("SuperSecret123", verdict.operator_message)
        self.assertNotIn("password=", verdict.operator_message)

    def test_foreign_exception_text_never_reaches_the_operator(self) -> None:
        cases = [
            RuntimeError("token=abc123 at /private/path/secrets.pem"),
            KeyError("show cdp neighbors detail"),
            OSError(r"[Errno 13] Permission denied: 'C:\Users\ops\.atlas'"),
            Exception("SomeForeignException: stack detail HERE"),
        ]
        for error in cases:
            verdict = self._classify(error)
            for fragment in ("token=", "abc123", "/private/path", "Errno",
                             "SomeForeignException", "cdp", r"C:\Users"):
                self.assertNotIn(fragment, verdict.operator_message,
                                 f"{type(error).__name__} leaked {fragment}")

    def test_unknown_errors_are_internal_with_safe_copy(self) -> None:
        verdict = self._classify(KeyError("boom"))
        self.assertEqual("internal", verdict.failure_class)
        self.assertEqual("error", verdict.severity)
        self.assertEqual("internal-error", verdict.diagnostic_code)
        self.assertIn("internal error", verdict.operator_message)
        self.assertIn("preserved", verdict.operator_message)

    def test_untyped_text_still_selects_the_legacy_branches(self) -> None:
        """The pre-existing substring selector remains the fallback: a
        foreign exception whose text mentions a timeout still gets the
        canonical timeout message — not the foreign text."""

        verdict = self._classify(RuntimeError(
            "socket timed out talking to somewhere"
        ))
        self.assertEqual("environmental", verdict.failure_class)
        self.assertEqual("connection-timeout", verdict.diagnostic_code)
        self.assertNotIn("socket", verdict.operator_message)

    def test_friendly_failure_compatibility_is_untouched(self) -> None:
        from founderos_atlas.web.jobs import friendly_failure

        message, code = friendly_failure(
            "authentication failed for 10.0.0.1", "Hyderabad", "10.0.0.1"
        )
        self.assertEqual("authentication-failed", code)
        self.assertIn("Update the credentials", message)


class JobAdoptionTests(unittest.TestCase):
    """The classifier through the real DiscoveryJobManager."""

    def _manager(self, runner, tmp: Path):
        from founderos_atlas.web.jobs import DiscoveryJobManager

        class Profiles:
            def get_profile(self, name):
                class P:
                    profile_id = "hyderabad"
                    name = "Hyderabad"
                    site = None
                    management_ip = "10.0.0.1"
                return P()

        return DiscoveryJobManager(
            runner=runner, profile_service=Profiles(),
            persist_path=tmp / "jobs.json",
        )

    def _run_failing(self, error, tmp: Path):
        def runner(profile, on_line, on_connect):
            raise error

        manager = self._manager(runner, tmp)
        job, _ = manager.start("Hyderabad")
        manager.wait(job.job_id, timeout=30)
        return manager.snapshot(job), tmp / "jobs.json"

    def test_credential_not_found_end_to_end(self) -> None:
        from founderos_atlas.workspace.exceptions import CredentialNotFoundError

        with tempfile.TemporaryDirectory() as tmp:
            snap, _ = self._run_failing(CredentialNotFoundError(
                "No stored credential was found for this profile. "
                "Update the profile to set the password again."
            ), Path(tmp))
        self.assertEqual("failed", snap["status"])
        self.assertIn("No stored credential", snap["error"])
        self.assertEqual("user-correctable", snap["failure_class"])
        self.assertEqual("Edit the profile", snap["next_action_label"])
        self.assertEqual("/profiles", snap["next_action_href"])

    def test_internal_error_logs_the_traceback_and_names_the_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertLogs("atlas", level=logging.ERROR) as captured:
                snap, persisted = self._run_failing(
                    KeyError("show cdp neighbors detail"), Path(tmp)
                )
            # ...and the persisted record carries no foreign text.
            raw = persisted.read_text(encoding="utf-8")
        self.assertEqual("internal", snap["failure_class"])
        self.assertIn(f"Quote job {snap['job_id']}", snap["error"])
        joined = "\n".join(captured.output)
        self.assertIn("Traceback", joined)
        self.assertIn(snap["job_id"], joined)
        self.assertNotIn("cdp", raw)
        self.assertNotIn("KeyError", raw)

    def test_secret_bearing_foreign_error_never_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snap, persisted = self._run_failing(
                RuntimeError("password=Hunter2 token=xyz /private/key.pem"),
                Path(tmp),
            )
            raw = persisted.read_text(encoding="utf-8")
        payload = json.dumps(snap)
        for fragment in ("Hunter2", "password=", "token=", "key.pem"):
            self.assertNotIn(fragment, payload)
            self.assertNotIn(fragment, raw)

    def test_old_persisted_jobs_without_new_fields_still_load(self) -> None:
        from founderos_atlas.web.jobs import DiscoveryJobManager

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            path.write_text(json.dumps({"jobs": [{
                "job_id": "legacy123", "profile_id": "hyderabad",
                "profile_name": "Hyderabad", "management_ip": "10.0.0.1",
                "status": "failed", "stage_number": 2,
                "message": "Discovery failed",
                "error": "Discovery failed unexpectedly.",
            }]}), encoding="utf-8")

            class Profiles:
                def get_profile(self, name):
                    raise AssertionError("not needed for restore")

            manager = DiscoveryJobManager(
                runner=lambda *args: {}, profile_service=Profiles(),
                persist_path=path,
            )
            job = manager.get("legacy123")
            self.assertIsNotNone(job)
            snapshot = manager.snapshot(job)
            self.assertIsNone(snapshot["failure_class"])
            self.assertIsNone(snapshot["next_action_href"])
            self.assertEqual("failed", snapshot["status"])


if __name__ == "__main__":
    unittest.main()
