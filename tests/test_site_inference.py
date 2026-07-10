"""Acceptance tests for the PR-033 evidence-based site inference foundation."""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from founderos_atlas.sites import (
    ASSIGNMENT_AMBIGUOUS,
    ASSIGNMENT_ASSIGNED,
    ASSIGNMENT_UNKNOWN,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Site,
    SiteCatalog,
    SiteCatalogRepository,
    SiteInferenceEngine,
)


def catalog() -> SiteCatalog:
    return SiteCatalog(
        sites=(
            Site(
                site_id="hyderabad",
                name="Hyderabad",
                hostname_patterns=("hyd-*",),
                # A site may contain many unrelated subnets.
                cidrs=("10.0.1.0/24", "192.168.10.0/24"),
                explicit_hostnames=("special-core",),
            ),
            Site(
                site_id="secunderabad",
                name="Secunderabad",
                hostname_patterns=("sec-*",),
                # ...and one supernet (10.0.0.0/16) is subnetted across
                # both sites: 10.0.1.0/24 above vs 10.0.2.0/24 here.
                cidrs=("10.0.2.0/24",),
            ),
        )
    )


class SiteInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SiteInferenceEngine(catalog())

    def test_explicit_user_assignment_is_high_confidence(self) -> None:
        assignment = self.engine.assign(hostname="SPECIAL-CORE")
        self.assertEqual(ASSIGNMENT_ASSIGNED, assignment.status)
        self.assertEqual("hyderabad", assignment.site_id)
        self.assertEqual(CONFIDENCE_HIGH, assignment.confidence)
        self.assertTrue(assignment.explicit)

    def test_hostname_convention_alone_is_low_confidence(self) -> None:
        assignment = self.engine.assign(hostname="HYD-R1")
        self.assertEqual("hyderabad", assignment.site_id)
        self.assertEqual(CONFIDENCE_LOW, assignment.confidence)
        self.assertFalse(assignment.explicit)

    def test_multiple_agreeing_signals_raise_confidence(self) -> None:
        # Hostname convention + seed-origin hint agree -> medium.
        assignment = self.engine.assign(
            hostname="HYD-R1", profile_site_hints=("hyderabad",)
        )
        self.assertEqual("hyderabad", assignment.site_id)
        self.assertEqual(CONFIDENCE_MEDIUM, assignment.confidence)
        signals = {evidence.signal for evidence in assignment.evidence}
        self.assertEqual({"hostname-convention", "seed-origin"}, signals)

    def test_subnet_corroboration_raises_confidence_one_step(self) -> None:
        assignment = self.engine.assign(
            hostname="HYD-R1", management_ips=("10.0.1.5",)
        )
        self.assertEqual("hyderabad", assignment.site_id)
        self.assertEqual(CONFIDENCE_MEDIUM, assignment.confidence)  # low -> medium

    def test_subnet_alone_never_forces_a_site_assignment(self) -> None:
        assignment = self.engine.assign(
            hostname="R99", management_ips=("10.0.1.5",)
        )
        self.assertEqual(ASSIGNMENT_UNKNOWN, assignment.status)
        self.assertIsNone(assignment.site_id)
        # The subnet evidence is still recorded transparently.
        self.assertTrue(
            any(evidence.signal == "subnet" for evidence in assignment.evidence)
        )

    def test_no_evidence_is_honestly_unknown(self) -> None:
        assignment = self.engine.assign(hostname="R11")
        self.assertEqual(ASSIGNMENT_UNKNOWN, assignment.status)

    def test_conflicting_signals_yield_ambiguous(self) -> None:
        # Hostname says Hyderabad; the observing profile hints Secunderabad.
        assignment = self.engine.assign(
            hostname="HYD-R1", profile_site_hints=("secunderabad",)
        )
        self.assertEqual(ASSIGNMENT_AMBIGUOUS, assignment.status)
        self.assertIsNone(assignment.site_id)
        self.assertGreaterEqual(len(assignment.evidence), 2)

    def test_conflicting_corroboration_does_not_raise_confidence(self) -> None:
        # Hostname votes Hyderabad but the address sits in Secunderabad's
        # declared range: assignment stands, confidence stays low.
        assignment = self.engine.assign(
            hostname="HYD-R1", management_ips=("10.0.2.5",)
        )
        self.assertEqual("hyderabad", assignment.site_id)
        self.assertEqual(CONFIDENCE_LOW, assignment.confidence)

    def test_a_site_may_contain_multiple_unrelated_subnets(self) -> None:
        for address in ("10.0.1.7", "192.168.10.7"):
            assignment = self.engine.assign(
                hostname="HYD-SW1", management_ips=(address,)
            )
            self.assertEqual("hyderabad", assignment.site_id)
            self.assertEqual(CONFIDENCE_MEDIUM, assignment.confidence)

    def test_one_supernet_may_span_multiple_sites(self) -> None:
        # Both 10.0.1.x and 10.0.2.x live in the same 10.0.0.0/16 supernet
        # yet corroborate different sites.
        hyd = self.engine.assign(hostname="HYD-R1", management_ips=("10.0.1.9",))
        sec = self.engine.assign(hostname="SEC-R11", management_ips=("10.0.2.9",))
        self.assertEqual("hyderabad", hyd.site_id)
        self.assertEqual("secunderabad", sec.site_id)

    def test_uncataloged_seed_hint_still_votes_deterministically(self) -> None:
        engine = SiteInferenceEngine(SiteCatalog())
        assignment = engine.assign(
            hostname="R1", profile_site_hints=("Branch Office 7",)
        )
        self.assertEqual("branch-office-7", assignment.site_id)
        self.assertEqual(CONFIDENCE_LOW, assignment.confidence)


class SiteCatalogRepositoryTests(unittest.TestCase):
    def test_catalog_round_trips_through_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = SiteCatalogRepository(Path(tmp))
            repository.save(catalog())
            loaded = repository.load()
            self.assertEqual(2, len(loaded.sites))
            self.assertEqual(
                ("hyd-*",), loaded.get("hyderabad").hostname_patterns
            )

    def test_missing_catalog_is_empty_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                (), SiteCatalogRepository(Path(tmp)).load().sites
            )


if __name__ == "__main__":
    unittest.main()
