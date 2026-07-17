"""Navigation, deep-linking, and contextual-action infrastructure.

Route generation, scope preservation in copied URLs, dead-scope
behavior, link integrity across every server-rendered primary page,
search ranking, and the complete policy-failure workflow:
policy failure → evidence → configuration → prediction → Compass.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world


PRIMARY_PAGES = (
    "/", "/topology", "/timeline", "/history", "/changes", "/configuration",
    "/evidence", "/policy", "/advisor", "/paths", "/predict", "/compass",
    "/incidents", "/discovery", "/profiles", "/credentials", "/settings",
    "/console",
)

FAILING_FRR_CONFIG = (
    "frr version 9.1\n"
    "hostname GW\n"
    "interface lo\n"
    " ip address 10.0.9.9/32\n"
    "!\n"
)


def seed_policy_memory(workdir: Path) -> tuple[str, str]:
    """A stored configuration for GW that fails at least one policy.

    Returns ``(device_id, config_sha)`` for exact-record assertions."""

    from founderos_atlas.enterprise_memory import (
        DiscoverySession,
        EnterpriseMemoryStore,
    )
    from founderos_atlas.workspace import profile_scope

    scope = profile_scope(workdir, "hyderabad", "Hyderabad")
    store = EnterpriseMemoryStore(scope.output_dir / "enterprise-memory")
    store.begin_session(
        DiscoverySession(
            session_id="sess-nav",
            network="Hyderabad",
            profile_id="hyderabad",
            profile_name="Hyderabad",
            started_at="2026-07-14T10:00:00+00:00",
        )
    )
    device_id = "cisco-ios:gw"
    record = store.store_evidence(
        device_id=device_id,
        hostname="GW",
        command="show running-config",
        output=FAILING_FRR_CONFIG,
        discovery_session="sess-nav",
        transport="ssh",
        platform="FRRouting",
    )
    store.store_configuration(
        device_id=device_id,
        hostname="GW",
        discovery_session="sess-nav",
        running_config=FAILING_FRR_CONFIG,
        platform="FRRouting",
    )
    # Configuration Memory is what the /configuration pages read.
    from founderos_atlas.config_memory import ConfigMemoryStore

    ConfigMemoryStore(scope.output_dir / "config-memory").record(
        FAILING_FRR_CONFIG,
        device_id=device_id,
        hostname="GW",
        network="Hyderabad",
        profile_id="hyderabad",
        discovery_session="sess-nav",
        collected_at="2026-07-14T10:00:05+00:00",
        platform="FRRouting",
    )
    return device_id, record.content_sha256


class LinkingModelTests(unittest.TestCase):
    def test_every_entity_kind_produces_a_scoped_url(self) -> None:
        from founderos_atlas.web.linking import entity_url

        cases = {
            "device": dict(device_id="ent:gw:10.0.9.9"),
            "interface": dict(device_id="ent:gw:10.0.9.9", interface="Gi0/1"),
            "site": dict(site_id="hyderabad"),
            "policy": dict(policy_id="STD-NTP-001"),
            "policy_failure": dict(policy_id="STD-NTP-001", hostname="GW"),
            "discovery_run": dict(record_id="2026-07-10_08-00-00"),
            "change": {},
            "incident": {},
            "evidence_device": dict(device_id="cisco-ios:gw"),
            "evidence_record": dict(device_id="cisco-ios:gw", sha="ab" * 32),
            "configuration": dict(device_id="cisco-ios:gw"),
            "prediction": {},
            "plan": dict(plan_id="window"),
            "investigation": {},
            "topology_focus": dict(focus="GW"),
        }
        for kind, ids in cases.items():
            url = entity_url(kind, scope_id="labs", **ids)
            self.assertIn("scope=labs", url, kind)
        with self.assertRaises(ValueError):
            entity_url("galaxy")
        with self.assertRaises(ValueError):
            entity_url("device")  # missing device_id

    def test_actions_are_canonically_ordered_and_explain_unavailability(self) -> None:
        from founderos_atlas.web.linking import (
            ACTION_ORDER,
            EntityAction,
            device_entity_actions,
        )

        actions = device_entity_actions(
            device_id="ent:gw:10.0.9.9", hostname="GW", scope_id="all",
            ssh_target=None,
        )
        keys = [action.key for action in actions]
        self.assertEqual(keys, [key for key in ACTION_ORDER if key in keys])
        ssh = next(action for action in actions if action.key == "ssh")
        self.assertFalse(ssh.available)
        self.assertIn("no verified SSH endpoint", ssh.reason)
        with self.assertRaises(ValueError):
            EntityAction(key="ssh", available=False)  # reason required

    def test_every_generated_action_href_carries_the_scope(self) -> None:
        from founderos_atlas.web.linking import device_entity_actions

        for action in device_entity_actions(
            device_id="ent:gw:10.0.9.9", hostname="GW", scope_id="labs",
            ssh_target={"eligible": True, "device_id": "cisco-ios:gw"},
        ):
            if action.available and action.href and action.key != "ssh":
                self.assertIn("scope=labs", action.href, action.key)


class ScopeSafetyTests(unittest.TestCase):
    def test_copied_scoped_url_reopens_the_same_scope_in_a_fresh_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            # First browser looks at Hyderabad and copies a link.
            client.get("/?scope=hyderabad")
            copied = "/topology?scope=hyderabad"
            # A FRESH browser (new session) whose session remembers a
            # different scope must still open the named scope.
            fresh = client.application.test_client()
            fresh.get("/?scope=secunderabad")
            page = fresh.get(copied).data
            self.assertIn(b"Topology \xe2\x80\x94 Hyderabad", page)

    def test_dead_scope_is_answered_explicitly_never_silently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            response = client.get("/?scope=ghost-network", follow_redirects=True)
            self.assertEqual(200, response.status_code)
            page = response.data.decode("utf-8")
            self.assertIn("no longer exists", page)
            self.assertIn("Mission — Enterprise", page)

    def test_device_page_is_addressable_by_stable_hostname(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            page = client.get("/devices/GW?scope=all")
            self.assertEqual(200, page.status_code)
            self.assertIn(b"canonical enterprise device", page.data)
            missing = client.get("/devices/never-existed?scope=all")
            self.assertEqual(404, missing.status_code)


class LinkIntegrityTests(unittest.TestCase):
    _HREF = re.compile(r'href="([^"]+)"')

    def test_every_internal_link_on_every_primary_page_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            seed_policy_memory(workdir)
            _, client = build_world(workdir)
            seen: set[str] = set()
            for page_path in PRIMARY_PAGES:
                page = client.get(page_path, follow_redirects=True)
                self.assertLess(page.status_code, 500, page_path)
                html = page.data.decode("utf-8")
                for href in self._HREF.findall(html):
                    target = href.split("#", 1)[0]
                    if (
                        not target
                        or not target.startswith("/")
                        or target.startswith("//")
                        or target in seen
                    ):
                        continue
                    seen.add(target)
                    response = client.get(target, follow_redirects=True)
                    self.assertLess(
                        response.status_code, 500,
                        f"{page_path} links to {target}",
                    )
                    if not target.startswith("/artifacts/"):
                        # An artifact may honestly not exist yet; a routed
                        # page must never 404 from a rendered link.
                        self.assertNotEqual(
                            404, response.status_code,
                            f"{page_path} links to {target}",
                        )

    def test_no_page_renders_an_ambiguous_bare_view_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            seed_policy_memory(workdir)
            _, client = build_world(workdir)
            for page_path in PRIMARY_PAGES:
                html = client.get(page_path, follow_redirects=True).data.decode(
                    "utf-8"
                )
                self.assertNotRegex(
                    html, r">\s*View\s*</a>",
                    f"{page_path} renders an ambiguous 'View' link",
                )


class PolicyWorkflowTests(unittest.TestCase):
    """policy failure → evidence → configuration → prediction → Compass."""

    def test_the_complete_workflow_has_no_dead_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            device_id, sha = seed_policy_memory(workdir)
            _, client = build_world(workdir)

            policy_page = client.get("/policy?scope=all").data.decode("utf-8")
            self.assertIn("result-", policy_page)
            self.assertIn("Exact configuration", policy_page)
            self.assertIn("Predict remediation impact", policy_page)
            self.assertIn("Add remediation to Compass", policy_page)

            # Exact evidence record: the verdict's config sha addresses it.
            record = client.get(
                f"/evidence/device/{device_id}/record/{sha}?scope=all"
            )
            self.assertEqual(200, record.status_code)
            self.assertIn(b"show running-config", record.data)

            configuration = client.get(f"/configuration/{device_id}?scope=all")
            self.assertEqual(200, configuration.status_code)

            predict = client.get("/predict?scope=all&device=GW").data.decode(
                "utf-8"
            )
            self.assertIn('value="GW" selected', predict)

            # Add to Compass: the device rides through plan creation into
            # the plan page's preselected Add-a-Change form.
            created = client.post(
                "/compass/new",
                data={
                    "title": "Remediation window",
                    "maintenance_window": "Sat 02:00-04:00",
                    "engineer": "netops",
                    "device": "GW",
                    "reason": "Remediate policy: NTP",
                },
                follow_redirects=False,
            )
            self.assertEqual(302, created.status_code)
            location = created.headers["Location"]
            self.assertIn("device=GW", location)
            plan_page = client.get(location).data.decode("utf-8")
            self.assertIn('value="GW" selected', plan_page)
            self.assertIn("Remediate policy: NTP", plan_page)


class SearchExpansionTests(unittest.TestCase):
    def test_exact_device_outranks_its_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            payload = client.get("/api/search?q=GW").get_json()
            first_group = payload["groups"][0]
            self.assertEqual("devices", first_group["id"])
            self.assertEqual("GW", first_group["results"][0]["title"])

    def test_policy_failures_evidence_and_configurations_are_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            seed_policy_memory(workdir)
            _, client = build_world(workdir)
            payload = client.get("/api/search?q=GW").get_json()
            groups = {group["id"] for group in payload["groups"]}
            self.assertIn("evidence", groups)
            self.assertIn("configurations", groups)
            self.assertIn("policies", groups)
            evidence = next(
                group for group in payload["groups"] if group["id"] == "evidence"
            )
            self.assertIn("scope=", evidence["results"][0]["href"])

    def test_show_all_expands_one_group_past_the_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            seed_policy_memory(workdir)
            _, client = build_world(workdir)
            expanded = client.get(
                "/api/search?q=GW&group=policies&limit=200"
            ).get_json()
            self.assertEqual("policies", expanded.get("expanded_group"))
            self.assertEqual(
                ["policies"], [group["id"] for group in expanded["groups"]]
            )
            for group in expanded["groups"]:
                self.assertEqual(group["count"], len(group["results"]))


if __name__ == "__main__":
    unittest.main()
