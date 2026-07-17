"""Acceptance tests for PR-037A — Enterprise Federation (UNITY).

One enterprise, many observation points: profiles contribute
observations, the federation layer builds one canonical Enterprise Graph
(reusing the PR-033 identity engine), every merge is explainable with
deterministic evidence and documented confidence, observations and
provenance are never destroyed, unknown boundaries stay visible, and
All Networks becomes a working enterprise scope for topology, inventory,
prediction, and path intelligence.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.enterprise import ScopeContribution
from founderos_atlas.federation import (
    build_enterprise_graph,
    build_enterprise_snapshot,
    enterprise_scope_dir,
    get_enterprise_inventory,
    merge_observations,
    resolve_canonical_device,
    search_enterprise,
)
from founderos_atlas.path_intelligence import investigate_path
from founderos_atlas.prediction import ChangeRequest, predict
from founderos_atlas.visualization import TOPOLOGY_VISUAL_STYLE_MARKER

from tests.test_atlas_transport import PASSWORD
from tests.test_multihop_discovery import ScriptedNetwork
from tests.test_profile_isolation import (
    FIXED,
    add_profile,
    make_service,
    run_discover,
    scope_dir,
)
from tests.test_unified_pipeline import full_outputs


NOW = "2026-07-11T08:00:00+00:00"


def device(
    hostname: str,
    ip: str,
    *,
    serial: str | None = None,
    interfaces: tuple[tuple[str, str], ...] = (("Gi0/1", "up"),),
) -> dict:
    return {
        "device_id": f"{hostname}@{ip}",
        "hostname": hostname,
        "management_ip": ip,
        "platform": "IOSv",
        "serial_number": serial,
        "interfaces": [
            {"name": name, "status": status} for name, status in interfaces
        ],
    }


def contribution(
    profile_id: str,
    devices: list[dict],
    edges: list[dict] = (),
    *,
    observed_at: str | None = "2026-07-11T07:00:00+00:00",
    run_id: str | None = None,
    domain: str | None = None,
) -> ScopeContribution:
    return ScopeContribution(
        profile_id=profile_id,
        profile_name=profile_id.replace("-", " ").title(),
        snapshot={"snapshot_id": "test", "devices": devices, "edges": list(edges)},
        run_id=run_id or f"run-{profile_id}",
        observed_at=observed_at,
        domain_hint=domain,
    )


def edge(local_id: str, local_if: str, remote: str, remote_if: str | None) -> dict:
    return {
        "local_device_id": local_id,
        "local_interface": local_if,
        "remote_hostname": remote,
        "remote_interface": remote_if,
        "protocol": "cdp",
    }


class MergeRuleTests(unittest.TestCase):
    def test_routing_and_interface_evidence_survives_federation(self) -> None:
        local = device("R1", "10.0.0.1", serial="SER-R1")
        local["metadata"] = {
            "routing_evidence": {
                "ospf_adjacencies": [{
                    "peer_address": "10.0.0.2",
                    "state": "full",
                    "area": "0",
                    "source": "show ip ospf neighbor",
                }],
                "bgp_sessions": [],
            }
        }
        local["interfaces"][0]["metadata"] = {"vrf": "WAN"}
        observed_edge = edge(local["device_id"], "Gi0/1", "R2", "Gi0/1")
        observed_edge["protocol"] = "ospf"
        observed_edge["metadata"] = {"state": "full", "area": "0"}

        graph = build_enterprise_graph((
            contribution("hyd", [local, device("R2", "10.0.0.2")], [observed_edge]),
        ))
        snapshot = build_enterprise_snapshot(graph)
        rendered = next(item for item in snapshot.devices if item["hostname"] == "R1")
        self.assertEqual(
            "full",
            rendered["metadata"]["routing_evidence"]["ospf_adjacencies"][0]["state"],
        )
        self.assertEqual("WAN", rendered["interfaces"][0]["metadata"]["vrf"])
        federated_edge = next(item for item in snapshot.edges if item["protocol"] == "ospf")
        self.assertEqual("0", federated_edge["metadata"]["area"])
        self.assertEqual(
            "full", federated_edge["metadata"]["observations"][0]["metadata"]["state"]
        )

    def test_same_serial_across_profiles_merges(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution("hyd", [device("GW", "10.0.9.9", serial="SER-1")]),
                contribution("sec", [device("GW", "172.16.9.9", serial="SER-1")]),
            )
        )
        self.assertEqual(1, graph.device_count)
        self.assertEqual(2, graph.observation_count)
        merged = graph.devices[0]
        self.assertEqual(("Hyd", "Sec"), merged.profile_names)
        self.assertEqual(["10.0.9.9", "172.16.9.9"], list(merged.management_ips))

    def test_same_hostname_alone_never_merges(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution("hyd", [device("SW1", "10.0.0.2")]),
                contribution("sec", [device("SW1", "172.16.0.2")]),
            )
        )
        self.assertEqual(2, graph.device_count)

    def test_same_ip_alone_never_merges(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution("hyd", [device("SW1", "10.0.0.2")]),
                contribution("sec", [device("FW9", "10.0.0.2")]),
            )
        )
        self.assertEqual(2, graph.device_count)

    def test_hostname_and_ip_merge_only_inside_a_declared_domain(self) -> None:
        matching = (
            contribution("hyd", [device("SW1", "10.0.0.2")], domain="corp"),
            contribution("sec", [device("SW1", "10.0.0.2")], domain="corp"),
        )
        graph = build_enterprise_graph(matching)
        self.assertEqual(1, graph.device_count)
        without_domain = (
            contribution("hyd", [device("SW1", "10.0.0.2")]),
            contribution("sec", [device("SW1", "10.0.0.2")]),
        )
        graph = build_enterprise_graph(without_domain)
        self.assertEqual(2, graph.device_count)
        # Never-merged twins keep DISTINCT enterprise ids — separate
        # objects, never silently collapsed by an id collision.
        ids = {item.enterprise_id for item in graph.devices}
        self.assertEqual(2, len(ids))

    def test_merge_decisions_explain_why_with_confidence(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution("hyd", [device("GW", "10.0.9.9", serial="SER-1")]),
                contribution("sec", [device("GW", "172.16.9.9", serial="SER-1")]),
                contribution("lon", [device("R9", "192.168.1.1")]),
            )
        )
        merged = next(d for d in graph.merge_decisions if d.merged)
        self.assertEqual(2, merged.observation_count)
        self.assertIn("serial number", merged.reason)
        self.assertIn("SER-1", merged.evidence[0])
        self.assertEqual(95, merged.confidence_percent)
        single = next(d for d in graph.merge_decisions if not d.merged)
        self.assertIn("Single observation", single.reason)
        self.assertLess(single.confidence, merged.confidence)
        self.assertLessEqual(
            max(d.confidence for d in graph.merge_decisions), 0.95
        )

    def test_corroborated_merge_has_lower_confidence_than_serial(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution("hyd", [device("SW1", "10.0.0.2")], domain="corp"),
                contribution("sec", [device("SW1", "10.0.0.2")], domain="corp"),
            )
        )
        decision = graph.merge_decisions[0]
        self.assertTrue(decision.merged)
        self.assertIn("administrative", decision.reason)
        self.assertEqual(75, decision.confidence_percent)

    def test_merge_observations_api(self) -> None:
        devices, decisions = merge_observations(
            (
                contribution("hyd", [device("GW", "10.0.9.9", serial="SER-1")]),
                contribution("sec", [device("GW", "172.16.9.9", serial="SER-1")]),
            )
        )
        self.assertEqual(1, len(devices))
        self.assertTrue(decisions[0].merged)


class ProvenanceTests(unittest.TestCase):
    def test_every_observation_is_preserved_with_provenance(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution(
                    "hyd",
                    [device("GW", "10.0.9.9", serial="SER-1")],
                    observed_at="2026-07-11T06:00:00+00:00",
                    run_id="run-7",
                ),
                contribution(
                    "sec",
                    [device("GW", "172.16.9.9", serial="SER-1")],
                    observed_at="2026-07-11T07:00:00+00:00",
                    run_id="run-9",
                ),
            )
        )
        observations = graph.devices[0].observations
        self.assertEqual(2, len(observations))
        by_profile = {item.profile_id: item for item in observations}
        self.assertEqual("run-7", by_profile["hyd"].run_id)
        self.assertEqual("2026-07-11T06:00:00+00:00", by_profile["hyd"].observed_at)
        self.assertEqual("10.0.9.9", by_profile["hyd"].management_ip)
        self.assertEqual("run-9", by_profile["sec"].run_id)

    def test_inventory_rows_carry_merge_and_observation_provenance(self) -> None:
        graph = build_enterprise_graph(
            (
                contribution("hyd", [device("GW", "10.0.9.9", serial="SER-1")]),
                contribution(
                    "sec",
                    [device("GW", "172.16.9.9", serial="SER-1")],
                    observed_at="2026-07-11T07:30:00+00:00",
                ),
            )
        )
        rows = get_enterprise_inventory(graph)
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertTrue(row["merged"])
        self.assertEqual(2, row["observation_count"])
        self.assertEqual(["Hyd", "Sec"], row["observed_by"])
        self.assertEqual("2026-07-11T07:30:00+00:00", row["last_seen"])
        self.assertEqual(95, row["merge_confidence_percent"])
        self.assertIn("serial number", row["merge_reason"])
        self.assertEqual(2, len(row["observations"]))

    def test_interfaces_merge_with_newest_state_and_provenance(self) -> None:
        older = contribution(
            "hyd",
            [device("GW", "10.0.9.9", serial="SER-1",
                    interfaces=(("Gi0/1", "up"),))],
            observed_at="2026-07-11T06:00:00+00:00",
        )
        newer = contribution(
            "sec",
            [device("GW", "172.16.9.9", serial="SER-1",
                    interfaces=(("Gi0/1", "administratively down"), ("Gi0/2", "up")))],
            observed_at="2026-07-11T07:00:00+00:00",
        )
        graph = build_enterprise_graph((older, newer))
        interfaces = graph.interfaces[graph.devices[0].enterprise_id]
        by_name = {item.name: item for item in interfaces}
        self.assertEqual({"Gi0/1", "Gi0/2"}, set(by_name))
        # Newest observation wins conflicting state; both observers listed.
        self.assertEqual("administratively down", by_name["Gi0/1"].status)
        self.assertEqual(("Hyd", "Sec"), by_name["Gi0/1"].observed_by)
        self.assertEqual(("Sec",), by_name["Gi0/2"].observed_by)


class LinkAndBoundaryTests(unittest.TestCase):
    def two_labs(self) -> tuple[ScopeContribution, ScopeContribution]:
        hyd = contribution(
            "hyd",
            [
                device("A1", "10.0.0.1", serial="SER-A1",
                       interfaces=(("Gi0/1", "up"), ("Gi0/2", "up"))),
                device("GW", "10.0.9.9", serial="SER-GW"),
            ],
            [
                edge("A1@10.0.0.1", "Gi0/2", "GW", "Gi0/1"),
            ],
        )
        sec = contribution(
            "sec",
            [
                device("B1", "10.0.1.1", serial="SER-B1"),
                device("GW", "10.0.9.9", serial="SER-GW"),
            ],
            [
                edge("B1@10.0.1.1", "Gi0/1", "GW", "Gi0/2"),
            ],
        )
        return hyd, sec

    def test_cross_profile_topology_through_a_merged_device(self) -> None:
        graph = build_enterprise_graph(self.two_labs())
        self.assertEqual(3, graph.device_count)  # A1, B1, one GW
        self.assertEqual(2, len(graph.links))
        self.assertTrue(all(link.cross_profile for link in graph.links))
        gw = next(d for d in graph.devices if d.hostname == "GW")
        endpoints = {
            (link.local_hostname, link.remote_hostname) for link in graph.links
        }
        self.assertIn(("A1", "GW"), endpoints)
        self.assertIn(("B1", "GW"), endpoints)
        self.assertEqual(("Hyd", "Sec"), gw.profile_names)

    def test_links_never_resolve_hostnames_across_profiles(self) -> None:
        """A neighbor NAME in one profile must not attach to another
        profile's device — that would invent connectivity from name-only
        evidence."""

        hyd = contribution(
            "hyd",
            [device("A1", "10.0.0.1", serial="SER-A1")],
            [edge("A1@10.0.0.1", "Gi0/1", "CORE", None)],
        )
        sec = contribution(
            "sec",
            [device("CORE", "172.16.0.1", serial="SER-CORE")],
        )
        graph = build_enterprise_graph((hyd, sec))
        link = graph.links[0]
        self.assertTrue(link.is_boundary)
        self.assertIsNone(link.remote_enterprise_id)
        self.assertEqual(1, len(graph.boundaries))
        self.assertTrue(
            any("never discovered directly" in item for item in graph.unknowns)
        )

    def test_unknown_boundaries_stay_visible(self) -> None:
        hyd = contribution(
            "hyd",
            [device("A1", "10.0.0.1", serial="SER-A1")],
            [edge("A1@10.0.0.1", "Gi0/3", "MYSTERY-FW", None)],
        )
        graph = build_enterprise_graph((hyd,))
        self.assertEqual(1, len(graph.boundaries))
        boundary = graph.boundaries[0]
        self.assertEqual("MYSTERY-FW", boundary.remote_hostname)
        # Boundaries are links, never inventory.
        self.assertEqual(1, graph.device_count)

    def test_link_observations_record_which_profile_saw_them(self) -> None:
        graph = build_enterprise_graph(self.two_labs())
        for link in graph.links:
            self.assertTrue(link.observations)
            self.assertTrue(link.observed_by)


class EnterpriseSnapshotTests(unittest.TestCase):
    def test_snapshot_is_content_addressed_and_deterministic(self) -> None:
        labs = LinkAndBoundaryTests().two_labs()
        first = build_enterprise_snapshot(build_enterprise_graph(labs))
        second = build_enterprise_snapshot(build_enterprise_graph(labs))
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )
        self.assertTrue(first.snapshot_id.startswith("atlas-topology:"))
        self.assertTrue(first.metadata["enterprise"])

    def test_snapshot_devices_are_canonical_with_provenance(self) -> None:
        snapshot = build_enterprise_snapshot(
            build_enterprise_graph(LinkAndBoundaryTests().two_labs())
        )
        gw = next(
            dict(entry) for entry in snapshot.devices
            if entry["hostname"] == "GW"
        )
        metadata = dict(gw["metadata"])
        self.assertEqual(["Hyd", "Sec"], list(metadata["observed_by"]))
        self.assertEqual(2, metadata["observation_count"])
        self.assertEqual(0.95, metadata["merge_confidence"])
        self.assertEqual(gw["device_id"], metadata["enterprise_id"])

    def test_enterprise_path_investigation_crosses_profiles(self) -> None:
        snapshot = build_enterprise_snapshot(
            build_enterprise_graph(LinkAndBoundaryTests().two_labs())
        ).to_dict()
        result = investigate_path("A1", "B1", snapshot=snapshot, generated_at=NOW)
        self.assertEqual("connected", result.status)
        self.assertEqual(("A1", "GW", "B1"), result.path)

    def test_enterprise_prediction_blast_radius_crosses_profiles(self) -> None:
        snapshot = build_enterprise_snapshot(
            build_enterprise_graph(LinkAndBoundaryTests().two_labs())
        ).to_dict()
        request = ChangeRequest(
            request_id="cr-ent",
            change_type="shutdown-interface",
            target_device="GW",
            target_object="Gi0/1",
            requested_at=NOW,
        )
        prediction = predict(request, snapshot=snapshot, generated_at=NOW)
        described = json.dumps(prediction.to_dict())
        # Shutting the Hyderabad-facing interface of the shared gateway
        # affects the OTHER observation point's side of the enterprise.
        self.assertIn("A1", described)
        self.assertLessEqual(prediction.confidence.percent, 95)


class ResolveAndSearchTests(unittest.TestCase):
    def graph(self):
        return build_enterprise_graph(
            (
                contribution("hyd", [device("GW", "10.0.9.9", serial="SER-1")]),
                contribution("sec", [device("GW", "172.16.9.9", serial="SER-1")]),
                contribution("hyd2", [device("SW1", "10.0.0.2")]),
                contribution("sec2", [device("SW1", "172.16.0.2")]),
            )
        )

    def test_resolve_by_hostname_ip_and_serial(self) -> None:
        graph = self.graph()
        for query in ("GW", "gw", "10.0.9.9", "172.16.9.9", "SER-1"):
            found, problem = resolve_canonical_device(graph, query)
            self.assertIsNone(problem, query)
            self.assertEqual("GW", found.hostname)

    def test_ambiguous_names_are_reported_not_guessed(self) -> None:
        found, problem = resolve_canonical_device(self.graph(), "SW1")
        self.assertIsNone(found)
        self.assertIn("ambiguous", problem)
        self.assertIn("2", problem)

    def test_unknown_query_is_honest(self) -> None:
        found, problem = resolve_canonical_device(self.graph(), "GHOST")
        self.assertIsNone(found)
        self.assertIn("no enterprise device matches", problem)

    def test_search_is_deterministic_substring(self) -> None:
        results = search_enterprise(self.graph(), "sw1")
        self.assertEqual(2, len(results))
        self.assertEqual((), search_enterprise(self.graph(), "zz-nothing"))


def hyderabad_network() -> ScriptedNetwork:
    """A1 -- A2 and A1 -- GW (the shared gateway)."""

    return ScriptedNetwork(
        {
            "10.0.0.1": full_outputs(
                "A1", "10.0.0.1", (("A2", "10.0.0.2"), ("GW", "10.0.9.9"))
            ),
            "10.0.0.2": full_outputs("A2", "10.0.0.2", (("A1", "10.0.0.1"),)),
            "10.0.9.9": full_outputs("GW", "10.0.9.9", (("A1", "10.0.0.1"),)),
        }
    )


def secunderabad_network() -> ScriptedNetwork:
    """B1 -- GW: the same physical gateway observed from another site."""

    return ScriptedNetwork(
        {
            "10.0.1.1": full_outputs("B1", "10.0.1.1", (("GW", "10.0.9.9"),)),
            "10.0.9.9": full_outputs("GW", "10.0.9.9", (("B1", "10.0.1.1"),)),
        }
    )


class EnterpriseGuiTests(unittest.TestCase):
    """The CML scenario: two labs discovered, All Networks becomes usable."""

    def build_world(self, workdir: Path):
        from founderos_atlas.web import create_app

        service = make_service(workdir)
        add_profile(service, "Hyderabad", "10.0.0.1")
        add_profile(service, "Secunderabad", "10.0.1.1")
        run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
        run_discover(
            workdir, service, secunderabad_network(), "Secunderabad",
            FIXED + timedelta(minutes=30),
        )
        app = create_app(
            profile_service=service,
            output_dir=workdir,
            history_root=workdir / ".atlas" / "history",
        )
        app.config.update(TESTING=True)
        return service, app.test_client()

    def test_dashboard_shows_the_enterprise_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/?scope=all").data
            # PR-040: All Networks lands on MISSION; the enterprise
            # summary lives in its Enterprise Health card.
            self.assertIn(b"Enterprise Health", page)
            self.assertIn(b"Canonical devices", page)
            self.assertIn(b"Hyderabad", page)
            self.assertIn(b"Secunderabad", page)
            self.assertNotIn(PASSWORD.encode(), page)

    def test_enterprise_topology_and_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/topology?scope=all").data
            # Inventory contains ALL devices; the shared gateway merged.
            for hostname in (b"A1", b"A2", b"B1", b"GW"):
                self.assertIn(hostname, page)
            self.assertIn(b"Enterprise Knowledge", page)  # PR-043.10 wording
            self.assertIn(b"Merge Decisions", page)
            self.assertIn(b"serial number", page)
            self.assertIn(b"95%", page)
            self.assertIn(b"Observed by", page)
            # ONE enterprise topology viewer exists and spans both labs.
            self.assertIn(b".atlas/enterprise/atlas_topology.html", page)
            viewer = (
                workdir / ".atlas" / "enterprise" / "atlas_topology.html"
            ).read_text("utf-8")
            for hostname in ("A1", "A2", "B1", "GW"):
                self.assertIn(hostname, viewer)
            self.assertNotIn(PASSWORD, viewer)
            self.assertNotIn(PASSWORD.encode(), page)

    def test_cached_enterprise_viewer_refreshes_when_its_style_marker_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            self.assertEqual(200, client.get("/topology?scope=all").status_code)
            enterprise = enterprise_scope_dir(workdir)
            viewer = enterprise / "atlas_topology.html"
            snapshot_before = (enterprise / "topology_snapshot.json").read_bytes()
            viewer.write_text("<html>old enterprise style</html>", encoding="utf-8")

            response = client.get("/topology?scope=all")

            self.assertEqual(200, response.status_code)
            refreshed = viewer.read_text(encoding="utf-8")
            self.assertIn(TOPOLOGY_VISUAL_STYLE_MARKER, refreshed)
            self.assertIn("A1", refreshed)
            self.assertIn("B1", refreshed)
            self.assertEqual(
                snapshot_before,
                (enterprise / "topology_snapshot.json").read_bytes(),
            )

    def test_enterprise_inventory_merges_the_shared_gateway_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/topology?scope=all")
            snapshot = json.loads(
                (
                    workdir / ".atlas" / "enterprise" / "topology_snapshot.json"
                ).read_text("utf-8")
            )
            hostnames = [entry["hostname"] for entry in snapshot["devices"]]
            self.assertEqual(1, hostnames.count("GW"))
            self.assertEqual(4, len(hostnames))  # A1, A2, B1, GW

    def test_enterprise_path_investigation_crosses_the_labs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/paths?scope=all").data
            self.assertIn(b"Enterprise scope", page)
            names = {
                item["value"] for item in client.get(
                    "/api/entities?kind=device&scope=all"
                ).get_json()["results"]
            }
            self.assertIn("B1", names)
            response = client.post(
                "/paths/run",
                data={"source": "A2", "destination": "B1"},
                follow_redirects=True,
            )
            self.assertIn(b"Connected", response.data)
            self.assertIn(b"GW", response.data)
            report = json.loads(
                (
                    workdir / ".atlas" / "enterprise"
                    / "path_investigation_report.json"
                ).read_text("utf-8")
            )
            self.assertEqual(["A2", "A1", "GW", "B1"], report["path"])
            self.assertEqual("all", report["profile_id"])
            self.assertNotIn(PASSWORD.encode(), response.data)

    def test_enterprise_prediction_works_at_all_networks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            page = client.get("/predict?scope=all").data
            self.assertIn(b"Enterprise scope", page)
            names = {
                item["value"] for item in client.get(
                    "/api/entities?kind=device&scope=all"
                ).get_json()["results"]
            }
            self.assertIn("GW", names)
            response = client.post(
                "/predict/run",
                data={"device": "GW", "interface": "Gi0/1"},
                follow_redirects=True,
            )
            self.assertIn(b"Risk:", response.data)
            self.assertTrue(
                (
                    workdir / ".atlas" / "enterprise" / "prediction_report.json"
                ).is_file()
            )
            self.assertNotIn(PASSWORD.encode(), response.data)

    def test_profile_isolation_is_untouched_by_federation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = self.build_world(workdir)
            profiles = {p.name: p.profile_id for p in service.list_profiles()}
            hyd_snapshot = scope_dir(
                workdir, profiles["Hyderabad"]
            ) / "topology_snapshot.json"
            before = hyd_snapshot.read_bytes()
            # Exercise every enterprise page.
            client.get("/?scope=all")
            client.get("/topology?scope=all")
            client.get("/predict?scope=all")
            client.get("/paths?scope=all")
            client.post(
                "/paths/run",
                data={"source": "A2", "destination": "B1"},
                follow_redirects=True,
            )
            self.assertEqual(before, hyd_snapshot.read_bytes())
            # Scoped pages still work exactly as before.
            page = client.get(f"/paths?scope={profiles['Hyderabad']}").data
            self.assertNotIn(b"Enterprise scope", page)
            names = {
                item["value"] for item in client.get(
                    f"/api/entities?kind=device&scope={profiles['Hyderabad']}"
                ).get_json()["results"]
            }
            self.assertIn("A1", names)
            self.assertNotIn("B1", names)  # isolation intact

    def test_enterprise_artifacts_live_in_the_enterprise_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = self.build_world(workdir)
            client.get("/topology?scope=all")
            enterprise = enterprise_scope_dir(workdir)
            self.assertTrue((enterprise / "topology_snapshot.json").is_file())
            self.assertTrue((enterprise / "enterprise_graph.json").is_file())
            graph = json.loads(
                (enterprise / "enterprise_graph.json").read_text("utf-8")
            )
            self.assertEqual(4, graph["device_count"])
            self.assertEqual(5, graph["observation_count"])
            self.assertEqual(1, graph["merged_device_count"])
            self.assertNotIn(
                PASSWORD, (enterprise / "enterprise_graph.json").read_text("utf-8")
            )


if __name__ == "__main__":
    unittest.main()
