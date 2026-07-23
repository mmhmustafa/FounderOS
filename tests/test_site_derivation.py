"""Deriving sites from the hostname convention and the topology.

Atlas never invents a site from a guess — but a 19-city estate named
``<city>-<tier>-<role>`` with a catalog that names four is not a guess,
it is a convention Atlas simply was not reading. These tests pin the
convention reading AND the honesty guard that keeps it from over-claiming:
a shared device with no home of its own is placed only where the evidence
points one way, and left unidentified when it does not.

The site-vs-fabric thresholds were set against a real 117-device capture;
the fixtures here mirror that structure in miniature.
"""

from __future__ import annotations

import unittest

from founderos_atlas.sites.derivation import (
    DerivedDevice,
    derive_sites,
    hostname_prefix,
)
from founderos_atlas.sites.models import Site, SiteCatalog


def _edge(local_id: str, remote_hostname: str) -> dict:
    return {"local_device_id": local_id, "remote_hostname": remote_hostname}


def _cohesive_site(prefix: str) -> tuple[list, list]:
    """A small internally-wired branch: core wired to fw, sw and access."""

    devices = [
        DerivedDevice(f"id:{prefix}-{role}", f"{prefix}-branch-{role}")
        for role in ("core", "fw", "sw", "access")
    ]
    core = f"id:{prefix}-core"
    edges = [
        _edge(core, f"{prefix}-branch-fw"),
        _edge(core, f"{prefix}-branch-sw"),
        _edge(core, f"{prefix}-branch-access"),
    ]
    return devices, edges


class PrefixReadingTests(unittest.TestCase):
    def test_prefix_is_the_leading_token(self) -> None:
        self.assertEqual("chennai", hostname_prefix("chennai-branch-core"))

    def test_a_name_with_no_convention_yields_none(self) -> None:
        # A one-off box called "firewall" must never seed a site.
        self.assertIsNone(hostname_prefix("firewall"))
        self.assertIsNone(hostname_prefix(""))
        self.assertIsNone(hostname_prefix(None))


class ClusteringTests(unittest.TestCase):
    def test_a_convention_shared_by_many_becomes_a_site(self) -> None:
        devices, edges = _cohesive_site("chennai")
        result = derive_sites(devices, edges)
        self.assertEqual(
            ["chennai"], [s.site_id for s in result.catalog.sites]
        )
        self.assertEqual(("chennai-*",), result.catalog.sites[0].hostname_patterns)

    def test_a_single_device_is_too_thin_to_be_a_site(self) -> None:
        result = derive_sites([DerivedDevice("id:x", "solo-router-1")])
        self.assertEqual((), result.catalog.sites)

    def test_a_declared_site_is_never_re_derived(self) -> None:
        """The operator's word is not re-proposed. A declared chennai plus
        a derived delhi yields only the delhi proposal."""

        chennai_devs, chennai_edges = _cohesive_site("chennai")
        delhi_devs, delhi_edges = _cohesive_site("delhi")
        declared = SiteCatalog(sites=(
            Site(site_id="chennai", name="Chennai",
                 hostname_patterns=("chennai-*",)),
        ))
        result = derive_sites(
            chennai_devs + delhi_devs, chennai_edges + delhi_edges,
            existing_catalog=declared,
        )
        self.assertEqual(["delhi"], [s.site_id for s in result.catalog.sites])

    def test_a_derived_site_is_marked_for_confirmation(self) -> None:
        devices, edges = _cohesive_site("chennai")
        site = derive_sites(devices, edges).catalog.sites[0]
        self.assertIn("confirm", (site.description or "").lower())


class FabricTests(unittest.TestCase):
    """Shared devices with no premises of their own."""

    def _estate(self):
        """Two cohesive branches, plus a hub that touches both evenly and a
        WAN pair that only mesh unresolved peers."""

        chennai, chennai_e = _cohesive_site("chennai")
        delhi, delhi_e = _cohesive_site("delhi")
        hub = [DerivedDevice(f"id:inet-{n}", f"inet-{n}") for n in ("a", "b")]
        wan = [DerivedDevice(f"id:wan-pe{n}", f"wan-pe{n}") for n in (1, 2)]
        edges = chennai_e + delhi_e + [
            # inet-a reaches BOTH sites, one link each — no lean.
            _edge("id:inet-a", "chennai-branch-core"),
            _edge("id:inet-a", "delhi-branch-core"),
            _edge("id:inet-b", "chennai-branch-fw"),
            _edge("id:inet-b", "delhi-branch-fw"),
            # wan peers only unresolved addresses; no internal cohesion.
            _edge("id:wan-pe1", "10.255.0.2"),
            _edge("id:wan-pe2", "10.255.0.1"),
        ]
        return chennai + delhi + hub + wan, edges

    def test_a_hub_that_spans_sites_is_not_made_a_site(self) -> None:
        devices, edges = self._estate()
        derived = {s.site_id for s in derive_sites(devices, edges).catalog.sites}
        self.assertNotIn("inet", derived)
        self.assertEqual({"chennai", "delhi"}, derived)

    def test_a_mesh_with_no_internal_cohesion_is_not_a_site(self) -> None:
        # wan-pe* never connect to each other — a premises would.
        devices, edges = self._estate()
        derived = {s.site_id for s in derive_sites(devices, edges).catalog.sites}
        self.assertNotIn("wan", derived)

    def test_an_evenly_spread_device_is_left_unidentified(self) -> None:
        """inet-a touches chennai and delhi one link each. There is no
        closest, so it stays unplaced rather than assigned by a coin-flip."""

        devices, edges = self._estate()
        result = derive_sites(devices, edges)
        self.assertIn("id:inet-a", result.fabric_unplaced)
        self.assertNotIn("id:inet-a", result.fabric_placements)

    def test_a_device_that_leans_one_way_is_placed_there(self) -> None:
        """Proximity is the real signal: a shared device whose links
        clearly favour one site takes it."""

        chennai, chennai_e = _cohesive_site("chennai")
        delhi, delhi_e = _cohesive_site("delhi")
        leaning = [DerivedDevice("id:hub", "hub-1")]
        edges = chennai_e + delhi_e + [
            _edge("id:hub", "chennai-branch-core"),
            _edge("id:hub", "chennai-branch-fw"),   # 2 to chennai
            _edge("id:hub", "delhi-branch-core"),    # 1 to delhi
        ]
        result = derive_sites(chennai + delhi + leaning, edges)
        # "hub" is a singleton prefix, so it is never its own site; it is a
        # placeable shared device.
        self.assertEqual("chennai", result.fabric_placements.get("id:hub"))


class RendererIntegrationTests(unittest.TestCase):
    """The wiring: an un-curated multi-site estate now draws as many sites
    instead of one blob, without a catalog being declared at all."""

    def _snapshot(self):
        from founderos_atlas.topology.snapshot import content_address
        from founderos_atlas.topology.snapshot import TopologySnapshot

        devices, edges = [], []
        for city in ("chennai", "delhi", "mumbai"):
            for role in ("core", "fw", "sw", "access"):
                devices.append({
                    "device_id": f"frr:{city}-branch-{role}",
                    "hostname": f"{city}-branch-{role}",
                    "management_ip": "10.0.0.1", "vendor": "frr",
                    "platform": "FRRouting", "os_name": "FRRouting",
                    "os_version": "8.4", "interfaces": [],
                    "serial_number": None, "metadata": {},
                })
            for role in ("fw", "sw", "access"):
                edges.append({
                    "local_device_id": f"frr:{city}-branch-core",
                    "local_interface": "eth1",
                    "remote_hostname": f"{city}-branch-{role}",
                    "remote_interface": "eth0", "protocol": "lldp",
                    "metadata": {},
                })
        devices = tuple(devices)
        edges = tuple(edges)
        sid = content_address(
            created_at=None, devices=devices, edges=edges,
            warnings=(), metadata={},
        )
        return TopologySnapshot(
            snapshot_id=sid, created_at=None,
            devices=devices, edges=edges, warnings=(), metadata={},
        )

    def test_uncurated_estate_draws_as_many_sites_not_one_blob(self) -> None:
        from founderos_atlas.visualization.renderer import TopologyRenderer

        renderer = TopologyRenderer(self._snapshot(), site_catalog=None)
        view = renderer.site_view(renderer.elements())
        names = sorted(
            s.get("label") or s.get("display_label") for s in view["sites"]
        )
        self.assertIn("Chennai", names)
        self.assertIn("Delhi", names)
        self.assertIn("Mumbai", names)
        # Nothing landed in "Site not identified": every device is
        # conventionally named and cohesively wired.
        self.assertNotIn("__none__", set(view["membership"].values()))


class NoEvidenceTests(unittest.TestCase):
    def test_without_adjacency_every_cluster_is_a_site(self) -> None:
        """No edges means no evidence to call anything fabric, so a naming
        convention alone still yields sites — the common case of a capture
        with hostnames but no LLDP."""

        devices = [
            DerivedDevice(f"id:{c}-{r}", f"{c}-branch-{r}")
            for c in ("chennai", "delhi") for r in ("core", "fw")
        ]
        result = derive_sites(devices)
        self.assertEqual(
            {"chennai", "delhi"},
            {s.site_id for s in result.catalog.sites},
        )


if __name__ == "__main__":
    unittest.main()
