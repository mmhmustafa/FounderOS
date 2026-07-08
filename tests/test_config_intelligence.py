"""Acceptance tests for PR-026 configuration intelligence."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.config_intelligence import (
    compare_configurations,
    mask_line,
    render_config_report_json,
    render_config_report_markdown,
)
from founderos_atlas.dashboard import build_dashboard_summary
from founderos_atlas.history import HistoryRepository
from founderos_runtime.cli import main

from tests.test_atlas_history import record_fields
from tests.test_dashboard import summary_kwargs


BASE_CONFIG = """\
hostname R1
!
interface GigabitEthernet0/0
 ip address 10.0.0.1 255.255.255.0
 no shutdown
!
interface GigabitEthernet0/1
 description uplink to SW1
 ip address 10.0.1.1 255.255.255.0
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
router bgp 65001
 neighbor 10.0.1.2 remote-as 65002
!
ip route 0.0.0.0 0.0.0.0 10.0.0.254
!
access-list 101 permit tcp any host 10.0.0.10 eq 443
!
snmp-server community S3cr3tC0mmunity RO
!
ntp server 10.0.0.100
!
logging host 10.0.0.50
!
username admin password 7 094F471A1A0A
enable secret 5 $1$abcd$WvJhWq9pXo1
!
line vty 0 4
 transport input ssh
!
end
"""


def modified(*replacements: tuple[str, str], extra: str = "") -> str:
    text = BASE_CONFIG
    for old, new in replacements:
        text = text.replace(old, new)
    if extra:
        text = text.replace("!\nend", f"!\n{extra}\n!\nend")
    return text


class ConfigComparisonTests(unittest.TestCase):
    def compare(self, current: str, previous: str = BASE_CONFIG):
        return compare_configurations(previous, current, hostname="R1")

    def test_identical_configs_produce_no_changes(self) -> None:
        report = self.compare(BASE_CONFIG)
        self.assertEqual(0, report.change_count)
        self.assertEqual({"high": 0, "medium": 0, "low": 0}, report.severity_counts)

    def test_interface_change(self) -> None:
        report = self.compare(
            modified((" description uplink to SW1", " description uplink to SW2"))
        )
        self.assertEqual(1, report.change_count)
        change = report.changes[0]
        self.assertEqual("interfaces", change.category)
        self.assertEqual("medium", change.severity)
        self.assertEqual("interface GigabitEthernet0/1", change.raw_diff_reference)
        self.assertEqual((" description uplink to SW2",), change.added_lines)
        self.assertEqual((" description uplink to SW1",), change.removed_lines)
        self.assertIn("changed", change.summary)
        self.assertIn("Verify the interface change", change.recommendation)

    def test_ospf_change(self) -> None:
        report = self.compare(
            modified(
                (
                    " network 10.0.0.0 0.0.0.255 area 0",
                    " network 10.0.0.0 0.0.0.255 area 0\n network 10.0.1.0 0.0.0.255 area 0",
                )
            )
        )
        change = report.changes[0]
        self.assertEqual("ospf", change.category)
        self.assertEqual("medium", change.severity)
        self.assertIn(" network 10.0.1.0 0.0.0.255 area 0", change.added_lines)

    def test_bgp_change_is_high_severity(self) -> None:
        report = self.compare(
            modified(
                (
                    " neighbor 10.0.1.2 remote-as 65002",
                    " neighbor 10.0.1.2 remote-as 65002\n neighbor 10.0.2.2 remote-as 65003",
                )
            )
        )
        change = report.changes[0]
        self.assertEqual("bgp", change.category)
        self.assertEqual("high", change.severity)
        self.assertIn("BGP sessions", change.recommendation)

    def test_acl_change_is_high_severity(self) -> None:
        report = self.compare(modified(extra="access-list 101 deny ip any any log"))
        change = report.changes[0]
        self.assertEqual("acls", change.category)
        self.assertEqual("high", change.severity)
        self.assertIn("was added", change.summary)
        self.assertIn("security policy", change.recommendation)

    def test_static_route_change(self) -> None:
        report = self.compare(
            modified(
                (
                    "ip route 0.0.0.0 0.0.0.0 10.0.0.254",
                    "ip route 0.0.0.0 0.0.0.0 10.0.0.253",
                )
            )
        )
        self.assertEqual(2, report.change_count)  # one removed, one added line-section
        categories = {change.category for change in report.changes}
        self.assertEqual({"static-routes"}, categories)
        self.assertEqual({"medium"}, {change.severity for change in report.changes})

    def test_shutdown_escalates_interface_to_high(self) -> None:
        report = self.compare(
            modified((" no shutdown", " shutdown"))
        )
        change = report.changes[0]
        self.assertEqual("interfaces", change.category)
        self.assertEqual("high", change.severity)


class SecretMaskingTests(unittest.TestCase):
    def test_snmp_community_masking(self) -> None:
        report = compare_configurations(
            BASE_CONFIG,
            BASE_CONFIG.replace(
                "snmp-server community S3cr3tC0mmunity RO",
                "snmp-server community N3wC0mmunity RW",
            ),
            hostname="R1",
        )
        serialized = render_config_report_json(report) + render_config_report_markdown(report)
        self.assertNotIn("S3cr3tC0mmunity", serialized)
        self.assertNotIn("N3wC0mmunity", serialized)
        self.assertIn("<masked: line contains 'community'>", serialized)
        snmp_changes = [c for c in report.changes if c.category == "snmp"]
        self.assertEqual(2, len(snmp_changes))  # masked headers stay distinct sections

    def test_password_and_secret_masking(self) -> None:
        report = compare_configurations(
            BASE_CONFIG,
            BASE_CONFIG.replace(
                "username admin password 7 094F471A1A0A",
                "username admin password 7 13261E010803",
            ).replace(
                "enable secret 5 $1$abcd$WvJhWq9pXo1",
                "enable secret 5 $1$efgh$Zq8LmNoPq2",
            ),
            hostname="R1",
        )
        serialized = render_config_report_json(report) + render_config_report_markdown(report)
        for secret in ("094F471A1A0A", "13261E010803", "$1$abcd$WvJhWq9pXo1", "$1$efgh$Zq8LmNoPq2"):
            self.assertNotIn(secret, serialized)
        self.assertIn("<masked: line contains 'password'>", serialized)
        self.assertIn("<masked: line contains 'secret'>", serialized)
        self.assertEqual({"aaa"}, {c.category for c in report.changes})
        self.assertEqual({"high"}, {c.severity for c in report.changes})

    def test_mask_line_terms(self) -> None:
        self.assertEqual(
            " <masked: line contains 'key'>", mask_line(" crypto key generate rsa")
        )
        self.assertEqual(
            "<masked: line contains 'token'>", mask_line("token abc123")
        )
        self.assertEqual(" ip address 10.0.0.1", mask_line(" ip address 10.0.0.1"))


class SeverityClassificationTests(unittest.TestCase):
    def test_category_severity_mapping(self) -> None:
        cases = (
            ("ntp server 10.0.0.101", "ntp", "low"),
            ("logging host 10.0.0.51", "logging", "low"),
            ("vlan 30", "vlans", "medium"),
            ("ip nat inside source list 1 interface GigabitEthernet0/0 overload", "nat", "high"),
            ("aaa new-model", "aaa", "high"),
            ("banner motd ^Unauthorized^", "other", "low"),
        )
        for line, category, severity in cases:
            with self.subTest(line=line):
                report = compare_configurations(
                    BASE_CONFIG,
                    BASE_CONFIG.replace("!\nend", f"!\n{line}\n!\nend"),
                    hostname="R1",
                )
                self.assertEqual(1, report.change_count)
                self.assertEqual(category, report.changes[0].category)
                self.assertEqual(severity, report.changes[0].severity)

    def test_line_vty_change_is_high(self) -> None:
        report = compare_configurations(
            BASE_CONFIG,
            BASE_CONFIG.replace(" transport input ssh", " transport input telnet"),
            hostname="R1",
        )
        change = report.changes[0]
        self.assertEqual("line-access", change.category)
        self.assertEqual("high", change.severity)


class ReportRenderingTests(unittest.TestCase):
    def build_report(self):
        return compare_configurations(
            BASE_CONFIG,
            modified((" description uplink to SW1", " description uplink to SW2")),
            hostname="R1",
            previous_ref="2026-07-08_18-22-00",
            current_ref="2026-07-09_23-41-18",
        )

    def test_json_generation(self) -> None:
        data = json.loads(render_config_report_json(self.build_report()))
        self.assertEqual("R1", data["hostname"])
        self.assertEqual("2026-07-08_18-22-00", data["previous_ref"])
        self.assertEqual(1, data["change_count"])
        self.assertTrue(data["secrets_masked"])
        change = data["changes"][0]
        for field in (
            "hostname", "category", "severity", "summary", "recommendation",
            "added_lines", "removed_lines", "raw_diff_reference",
        ):
            self.assertIn(field, change)

    def test_markdown_generation(self) -> None:
        markdown = render_config_report_markdown(self.build_report())
        self.assertIn("# Atlas Configuration Change Report", markdown)
        self.assertIn("## Severity Summary", markdown)
        self.assertIn("| Medium | 1 |", markdown)
        self.assertIn("### [Medium] interface GigabitEthernet0/1", markdown)
        self.assertIn("+  description uplink to SW2", markdown)
        self.assertIn("-  description uplink to SW1", markdown)
        self.assertIn("Secrets: masked", markdown)

    def test_deterministic_output(self) -> None:
        first, second = self.build_report(), self.build_report()
        self.assertEqual(first, second)
        self.assertEqual(
            render_config_report_json(first), render_config_report_json(second)
        )
        self.assertEqual(
            render_config_report_markdown(first), render_config_report_markdown(second)
        )


class ConfigDiffCliTests(unittest.TestCase):
    def invoke(self, *arguments: str, workdir: Path, history_root: Path | None = None):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                list(arguments),
                atlas_history_root=history_root or (workdir / ".atlas" / "history"),
                atlas_config_diff_json_output=workdir / "config_change_report.json",
                atlas_config_diff_markdown_output=workdir / "config_change_report.md",
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_path_mode_generates_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            device_dir = workdir / "configs" / "R1"
            device_dir.mkdir(parents=True)
            previous = device_dir / "previous.txt"
            current = device_dir / "running_config.txt"
            previous.write_text(BASE_CONFIG, encoding="utf-8")
            current.write_text(
                modified((" description uplink to SW1", " description uplink to SW2")),
                encoding="utf-8",
            )
            code, output, error = self.invoke(
                "atlas", "config-diff", str(previous), str(current), workdir=workdir
            )
            self.assertEqual(0, code, error)
            self.assertIn("Atlas Configuration Change Report", output)
            self.assertIn("Device: R1", output)
            self.assertIn("Changes detected: 1", output)
            self.assertIn("[medium] interfaces: interface GigabitEthernet0/1", output)
            self.assertIn("Secrets: masked", output)
            report = json.loads(
                (workdir / "config_change_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual("R1", report["hostname"])
            self.assertIn(
                "# Atlas Configuration Change Report",
                (workdir / "config_change_report.md").read_text(encoding="utf-8"),
            )

    def test_latest_history_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            history_root = workdir / ".atlas" / "history"
            repository = HistoryRepository(history_root)
            with tempfile.TemporaryDirectory() as staging:
                for started_at, text in (
                    ("2026-07-08T18:22:00+00:00", BASE_CONFIG),
                    (
                        "2026-07-09T23:41:18+00:00",
                        modified((" no shutdown", " shutdown")),
                    ),
                ):
                    config_dir = Path(staging) / started_at[:13] / "R1"
                    config_dir.mkdir(parents=True)
                    (config_dir / "running_config.txt").write_text(text, encoding="utf-8")
                    repository.save_discovery(
                        **record_fields(started_at=started_at),
                        config_directories={"R1": config_dir},
                    )
            code, output, error = self.invoke(
                "atlas", "config-diff", "--latest", "R1", workdir=workdir
            )
            self.assertEqual(0, code, error)
            self.assertIn("Device: R1", output)
            self.assertIn("Previous: 2026-07-08_18-22-00", output)
            self.assertIn("Current: 2026-07-09_23-41-18", output)
            self.assertIn("[high] interfaces: interface GigabitEthernet0/0", output)

    def test_latest_requires_two_collected_configs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            code, output, error = self.invoke(
                "atlas", "config-diff", "--latest", "R1", workdir=workdir
            )
            self.assertEqual(1, code)
            self.assertIn("two are required", error)

    def test_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code, _, error = self.invoke("atlas", "config-diff", workdir=Path(tmp))
            self.assertEqual(2, code)
            self.assertIn("Usage: founderos atlas config-diff", error)

    def test_help_lists_config_diff(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["help"])
        self.assertEqual(0, code)
        self.assertIn("founderos atlas config-diff", stdout.getvalue())


class DashboardConfigChangesTests(unittest.TestCase):
    def test_dashboard_shows_configuration_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            report = compare_configurations(
                BASE_CONFIG,
                modified((" no shutdown", " shutdown")),
                hostname="R1",
            )
            (workdir / "config_change_report.json").write_text(
                render_config_report_json(report), encoding="utf-8"
            )
            (workdir / "config_change_report.md").write_text(
                render_config_report_markdown(report), encoding="utf-8"
            )
            summary = build_dashboard_summary(**summary_kwargs(workdir))
        self.assertEqual(
            (
                "Devices changed: 1",
                "High severity: 1",
                "Medium severity: 0",
                "Low severity: 0",
            ),
            summary.configuration_changes,
        )
        availability = {action.label: action.available for action in summary.actions}
        self.assertTrue(availability["Open Config Changes"])

    def test_dashboard_without_config_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = build_dashboard_summary(**summary_kwargs(Path(tmp)))
        self.assertEqual((), summary.configuration_changes)
        availability = {action.label: action.available for action in summary.actions}
        self.assertFalse(availability["Open Config Changes"])


if __name__ == "__main__":
    unittest.main()
