"""PR-181 configuration-collection integrity: guard rails and pins.

Step 1 (guard rails) lands BEFORE any behaviour change and must stay green
through every later step:

- T19: platforms that successfully collect configuration today — FRRouting
  above all, 79% of the measured live estate — keep collecting after the
  collector becomes driver-aware.
- T16: every configuration Atlas has actually collected on this machine
  remains an accepted configuration. The live estate is the one corpus that
  can prove the repair does not fail closed on real data.
- Every CONFIGURATION CommandSpec is required=False: ProductionDriver raises
  AtlasDiscoveryError when a REQUIRED spec hits a transport fault, and that
  exception escapes the CLI collection loop's except clause — one flaky
  device must never end collection for the whole run.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from founderos_atlas.config import collect_configuration
from founderos_atlas.platforms import capabilities as caps
from founderos_atlas.platforms.registry import default_registry

from tests.test_config_collection import config_outputs, make_collection


# A realistic FRRouting (vtysh) running configuration, shaped like the ones
# the live estate actually holds: hostname, interfaces, BGP, statics.
FRR_RUNNING_CONFIG = (
    "frr version 8.4.2\n"
    "frr defaults traditional\n"
    "hostname chennai-edge\n"
    "!\n"
    "interface eth0\n"
    " ip address 10.30.0.1/31\n"
    "!\n"
    "interface eth1\n"
    " ip address 10.30.0.3/31\n"
    "!\n"
    "router bgp 65040\n"
    " neighbor 10.30.0.0 remote-as 65041\n"
    " neighbor 10.30.0.2 remote-as 65042\n"
    "!\n"
    "ip route 0.0.0.0/0 10.30.0.0\n"
    "line vty\n"
    "!\n"
    "end\n"
)


def _live_estate_configs(limit: int | None = None) -> list[Path]:
    """Every running_config.txt this machine's estate holds (live + history).

    Empty on a machine without an estate — the corpus tests skip then.
    """

    repo = Path(__file__).resolve().parent.parent
    roots = (repo / ".atlas" / "profiles", repo / "configs")
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found.extend(sorted(root.rglob("running_config.txt")))
    return found[:limit] if limit else found


class ConfigurationCommandSpecContractTests(unittest.TestCase):
    """No CONFIGURATION capability may be marked required (PR-181 R7)."""

    def test_every_configuration_commandspec_is_optional(self) -> None:
        checked = 0
        for driver_cls in default_registry().drivers():
            driver = driver_cls()
            try:
                plan = driver.command_plan()
            except (NotImplementedError, AttributeError):
                continue  # legacy PlatformDriver — no CommandSpec plan
            for spec in plan:
                if spec.capability == caps.CONFIGURATION:
                    checked += 1
                    self.assertFalse(
                        spec.required,
                        f"{type(driver).__name__} marks CONFIGURATION required; "
                        "a transport fault on one device would abort the whole "
                        "collection run (production.py raises AtlasDiscoveryError "
                        "for required specs, which the CLI loop does not catch)",
                    )
        self.assertGreaterEqual(
            checked, 8, "expected at least the eight known CONFIGURATION specs"
        )


class CollectionRegressionGuardTests(unittest.TestCase):
    """T19 — what collects today must still collect after the repair."""

    def test_frr_style_configuration_stays_collected(self) -> None:
        # FRRouting is 968 of the live estate's 1430 snapshots. Its vtysh
        # answers the legacy 'show running-config'; the driver declares no
        # CONFIGURATION spec. This pin fails if the repair ever turns that
        # into "unsupported by declaration".
        _, transport, result = make_collection(
            config_outputs(**{"show running-config": FRR_RUNNING_CONFIG})
        )
        artifact = collect_configuration(transport, result, include_optional=False)
        self.assertEqual("complete", artifact.status)
        self.assertEqual(FRR_RUNNING_CONFIG, artifact.running_config)

    def test_classic_ios_configuration_stays_collected(self) -> None:
        _, transport, result = make_collection(config_outputs())
        artifact = collect_configuration(transport, result, include_optional=False)
        self.assertEqual("complete", artifact.status)
        self.assertIn("hostname R1", artifact.running_config)


class LiveEstateCorpusTests(unittest.TestCase):
    """T16 — the repair must not fail closed on any real collected config.

    Runs only where an estate exists; on other machines the corpus is empty
    and the test skips rather than asserting on nothing.
    """

    def test_every_live_configuration_remains_collected(self) -> None:
        corpus = _live_estate_configs()
        if not corpus:
            self.skipTest("no live estate on this machine")
        rejected: list[str] = []
        for path in corpus:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if not text.strip():
                continue  # an empty file was never a collected configuration
            _, transport, result = make_collection(
                config_outputs(**{"show running-config": text})
            )
            artifact = collect_configuration(
                transport, result, include_optional=False
            )
            if artifact.status != "complete" or artifact.running_config != text:
                rejected.append(str(path))
        self.assertEqual(
            [], rejected,
            f"{len(rejected)} of {len(corpus)} real collected configurations "
            "would no longer be accepted",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
