"""PR-181 Step 3 — the positive configuration classifier, in isolation.

The invariant under test: a reply becomes COLLECTED only when the resolved
driver positively confirms it is a configuration. The absence of a
recognised error is never proof. Refusal grammar explains rejections and
cannot be defeated by position (banners, usage blocks, prompt echoes).
"""

from __future__ import annotations

import unittest

from founderos_atlas.config.classify import (
    classify_configuration_reply,
    probe_regions,
    shared_structural_is_configuration,
)
from founderos_atlas.platforms.registry import default_registry

from tests.platform_fixtures import (
    adc as fx_adc,
    aruba_cx as fx_aruba,
    cisco_wlc as fx_wlc,
    eos as fx_eos,
    fortios as fx_fortios,
    ios_xe as fx_iosxe,
    junos as fx_junos,
    nxos as fx_nxos,
    panos as fx_panos,
)
from tests.test_configuration_integrity import FRR_RUNNING_CONFIG


def _driver(platform_id: str):
    driver = default_registry().driver_for(platform_id)
    assert driver is not None, platform_id
    return driver


def _status(driver, reply: str) -> str:
    return classify_configuration_reply(driver, reply)[0]


BANNER = "\n".join(
    "* AUTHORISED USE ONLY — activity on this system is monitored *"
    for _ in range(6)
)

IOS_XE_CONFIG = (
    "hostname R1\n"
    "!\n"
    "interface GigabitEthernet0/0\n"
    " ip address 10.0.0.1 255.255.255.0\n"
    "!\n"
    "end\n"
)

FORTIOS_CONFIG = fx_fortios.SHOW


class PositiveFirstTests(unittest.TestCase):
    """T24/T25 — valid configurations are COLLECTED, whatever they contain."""

    def test_every_platform_fixture_configuration_is_collected(self) -> None:
        cases = (
            ("cisco-ios-xe", IOS_XE_CONFIG),
            ("junos", fx_junos.SHOW_CONFIG_SET),
            ("paloalto-panos", fx_panos.SHOW_CONFIG_RUNNING),
            ("aruba-cx", fx_aruba.SHOW_RUNNING_CONFIG),
            ("cisco-wlc", fx_wlc.SHOW_RUNNING_CONFIG),
            ("fortinet-fortios", FORTIOS_CONFIG),
        )
        for platform_id, config in cases:
            with self.subTest(platform=platform_id):
                self.assertEqual(
                    "collected", _status(_driver(platform_id), config)
                )

    def test_valid_config_containing_refusal_words_is_collected(self) -> None:
        # T24: refusal grammar inside a description or trailing banner is
        # content, not a refusal — the positive test runs first.
        config = (
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " description invalid input detected on span\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            "banner motd ^C % Invalid input detected here once ^C\n"
            "end\n"
        )
        self.assertEqual("collected", _status(_driver("cisco-ios-xe"), config))

    def test_junos_config_quoting_refusal_words_is_collected(self) -> None:
        config = (
            "set system host-name edge-1\n"
            'set system login message "unknown command policy applies"\n'
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
        )
        self.assertEqual("collected", _status(_driver("junos"), config))

    def test_tiny_real_junos_stub_is_collected(self) -> None:
        # The three-line configuration that disproved the size heuristic.
        config = (
            "set system host-name stub-01\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set system services ssh\n"
        )
        self.assertEqual("collected", _status(_driver("junos"), config))

    def test_frr_configuration_is_collected_with_no_driver(self) -> None:
        self.assertEqual("collected", _status(None, FRR_RUNNING_CONFIG))


class RefusalRecallTests(unittest.TestCase):
    """T20/T22 — a refusal is a refusal wherever the device puts it."""

    def _refusals(self):
        return (
            ("cisco-ios-xe", fx_iosxe.UNSUPPORTED),
            ("cisco-nxos", fx_nxos.UNSUPPORTED),
            ("arista-eos", fx_eos.UNSUPPORTED),
            ("junos", fx_junos.UNSUPPORTED),
            ("fortinet-fortios", fx_fortios.UNKNOWN),
            ("paloalto-panos", fx_panos.UNKNOWN),
            ("aruba-cx", fx_aruba.UNKNOWN),
            ("cisco-wlc", fx_wlc.UNKNOWN),
            ("f5-bigip", fx_adc.F5_UNKNOWN),
            ("citrix-adc", fx_adc.NS_UNKNOWN),
            ("a10-acos", fx_adc.A10_UNKNOWN),
        )

    def test_every_bare_platform_refusal_is_unsupported(self) -> None:
        for platform_id, refusal in self._refusals():
            with self.subTest(platform=platform_id):
                self.assertEqual(
                    "unsupported", _status(_driver(platform_id), refusal)
                )

    def test_refusal_behind_six_line_banner_is_unsupported(self) -> None:
        # T20 — the measured recall failure of every pre-PR-181 classifier.
        for platform_id, refusal in self._refusals():
            with self.subTest(platform=platform_id):
                reply = BANNER + "\n" + refusal
                self.assertEqual(
                    "unsupported", _status(_driver(platform_id), reply)
                )

    def test_refusal_at_top_followed_by_usage_block_is_unsupported(self) -> None:
        # T22 — a refusal followed by five lines of help text puts the
        # refusal outside any tail window; the whole-reply probe finds it.
        reply = (
            fx_wlc.UNKNOWN + "\n"
            "Usage: show run-config [commands | startup]\n"
            "       show run-config commands\n"
            "       show sysinfo\n"
            "       show interface summary\n"
            "       show wlan summary\n"
        )
        self.assertEqual("unsupported", _status(_driver("cisco-wlc"), reply))

    def test_refusal_with_leading_whitespace_and_mixed_case(self) -> None:
        reply = "   \n   % INVALID INPUT DETECTED AT '^' MARKER.\n"
        self.assertEqual("unsupported", _status(_driver("cisco-ios-xe"), reply))

    def test_refusal_with_trailing_prompt_echo_is_unsupported(self) -> None:
        reply = fx_junos.UNSUPPORTED + "\n\nuser@edge-1> \n"
        self.assertEqual("unsupported", _status(_driver("junos"), reply))


class DenialTests(unittest.TestCase):
    """T21 — privilege denials are DENIED, wherever the device puts them."""

    def test_bare_privilege_denial_is_denied(self) -> None:
        self.assertEqual(
            "denied",
            _status(_driver("cisco-ios-xe"), fx_iosxe.PRIVILEGE_DENIED),
        )

    def test_privilege_denial_behind_banner_is_denied(self) -> None:
        reply = BANNER + "\n" + fx_iosxe.PRIVILEGE_DENIED
        self.assertEqual("denied", _status(_driver("cisco-ios-xe"), reply))


class FailClosedTests(unittest.TestCase):
    """T18/T23 — anything unconfirmed fails closed as UNRECOGNISED."""

    def test_show_version_in_the_config_slot_is_not_collected(self) -> None:
        self.assertEqual(
            "unrecognised",
            _status(_driver("cisco-ios-xe"), fx_iosxe.SHOW_VERSION),
        )

    def test_show_ip_interface_brief_is_not_collected(self) -> None:
        # The measured shared-default false positive: the table header used
        # to count as an interface stanza. Anchored away.
        self.assertEqual(
            "unrecognised",
            _status(_driver("cisco-ios-xe"), fx_iosxe.SHOW_IP_INT_BRIEF),
        )

    def test_ssh_banner_alone_is_not_collected(self) -> None:
        self.assertEqual(
            "unrecognised", _status(_driver("cisco-ios-xe"), BANNER)
        )

    def test_linux_shell_error_block_is_not_collected(self) -> None:
        reply = (
            "bash: show: command not found\n"
            "bash: running-config: command not found\n"
            "sh: 1: terminal: not found\n"
        )
        # 'not found' is shell-refusal grammar on the legacy fallback; with
        # a Cisco driver resolved this must still never be COLLECTED.
        self.assertIn(
            _status(_driver("cisco-ios-xe"), reply),
            ("unrecognised", "unsupported"),
        )

    def test_empty_and_whitespace_replies_are_empty(self) -> None:
        for reply in ("", "   \n  \n"):
            with self.subTest(reply=repr(reply)):
                self.assertEqual(
                    "empty", _status(_driver("cisco-ios-xe"), reply)
                )

    def test_unknown_platform_unrecognised_reply_fails_closed(self) -> None:
        # T18 — no driver, no structure, no recognised grammar.
        reply = "SYSTEM READY\nOK\nDONE\n"
        self.assertEqual("unrecognised", _status(None, reply))


class WrongPlatformTests(unittest.TestCase):
    """The wrong driver must degrade fail-closed, never fail-open."""

    def test_every_refusal_against_every_driver_never_collects(self) -> None:
        refusals = (
            fx_iosxe.UNSUPPORTED, fx_nxos.UNSUPPORTED, fx_eos.UNSUPPORTED,
            fx_junos.UNSUPPORTED, fx_fortios.UNKNOWN, fx_panos.UNKNOWN,
            fx_aruba.UNKNOWN, fx_wlc.UNKNOWN, fx_adc.F5_UNKNOWN,
            fx_adc.NS_UNKNOWN, fx_adc.A10_UNKNOWN,
        )
        drivers = [cls() for cls in default_registry().drivers()]
        for refusal in refusals:
            for driver in drivers:
                with self.subTest(
                    refusal=refusal[:24], driver=type(driver).__name__
                ):
                    self.assertNotEqual(
                        "collected", _status(driver, refusal)
                    )


class ProbeRegionTests(unittest.TestCase):
    def test_probe_regions_cover_head_tail_and_whole(self) -> None:
        reply = "a\nb\nc\nd\ne\nf\ng\n"
        regions = probe_regions(reply)
        for line in ("a", "b", "c", "e", "f", "g"):
            self.assertIn(line, regions)
        self.assertIn("e\nf\ng", regions)
        self.assertIn(reply, regions)

    def test_shared_structural_test_rejects_refusals(self) -> None:
        for refusal in (fx_junos.UNSUPPORTED, fx_panos.UNKNOWN, ""):
            self.assertFalse(shared_structural_is_configuration(refusal))
        self.assertTrue(shared_structural_is_configuration(FRR_RUNNING_CONFIG))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
