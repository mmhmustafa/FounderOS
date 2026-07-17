"""Acceptance tests for PR-031A profile-scoped discovery isolation.

Every discovery profile owns an isolated scope — its own current artifacts,
configuration snapshots, operational state, incidents, and history — keyed
by the profile's stable ``profile_id``. Discovering one profile must never
mark another profile's devices as removed, and the All Networks view must
aggregate (never compare) the latest state of every scope.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.history import HistoryRepository
from founderos_atlas.sites import Site, SiteCatalog, SiteCatalogRepository
from founderos_atlas.visualization import TOPOLOGY_VISUAL_STYLE_MARKER
from founderos_atlas.workspace import (
    InMemoryCredentialProvider,
    ProfileRepository,
    ProfileService,
)
from founderos_runtime.cli import main

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_unified_pipeline import full_outputs


FIXED = datetime(2026, 7, 10, 8, 0, 0, tzinfo=timezone.utc)

A2_DOWN_BRIEF = (
    "Interface                  IP-Address      OK? Method Status                Protocol\n"
    "GigabitEthernet0/0         10.0.0.2        YES manual up                    up\n"
    "GigabitEthernet0/1         unassigned      YES unset  administratively down down\n"
)


def make_service(workdir: Path) -> ProfileService:
    return ProfileService(
        ProfileRepository(workdir / "workspace"),
        InMemoryCredentialProvider(),
        clock=lambda: FIXED,
    )


def add_profile(service: ProfileService, name: str, ip: str, **overrides):
    kwargs = {
        "name": name,
        "management_ip": ip,
        "username": "atlas",
        "password": PASSWORD,
        "max_depth": 1,
        "max_devices": 10,
        "collect_configuration": False,
    }
    kwargs.update(overrides)
    return service.add_profile(**kwargs)


def network_a(*, include_a2: bool = True, a2_interfaces: str | None = None):
    """Profile A's network: A1 with neighbor A2 (optionally absent/degraded)."""

    if not include_a2:
        return ScriptedNetwork({"10.0.0.1": full_outputs("A1", "10.0.0.1")})
    return ScriptedNetwork(
        {
            "10.0.0.1": full_outputs("A1", "10.0.0.1", (("A2", "10.0.0.2"),)),
            "10.0.0.2": full_outputs(
                "A2", "10.0.0.2", (("A1", "10.0.0.1"),),
                interfaces_brief=a2_interfaces,
            ),
        }
    )


def network_b():
    """Profile B's network: the single device B1."""

    return ScriptedNetwork({"10.0.1.1": full_outputs("B1", "10.0.1.1")})


def scope_dir(workdir: Path, profile_id: str) -> Path:
    return workdir / ".atlas" / "profiles" / profile_id


def run_discover(workdir: Path, service, network, profile: str, start: datetime):
    """Run the unified pipeline for one profile with injected everything."""

    ticks = iter([start, start + timedelta(seconds=30)])

    def no_prompt(prompt):
        raise AssertionError(f"unexpected prompt: {prompt!r}")

    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(
            ["atlas", "discover", "--profile", profile],
            atlas_transport_factory=lambda c: network.transport_factory(c.host),
            atlas_input_reader=no_prompt,
            atlas_password_reader=no_prompt,
            atlas_topology_output=workdir / "atlas_topology.html",
            atlas_snapshot_output=workdir / "topology_snapshot.json",
            atlas_morning_brief_output=workdir / "morning_brief.md",
            atlas_config_output_dir=workdir / "configs",
            atlas_dashboard_output=workdir / "dashboard.html",
            atlas_history_root=workdir / ".atlas" / "history",
            atlas_compare_json_output=workdir / "change_report.json",
            atlas_compare_markdown_output=workdir / "change_report.md",
            atlas_config_diff_json_output=workdir / "config_change_report.json",
            atlas_config_diff_markdown_output=workdir / "config_change_report.md",
            atlas_state_diff_json_output=workdir / "state_change_report.json",
            atlas_state_diff_markdown_output=workdir / "state_change_report.md",
            atlas_clock=lambda: next(ticks),
            atlas_browser_opener=lambda uri: None,
            atlas_profile_service=service,
        )
    return code, stdout.getvalue(), stderr.getvalue()


def run_unscoped_discover(workdir: Path, network, start: datetime):
    """Legacy interactive discovery (no profile): writes the unscoped layout."""

    ticks = iter([start, start + timedelta(seconds=30)])
    replies = iter(["10.0.0.1", "atlas", "", "", "n"])
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(
            ["atlas", "discover"],
            atlas_transport_factory=lambda c: network.transport_factory(c.host),
            atlas_input_reader=lambda prompt: next(replies, ""),
            atlas_password_reader=lambda prompt: PASSWORD,
            atlas_topology_output=workdir / "atlas_topology.html",
            atlas_snapshot_output=workdir / "topology_snapshot.json",
            atlas_morning_brief_output=workdir / "morning_brief.md",
            atlas_config_output_dir=workdir / "configs",
            atlas_dashboard_output=workdir / "dashboard.html",
            atlas_history_root=workdir / ".atlas" / "history",
            atlas_compare_json_output=workdir / "change_report.json",
            atlas_compare_markdown_output=workdir / "change_report.md",
            atlas_config_diff_json_output=workdir / "config_change_report.json",
            atlas_config_diff_markdown_output=workdir / "config_change_report.md",
            atlas_state_diff_json_output=workdir / "state_change_report.json",
            atlas_state_diff_markdown_output=workdir / "state_change_report.md",
            atlas_clock=lambda: next(ticks),
            atlas_browser_opener=lambda uri: None,
        )
    return code, stdout.getvalue(), stderr.getvalue()


def snapshot_hostnames(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {device["hostname"] for device in data["devices"]}


class ProfileScopeIsolationTests(unittest.TestCase):
    """CLI-level isolation: the core of PR-031A."""

    def setup_two_profiles(self, workdir: Path):
        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        add_profile(service, "Lab B", "10.0.1.1")
        return service

    def test_profiles_discover_into_isolated_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.setup_two_profiles(workdir)
            code, out, err = run_discover(workdir, service, network_a(), "Lab A", FIXED)
            self.assertEqual(0, code, err)
            code, out, err = run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            self.assertEqual(0, code, err)
            # B's first run has NO baseline — A's run is invisible to it.
            self.assertIn(
                "[4/9] Loading previous baseline ... skipped (first discovery)", out
            )
            scope_a = scope_dir(workdir, "lab-a")
            scope_b = scope_dir(workdir, "lab-b")
            self.assertEqual(
                {"A1", "A2"}, snapshot_hostnames(scope_a / "topology_snapshot.json")
            )
            self.assertEqual(
                {"B1"}, snapshot_hostnames(scope_b / "topology_snapshot.json")
            )
            # No change report anywhere: both runs were first discoveries.
            self.assertFalse((scope_a / "change_report.json").exists())
            self.assertFalse((scope_b / "change_report.json").exists())
            # Nothing was written to the shared unscoped workspace.
            self.assertFalse((workdir / "topology_snapshot.json").exists())

    def test_cross_profile_runs_produce_no_false_removals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.setup_two_profiles(workdir)
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            # A again: must compare against A's own baseline -> zero changes.
            code, out, err = run_discover(
                workdir, service, network_a(), "Lab A", FIXED + timedelta(hours=2)
            )
            self.assertEqual(0, code, err)
            self.assertIn("0 topology change(s)", out)
            scope_a = scope_dir(workdir, "lab-a")
            report = json.loads(
                (scope_a / "change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(0, report["change_count"])
            self.assertEqual([], report["removed_devices"])
            self.assertNotIn("B1", (scope_a / "change_report.md").read_text("utf-8"))
            # B again: A1/A2 must not appear removed either.
            code, out, err = run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=3)
            )
            self.assertEqual(0, code, err)
            scope_b = scope_dir(workdir, "lab-b")
            report = json.loads(
                (scope_b / "change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(0, report["change_count"])
            self.assertEqual([], report["removed_devices"])
            markdown = (scope_b / "change_report.md").read_text("utf-8")
            self.assertNotIn("A1", markdown)
            self.assertNotIn("A2", markdown)

    def test_baseline_comes_from_the_same_profile_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.setup_two_profiles(workdir)
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            _, out, _ = run_discover(
                workdir, service, network_a(), "Lab A", FIXED + timedelta(hours=2)
            )
            # A's baseline is A's 08:00 record — not B's 09:00 record.
            self.assertIn(
                "[4/9] Loading previous baseline ... ok (2026-07-10_08-00-00)", out
            )
            _, out, _ = run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=3)
            )
            self.assertIn(
                "[4/9] Loading previous baseline ... ok (2026-07-10_09-00-00)", out
            )

    def test_genuine_removal_is_detected_within_a_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.setup_two_profiles(workdir)
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            # A2 genuinely disappears from Lab A.
            code, out, err = run_discover(
                workdir,
                service,
                network_a(include_a2=False),
                "Lab A",
                FIXED + timedelta(hours=2),
            )
            self.assertEqual(0, code, err)
            scope_a = scope_dir(workdir, "lab-a")
            report = json.loads(
                (scope_a / "change_report.json").read_text(encoding="utf-8")
            )
            self.assertIn("A2", report["removed_devices"])
            self.assertIn(
                "A2 is no longer discovered",
                (scope_a / "change_report.md").read_text("utf-8"),
            )
            # ...and Lab B's scope is completely untouched by all of this.
            scope_b = scope_dir(workdir, "lab-b")
            self.assertEqual(
                {"B1"}, snapshot_hostnames(scope_b / "topology_snapshot.json")
            )
            self.assertFalse((scope_b / "change_report.json").exists())

    def test_history_is_stamped_with_stable_profile_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.setup_two_profiles(workdir)
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            index_a = HistoryRepository(
                scope_dir(workdir, "lab-a") / "history"
            ).load()
            self.assertEqual(1, len(index_a.records))
            self.assertEqual("lab-a", index_a.records[0].profile_id)
            self.assertEqual("Lab A", index_a.records[0].profile_name)
            index_b = HistoryRepository(
                scope_dir(workdir, "lab-b") / "history"
            ).load()
            self.assertEqual(1, len(index_b.records))
            self.assertEqual("lab-b", index_b.records[0].profile_id)
            # The legacy unscoped history remains empty.
            legacy = HistoryRepository(workdir / ".atlas" / "history").load()
            self.assertEqual(0, len(legacy.records))

    def test_rename_keeps_scope_history_and_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.setup_two_profiles(workdir)
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            renamed = service.update_profile("Lab A", new_name="Lab A Production")
            self.assertEqual("lab-a", renamed.profile_id)  # identity is stable
            code, out, err = run_discover(
                workdir,
                service,
                network_a(),
                "Lab A Production",
                FIXED + timedelta(hours=2),
            )
            self.assertEqual(0, code, err)
            # The pre-rename run is still the baseline: same scope, no loss.
            self.assertIn(
                "[4/9] Loading previous baseline ... ok (2026-07-10_08-00-00)", out
            )
            index = HistoryRepository(scope_dir(workdir, "lab-a") / "history").load()
            self.assertEqual(2, len(index.records))
            names = {record.profile_name for record in index.records}
            self.assertEqual({"Lab A", "Lab A Production"}, names)
            self.assertEqual(
                {"lab-a"}, {record.profile_id for record in index.records}
            )

    def test_configuration_snapshots_are_isolated_by_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1", collect_configuration=True)
            add_profile(service, "Lab B", "10.0.1.1", collect_configuration=True)
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            scope_a = scope_dir(workdir, "lab-a")
            scope_b = scope_dir(workdir, "lab-b")
            self.assertTrue(
                (scope_a / "configs" / "A1" / "running_config.txt").is_file()
            )
            self.assertTrue(
                (scope_b / "configs" / "B1" / "running_config.txt").is_file()
            )
            self.assertFalse((scope_b / "configs" / "A1").exists())
            self.assertFalse((workdir / "configs").exists())
            # Second B run compares only B's own configurations.
            _, out, _ = run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=2)
            )
            report = json.loads(
                (scope_b / "config_change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, report["device_count"])
            hostnames = {entry["hostname"] for entry in report["reports"]}
            self.assertEqual({"B1"}, hostnames)

    def test_operational_state_is_isolated_by_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.setup_two_profiles(workdir)
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            # A degrades: A2's interface goes down. Detected inside Lab A.
            code, out, err = run_discover(
                workdir,
                service,
                network_a(a2_interfaces=A2_DOWN_BRIEF),
                "Lab A",
                FIXED + timedelta(hours=2),
            )
            self.assertEqual(0, code, err)
            scope_a = scope_dir(workdir, "lab-a")
            report = json.loads(
                (scope_a / "state_change_report.json").read_text(encoding="utf-8")
            )
            self.assertGreaterEqual(report["active_issue_count"], 1)
            # B's next run sees none of A's operational events.
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=3)
            )
            scope_b = scope_dir(workdir, "lab-b")
            report = json.loads(
                (scope_b / "state_change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(0, report["change_count"])
            self.assertEqual(0, report["active_issue_count"])
            self.assertNotIn(
                "A2", (scope_b / "state_change_report.md").read_text("utf-8")
            )

    def test_legacy_unscoped_discovery_is_unchanged_and_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            # Legacy flow first: profile-less discovery uses the classic layout.
            code, out, err = run_unscoped_discover(workdir, network_a(), FIXED)
            self.assertEqual(0, code, err)
            legacy_snapshot = workdir / "topology_snapshot.json"
            self.assertTrue(legacy_snapshot.is_file())
            before = legacy_snapshot.read_bytes()
            legacy_index = HistoryRepository(workdir / ".atlas" / "history").load()
            self.assertEqual(1, len(legacy_index.records))
            # Legacy records carry no profile identity (default scope).
            self.assertIsNone(legacy_index.records[0].profile_id)
            # A profile discovery afterwards must not disturb legacy data.
            service = make_service(workdir)
            add_profile(service, "Lab B", "10.0.1.1")
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            self.assertEqual(before, legacy_snapshot.read_bytes())
            legacy_index = HistoryRepository(workdir / ".atlas" / "history").load()
            self.assertEqual(1, len(legacy_index.records))
            # And the legacy flow keeps comparing against its own baseline.
            code, out, err = run_unscoped_discover(
                workdir, network_a(), FIXED + timedelta(hours=2)
            )
            self.assertEqual(0, code, err)
            self.assertIn(
                "[4/9] Loading previous baseline ... ok (2026-07-10_08-00-00)", out
            )
            report = json.loads(
                (workdir / "change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(0, report["change_count"])

    def test_profile_ids_are_unique_even_for_colliding_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            first = add_profile(service, "Lab A", "10.0.0.1")
            second = add_profile(service, "Lab-A", "10.0.0.9")
            self.assertNotEqual(first.profile_id, second.profile_id)
            self.assertNotEqual(first.credential_ref, second.credential_ref)
            # Both credentials resolve independently.
            self.assertEqual(
                PASSWORD, service.resolve_discovery_inputs("Lab A").password
            )
            self.assertEqual(
                PASSWORD, service.resolve_discovery_inputs("Lab-A").password
            )

    def test_rename_via_service_keeps_credential_and_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(Path(tmp))
            add_profile(service, "Lab A", "10.0.0.1")
            service.update_profile("Lab A", new_name="Lab A Production")
            inputs = service.resolve_discovery_inputs("Lab A Production")
            self.assertEqual(PASSWORD, inputs.password)
            self.assertEqual("lab-a", inputs.profile_id)
            with self.assertRaises(Exception):
                service.get_profile("Lab A")


class ProfileScopedCliCommandTests(unittest.TestCase):
    """--profile support on the read-side CLI commands."""

    def build_two_profile_history(self, workdir: Path):
        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        add_profile(service, "Lab B", "10.0.1.1")
        run_discover(workdir, service, network_a(), "Lab A", FIXED)
        run_discover(
            workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
        )
        return service

    def invoke(self, *arguments, workdir: Path, service):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                list(arguments),
                atlas_history_root=workdir / ".atlas" / "history",
                atlas_dashboard_output=workdir / "dashboard.html",
                atlas_timeline_output=workdir / "timeline.md",
                atlas_snapshot_output=workdir / "topology_snapshot.json",
                atlas_topology_output=workdir / "atlas_topology.html",
                atlas_morning_brief_output=workdir / "morning_brief.md",
                atlas_config_output_dir=workdir / "configs",
                atlas_compare_json_output=workdir / "change_report.json",
                atlas_compare_markdown_output=workdir / "change_report.md",
                atlas_config_diff_json_output=workdir / "config_change_report.json",
                atlas_config_diff_markdown_output=workdir / "config_change_report.md",
                atlas_state_diff_json_output=workdir / "state_change_report.json",
                atlas_state_diff_markdown_output=workdir / "state_change_report.md",
                atlas_profile_service=service,
                atlas_browser_opener=lambda uri: None,
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_history_command_is_profile_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_two_profile_history(workdir)
            code, out, err = self.invoke(
                "atlas", "history", "--profile", "Lab A",
                workdir=workdir, service=service,
            )
            self.assertEqual(0, code, err)
            self.assertIn("Atlas Discovery History — Lab A", out)
            self.assertIn("10-Jul-2026 08:00", out)
            self.assertNotIn("10-Jul-2026 09:00", out)  # B's run is invisible
            self.assertIn("Profile: Lab A", out)

    def test_history_command_without_profile_shows_legacy_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_two_profile_history(workdir)
            code, out, err = self.invoke(
                "atlas", "history", workdir=workdir, service=service
            )
            self.assertEqual(0, code, err)
            self.assertIn("No discovery history yet", out)

    def test_dashboard_command_is_profile_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_two_profile_history(workdir)
            code, out, err = self.invoke(
                "atlas", "dashboard", "--profile", "Lab B",
                workdir=workdir, service=service,
            )
            self.assertEqual(0, code, err)
            dashboard = scope_dir(workdir, "lab-b") / "dashboard.html"
            self.assertTrue(dashboard.is_file())
            self.assertFalse((workdir / "dashboard.html").exists())
            html = dashboard.read_text(encoding="utf-8")
            # Lab B's numbers: 1 device, discovered at 09:00 — not Lab A's 2.
            self.assertIn('<strong>Devices</strong><span class="value">1</span>', html)
            self.assertIn("Last discovery: 10-Jul-2026 09:00", html)

    def test_timeline_command_is_profile_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_two_profile_history(workdir)
            code, out, err = self.invoke(
                "atlas", "timeline", "--profile", "Lab A",
                workdir=workdir, service=service,
            )
            self.assertEqual(0, code, err)
            timeline = scope_dir(workdir, "lab-a") / "timeline.md"
            self.assertTrue(timeline.is_file())
            self.assertIn("Discoveries recorded: 1", out)

    def test_unknown_profile_is_a_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            code, out, err = self.invoke(
                "atlas", "history", "--profile", "Nope",
                workdir=workdir, service=service,
            )
            self.assertEqual(1, code)
            self.assertIn("No saved profile named 'Nope'", err)


class WebScopeTests(unittest.TestCase):
    """GUI scope selector: per-profile filtering and the All Networks view."""

    def build_world(self, workdir: Path):
        """Two profiles with completed discoveries plus a web client."""

        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        add_profile(service, "Lab B", "10.0.1.1")
        run_discover(workdir, service, network_a(), "Lab A", FIXED)
        run_discover(
            workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
        )
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def test_dashboard_scope_filtering_and_global_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/?scope=lab-a").data
            self.assertIn(b"Lab A", page)
            self.assertIn(b"<span>2</span>", page)  # Lab A device count
            page = client.get("/?scope=lab-b").data
            self.assertIn(b"Lab B", page)
            self.assertIn(b"<span>1</span>", page)
            page = client.get("/?scope=all").data
            # PR-041: enterprise-first language — the global scope's
            # label is "Enterprise" (the id stays "all").
            self.assertIn(b"Enterprise", page)
            self.assertIn(b"<span>3</span>", page)  # 2 + 1 devices combined
            self.assertIn(b"Lab A", page)
            self.assertIn(b"Lab B", page)

    def test_topology_scope_filtering_and_global_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/topology?scope=lab-b").data
            self.assertIn(b".atlas/profiles/lab-b/atlas_topology.html", page)
            self.assertNotIn(b".atlas/profiles/lab-a/", page)
            page = client.get("/topology?scope=all").data
            for hostname in (b"A1", b"A2", b"B1"):
                self.assertIn(hostname, page)

    def test_stale_current_profile_viewer_refreshes_without_rewriting_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.build_world(workdir)
            SiteCatalogRepository(workdir / "workspace").save(
                SiteCatalog(
                    sites=(
                        Site(
                            site_id="alpha",
                            name="Alpha Site",
                            explicit_hostnames=("A1", "A2"),
                        ),
                        Site(
                            site_id="beta",
                            name="Beta Site",
                            explicit_hostnames=("B1",),
                        ),
                    )
                )
            )
            current = scope_dir(workdir, "lab-a")
            viewer = current / "atlas_topology.html"
            snapshot_before = (current / "topology_snapshot.json").read_bytes()
            history_viewers = tuple(sorted((current / "history").glob("*/atlas_topology.html")))
            history_before = {path: path.read_bytes() for path in history_viewers}
            last_discovery = service.get_profile("Lab A").last_discovery
            viewer.write_text("<html>stale current viewer</html>", encoding="utf-8")

            response = client.get("/topology?scope=lab-a")

            self.assertEqual(200, response.status_code)
            refreshed = viewer.read_text(encoding="utf-8")
            self.assertIn(TOPOLOGY_VISUAL_STYLE_MARKER, refreshed)
            self.assertIn("A1", refreshed)
            self.assertIn('"id":"site:alpha"', refreshed)
            self.assertEqual(
                snapshot_before,
                (current / "topology_snapshot.json").read_bytes(),
            )
            self.assertEqual(
                history_before,
                {path: path.read_bytes() for path in history_viewers},
            )
            self.assertEqual(last_discovery, service.get_profile("Lab A").last_discovery)

    def test_failed_style_refresh_preserves_the_existing_viewer_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            current = scope_dir(workdir, "lab-a")
            viewer = current / "atlas_topology.html"
            old_viewer = b"<html>still-readable stale viewer</html>"
            viewer.write_bytes(old_viewer)
            (current / "topology_snapshot.json").write_text(
                json.dumps({"snapshot_id": "atlas-topology:broken"}),
                encoding="utf-8",
            )

            response = client.get("/topology?scope=lab-a")

            self.assertEqual(200, response.status_code)
            self.assertEqual(old_viewer, viewer.read_bytes())
            self.assertEqual(
                [],
                list(current.glob(".atlas_topology.html.*.refreshing")),
            )

    def test_history_scope_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/history?scope=lab-a").data
            self.assertIn(b"10-Jul-2026 08:00", page)
            self.assertNotIn(b"10-Jul-2026 09:00", page)
            page = client.get("/history?scope=all").data
            self.assertIn(b"10-Jul-2026 08:00", page)
            self.assertIn(b"10-Jul-2026 09:00", page)
            self.assertIn(b"Lab A", page)
            self.assertIn(b"Lab B", page)

    def test_scope_selection_persists_in_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/?scope=lab-b")
            page = client.get("/history").data  # no scope param: session rules
            self.assertIn(b"10-Jul-2026 09:00", page)
            self.assertNotIn(b"10-Jul-2026 08:00", page)

    def test_incidents_do_not_leak_across_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/incidents?scope=lab-a")  # select Lab A
            response = client.post(
                "/incidents/run",
                data={"title": "Device A2 unreachable", "description": "test"},
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertTrue(
                (scope_dir(workdir, "lab-a") / "incident_report.json").is_file()
            )
            self.assertFalse(
                (scope_dir(workdir, "lab-b") / "incident_report.json").exists()
            )
            self.assertFalse((workdir / "incident_report.json").exists())
            page = client.get("/incidents?scope=lab-b").data
            self.assertIn(b"No incident report generated yet", page)
            page = client.get("/incidents?scope=all").data
            self.assertIn(b"Device A2 unreachable", page)

    def test_incident_run_requires_a_specific_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/incidents?scope=all")
            response = client.post(
                "/incidents/run",
                data={"title": "Anything"},
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(b"Select a specific network scope", response.data)

    def test_changes_scope_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.build_world(workdir)
            # Second Lab B run creates B's (empty) change intelligence.
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=2)
            )
            page = client.get("/changes?scope=lab-b").data
            self.assertIn(b"0 change(s)", page)
            # The page reads as Lab B's change intelligence, with only
            # Lab B's archived runs offered for comparison (the scope
            # dropdown may legitimately name every profile).
            self.assertIn("Change Intelligence — Lab B".encode(), page)
            self.assertIn(b"Lab B \xc2\xb7 2026-07-10T", page)
            self.assertNotIn(b"Lab A \xc2\xb7 2026-07-10T", page)

    def test_scope_selector_lists_all_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/").data
            self.assertIn(b"Enterprise", page)
            self.assertIn(b'value="lab-a"', page)
            self.assertIn(b'value="lab-b"', page)
            # No legacy data -> the Local workspace option stays hidden.
            self.assertNotIn(b'value="default"', page)

    def test_topology_viewers_exist_for_each_scoped_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            self.assertTrue(
                (scope_dir(workdir, "lab-a") / "atlas_topology.html").is_file()
            )
            self.assertTrue(
                (scope_dir(workdir, "lab-b") / "atlas_topology.html").is_file()
            )
            page = client.get("/topology?scope=all").data
            self.assertIn(b".atlas/profiles/lab-a/atlas_topology.html", page)
            self.assertIn(b".atlas/profiles/lab-b/atlas_topology.html", page)

    def test_local_workspace_option_appears_with_legacy_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            run_unscoped_discover(workdir, network_a(), FIXED)
            from founderos_atlas.web import create_app

            service = make_service(workdir)
            app = create_app(
                profile_service=service,
                output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            page = client.get("/").data
            self.assertIn(b'value="default"', page)
            page = client.get("/?scope=default").data
            self.assertIn(b"Local workspace", page)
            self.assertIn(b"<span>2</span>", page)  # A1 + A2


class LegacyScopePolicyTests(unittest.TestCase):
    """Legacy-data policy: once profile scopes hold discovery data, the
    legacy Local workspace is archived out of All Networks aggregation —
    never deleted, always selectable directly."""

    def build_client(self, workdir: Path, service):
        from founderos_atlas.web import create_app

        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def build_legacy_then_profiles(self, workdir: Path):
        """The exact CML regression: legacy data holds the same devices
        that profile A later discovers into its own scope."""

        run_unscoped_discover(workdir, network_a(), FIXED - timedelta(hours=1))
        service = make_service(workdir)
        add_profile(service, "Lab A", "10.0.0.1")
        add_profile(service, "Lab B", "10.0.1.1")
        run_discover(workdir, service, network_a(), "Lab A", FIXED)
        run_discover(
            workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
        )
        return service

    def test_active_scopes_policy_is_deterministic(self) -> None:
        from founderos_atlas.workspace import (
            active_scopes,
            default_scope,
            profile_scope,
        )

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            default = default_scope(workdir)
            profile = profile_scope(workdir, "lab-a", "Lab A")
            # Nothing anywhere -> empty estate.
            self.assertEqual((), active_scopes(default, (profile,)))
            # Legacy data only -> the default scope keeps working.
            default.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            default.snapshot_path.write_text("{}", encoding="utf-8")
            self.assertEqual((default,), active_scopes(default, (profile,)))
            # A profile discovery supersedes legacy in aggregation.
            profile.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            profile.snapshot_path.write_text("{}", encoding="utf-8")
            self.assertEqual((profile,), active_scopes(default, (profile,)))

    def test_legacy_hidden_from_all_networks_once_profiles_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_legacy_then_profiles(workdir)
            client = self.build_client(workdir, service)
            page = client.get("/?scope=all").data
            # 2 active networks, 3 devices — not 3 networks / 5 devices.
            self.assertIn(b"<strong>Networks</strong><span>2</span>", page)
            self.assertIn(b"<strong>Devices</strong><span>3</span>", page)
            # No Local workspace row in the networks table.
            self.assertNotIn(b'href="/?scope=default"', page)
            # Global topology inventory lists each device exactly once.
            page = client.get("/topology?scope=all").data
            self.assertEqual(1, page.count(b"<td>A1</td>"))
            self.assertEqual(1, page.count(b"<td>A2</td>"))
            self.assertEqual(1, page.count(b"<td>B1</td>"))
            # Merged history excludes the legacy 07:00 run.
            page = client.get("/history?scope=all").data
            self.assertNotIn(b"10-Jul-2026 07:00", page)
            self.assertIn(b"10-Jul-2026 08:00", page)
            self.assertIn(b"10-Jul-2026 09:00", page)

    def test_legacy_stays_selectable_and_intact_as_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = self.build_legacy_then_profiles(workdir)
            client = self.build_client(workdir, service)
            # Clearly labelled as legacy in the selector once superseded.
            page = client.get("/?scope=all").data
            self.assertIn(b"Local workspace (legacy)", page)
            # Still directly viewable, with its data untouched.
            page = client.get("/?scope=default").data
            self.assertIn(b"<span>2</span>", page)  # legacy A1 + A2
            page = client.get("/history?scope=default").data
            self.assertIn(b"10-Jul-2026 07:00", page)
            self.assertTrue((workdir / "topology_snapshot.json").is_file())

    def test_legacy_participates_while_no_profile_has_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            run_unscoped_discover(workdir, network_a(), FIXED - timedelta(hours=1))
            service = make_service(workdir)
            # Profiles exist but have never discovered: legacy still counts.
            add_profile(service, "Lab A", "10.0.0.1")
            client = self.build_client(workdir, service)
            page = client.get("/?scope=all").data
            self.assertIn(b"<strong>Networks</strong><span>1</span>", page)
            self.assertIn(b"<strong>Devices</strong><span>2</span>", page)
            self.assertIn(b'href="/?scope=default"', page)
            # Not yet superseded -> no "(legacy)" suffix in the selector.
            self.assertNotIn(b"Local workspace (legacy)", page)

    def test_stale_legacy_critical_cannot_degrade_all_networks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            # Fabricate stale legacy state: a snapshot plus a Critical
            # operational report left over from pre-scoping days.
            (workdir / "topology_snapshot.json").write_text(
                json.dumps(
                    {"device_count": 2, "devices": [], "edges": [],
                     "warnings": [], "metadata": {}}
                ),
                encoding="utf-8",
            )
            (workdir / "state_change_report.json").write_text(
                json.dumps(
                    {"current_health": "Critical", "active_issue_count": 3,
                     "interfaces_down": 3}
                ),
                encoding="utf-8",
            )
            service = make_service(workdir)
            add_profile(service, "Lab A", "10.0.0.1")
            add_profile(service, "Lab B", "10.0.1.1")
            run_discover(workdir, service, network_a(), "Lab A", FIXED)
            run_discover(
                workdir, service, network_b(), "Lab B", FIXED + timedelta(hours=1)
            )
            client = self.build_client(workdir, service)
            page = client.get("/?scope=all").data
            # The canonical health model may honestly report Degraded or
            # Stale here (old evidence, missing configurations) — the point
            # of this test is narrower: the LEGACY scope's Critical must
            # never leak into the All Networks verdict.
            self.assertNotIn(b"status-banner status-critical", page)
            self.assertNotIn(b"interface(s) down", page)
            # The legacy scope itself still faithfully reports its state.
            page = client.get("/?scope=default").data
            self.assertIn(b"status-banner status-critical", page)

    def test_overlapping_hostnames_across_profiles_are_not_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            # Two legitimate sites reusing the same RFC1918 IP and hostname
            # for two physically distinct devices (distinct serial numbers).
            add_profile(service, "Site One", "10.0.0.1")
            add_profile(service, "Site Two", "10.0.0.1")

            def site_device(serial_suffix: str) -> ScriptedNetwork:
                outputs = dict(full_outputs("R1", "10.0.0.1"))
                outputs["show version"] = outputs["show version"].replace(
                    "SERIAL-R1", f"SERIAL-R1-{serial_suffix}"
                )
                return ScriptedNetwork({"10.0.0.1": outputs})

            run_discover(workdir, service, site_device("ONE"), "Site One", FIXED)
            run_discover(
                workdir, service, site_device("TWO"), "Site Two",
                FIXED + timedelta(hours=1),
            )
            client = self.build_client(workdir, service)
            page = client.get("/?scope=all").data
            self.assertIn(b"<strong>Networks</strong><span>2</span>", page)
            self.assertIn(b"<strong>Devices</strong><span>2</span>", page)
            page = client.get("/topology?scope=all").data
            # Two canonical R1 rows: never deduplicated on name alone.
            # (PR-037A: R1 appears once per inventory row; each site also
            # appears once in the contributing-profiles table.)
            self.assertEqual(2, page.count(b"<td>R1"))
            self.assertEqual(2, page.count(b"<td>Site One</td>"))
            self.assertEqual(2, page.count(b"<td>Site Two</td>"))
            self.assertNotIn(b"badge hop-badge hop-badge-pass\">merged", page)
            # Each site keeps its own clean first-discovery scope.
            self.assertFalse(
                (scope_dir(workdir, "site-one") / "change_report.json").exists()
            )
            self.assertFalse(
                (scope_dir(workdir, "site-two") / "change_report.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
