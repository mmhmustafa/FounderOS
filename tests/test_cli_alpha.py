"""Acceptance tests for the presentation-only FounderOS v0.3 Alpha CLI."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import socket
import unittest
from unittest.mock import patch
import urllib.request

from founderos_runtime.cli import main
from founderos_runtime.cli.render import render_discovery
from founderos_runtime.demo import discovery_example_root, run_discovery_vertical_slice

from tests.helpers import RuntimeFixture


class FounderOSAlphaCliTests(unittest.TestCase):
    def invoke(self, *arguments: str, runner=run_discovery_vertical_slice):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(arguments), discovery_runner=runner)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_version_command(self) -> None:
        code, output, error = self.invoke("version")
        self.assertEqual(0, code)
        self.assertEqual("FounderOS v0.3 Alpha\n", output)
        self.assertEqual("", error)

    def test_help_command(self) -> None:
        code, output, error = self.invoke("help")
        self.assertEqual(0, code)
        self.assertIn("founderos demo discovery", output)
        self.assertIn("founderos atlas demo topology", output)
        self.assertIn("founderos atlas morning-brief", output)
        self.assertIn("founderos doctor", output)
        self.assertEqual("", error)

    def test_doctor_command(self) -> None:
        code, output, error = self.invoke("doctor")
        self.assertEqual(0, code)
        for component in ("Runtime", "Manifests", "Evaluation", "Provider"):
            self.assertIn(f"{component}: PASS", output)
        self.assertIn("Overall: PASS", output)
        self.assertEqual("", error)

    def test_successful_discovery_demo(self) -> None:
        code, output, error = self.invoke("demo", "discovery")
        self.assertEqual(0, code)
        self.assertIn("Validation passed.", output)
        self.assertIn("Authorization granted.", output)
        self.assertIn("Opportunity Report Score: 1.00", output)
        self.assertIn("Journey completed.", output)
        self.assertIn("Journey status: succeeded", output)
        self.assertEqual("", error)

    def test_failed_discovery_demo(self) -> None:
        def fail():
            raise RuntimeError("fixture unavailable")

        code, output, error = self.invoke("demo", "discovery", runner=fail)
        self.assertEqual(1, code)
        self.assertEqual("", output)
        self.assertEqual("Error: Discovery demo failed: fixture unavailable\n", error)

    def test_output_is_deterministic(self) -> None:
        first = self.invoke("demo", "discovery")
        second = self.invoke("demo", "discovery")
        self.assertEqual(first, second)

    def test_exit_codes(self) -> None:
        self.assertEqual(0, self.invoke("version")[0])
        self.assertEqual(2, self.invoke("unknown-command")[0])

    def test_rendering_is_plain_and_complete(self) -> None:
        output = render_discovery(run_discovery_vertical_slice())
        self.assertNotIn("\x1b[", output)
        self.assertIn("Artifacts generated: opportunity_report", output)
        self.assertIn("Evaluation score: 1.00", output)
        self.assertIn("Execution duration: not recorded", output)

    def test_demo_uses_no_real_provider_or_network(self) -> None:
        with (
            patch.object(socket, "create_connection", side_effect=AssertionError("network used")),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError("network used")),
        ):
            code, output, error = self.invoke("demo", "discovery")
        self.assertEqual(0, code, error)
        self.assertIn("Journey completed.", output)

    def test_demo_does_not_mutate_runtime_or_files(self) -> None:
        runtime = RuntimeFixture()
        repositories_before = runtime.repositories.export_records()
        root = discovery_example_root()
        files_before = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
        code, _, error = self.invoke("demo", "discovery")
        files_after = {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(0, code, error)
        self.assertEqual(repositories_before, runtime.repositories.export_records())
        self.assertEqual(files_before, files_after)


if __name__ == "__main__":
    unittest.main()
