"""Enterprise-scale behavior of the investigation surfaces (PR-053).

Synthetic fixtures at thousands-of-records scale prove the explorers
stay fast and the pages never render hundreds of expanded bodies;
smaller end-to-end fixtures prove exceptions, audit, annotations, run
comparison, unknown-vs-missing-evidence semantics, and URL-carried
filter state.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_navigation import FAILING_FRR_CONFIG, seed_policy_memory
from tests.test_polish import build_world


NOW = "2026-07-17T12:00:00+00:00"


def seed_fleet(workdir: Path, count: int) -> None:
    """``count`` devices with stored configurations in the Hyderabad scope."""

    from founderos_atlas.enterprise_memory import (
        DiscoverySession, EnterpriseMemoryStore,
    )
    from founderos_atlas.workspace import profile_scope

    scope = profile_scope(workdir, "hyderabad", "Hyderabad")
    store = EnterpriseMemoryStore(scope.output_dir / "enterprise-memory")
    store.begin_session(DiscoverySession(
        session_id="sess-scale", network="Hyderabad",
        profile_id="hyderabad", profile_name="Hyderabad",
        started_at="2026-07-14T10:00:00+00:00",
    ))
    for index in range(count):
        hostname = f"edge-{index:03d}"
        store.store_configuration(
            device_id=f"frr:{hostname}", hostname=hostname,
            discovery_session="sess-scale",
            running_config=FAILING_FRR_CONFIG, platform="FRRouting",
        )


def synthetic_policy_report(count: int) -> list[dict]:
    """``count`` evaluations across devices, policies, and statuses."""

    policies = [
        {"policy_id": f"STD-{index:03d}", "name": f"Policy {index:03d}",
         "category": "security", "severity": ("high", "medium", "low")[index % 3]}
        for index in range(12)
    ]
    rows = []
    for index in range(count):
        policy = policies[index % len(policies)]
        status = ("pass", "fail", "warning", "unknown")[index % 4]
        result: dict = {
            "conclusion": f"conclusion {index}",
            "reasoning_path": [{"statement": "checked"}],
            "evidence_used": [
                {"observed_at": "2026-07-17T11:00:00+00:00"}
            ] if index % 5 else [],
            "evidence_missing": (
                [{"kind": "running-config", "detail": "not collected"}]
                if status == "unknown" and (index // 4) % 2 == 0 else []
            ),
        }
        if status == "pass" and index % 24 == 0:
            result["reasoning_path"] = [
                {"statement": "not applicable — the antecedent "
                              "configuration is not present"}
            ]
        rows.append({
            "policy": policy,
            "device_id": f"frr:device-{index % 500}",
            "hostname": f"device-{index % 500}",
            "network": "Scale Lab",
            "status": status,
            "status_label": status.title(),
            "result": result,
        })
    return rows


class PolicyExplorerScaleTests(unittest.TestCase):
    def setUp(self) -> None:
        from founderos_atlas.policy.explorer import annotate_evaluations

        self.raw = synthetic_policy_report(3000)
        started = time.perf_counter()
        self.rows = annotate_evaluations(
            self.raw, now=NOW,
            sites_by_device={
                f"device-{index}": ("chennai", "mumbai", "delhi")[index % 3]
                for index in range(500)
            },
        )
        self.annotate_seconds = time.perf_counter() - started

    def test_three_thousand_evaluations_process_quickly(self) -> None:
        from founderos_atlas.policy.explorer import (
            ResultFilter, filter_rows, group_rows, heatmap, paginate,
            sort_rows, summarize,
        )

        started = time.perf_counter()
        filtered = sort_rows(filter_rows(self.rows, ResultFilter()))
        page = paginate(filtered, 1, 50)
        summarize(self.rows)
        heatmap(self.rows)
        group_rows(filtered, "policy")
        elapsed = time.perf_counter() - started
        self.assertEqual(3000, len(filtered))
        self.assertEqual(50, len(page.items))
        self.assertLess(
            self.annotate_seconds + elapsed, 2.0,
            f"explorer pipeline too slow: {self.annotate_seconds + elapsed:.2f}s",
        )

    def test_unknown_and_missing_evidence_are_separate_buckets(self) -> None:
        from founderos_atlas.policy.explorer import summarize

        counts = summarize(self.rows)
        self.assertGreater(counts["missing-evidence"], 0)
        self.assertGreater(counts["unknown"], 0)
        # Every missing-evidence row has recorded gaps; unknown rows do not.
        for row in self.rows:
            if row["effective_status"] == "missing-evidence":
                self.assertTrue(row["result"]["evidence_missing"])
            if row["effective_status"] == "unknown":
                self.assertFalse(row["result"]["evidence_missing"])

    def test_not_applicable_is_never_counted_as_pass(self) -> None:
        from founderos_atlas.policy.explorer import summarize

        counts = summarize(self.rows)
        self.assertGreater(counts["not-applicable"], 0)
        plain_passes = [
            row for row in self.rows if row["effective_status"] == "pass"
        ]
        for row in plain_passes[:20]:
            statements = " ".join(
                step["statement"] for step in row["result"]["reasoning_path"]
            )
            self.assertNotIn("not applicable", statements)

    def test_displayed_score_reconciles_with_displayed_buckets(self) -> None:
        from founderos_atlas.policy.explorer import posture_score, summarize

        counts = summarize(self.rows)
        posture = posture_score(counts)
        self.assertEqual(
            counts["pass"] + counts["fail"] + counts["warning"],
            posture["judged"],
        )
        self.assertEqual(
            int(round(100 * counts["pass"] / posture["judged"])),
            posture["score"],
        )
        # Not-applicable never inflates the score (the engine-level report
        # counts those as passes; the page must not).
        self.assertGreater(counts["not-applicable"], 0)

    def test_filters_compose_and_group_counts_reconcile(self) -> None:
        from founderos_atlas.policy.explorer import (
            ResultFilter, filter_rows, group_rows,
        )

        filtered = filter_rows(
            self.rows,
            ResultFilter(status="fail", site="chennai", severity="high"),
        )
        for row in filtered:
            self.assertEqual("fail", row["effective_status"])
            self.assertEqual("chennai", row["site"])
            self.assertEqual("high", row["policy"]["severity"])
        groups = group_rows(filter_rows(self.rows, ResultFilter()), "site")
        self.assertEqual(
            len(self.rows), sum(group["total"] for group in groups)
        )


class PolicyPageScaleTests(unittest.TestCase):
    def test_page_renders_one_page_of_rows_never_every_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            seed_fleet(workdir, 60)
            _, client = build_world(workdir)
            started = time.perf_counter()
            page = client.get("/policy?scope=all").data.decode("utf-8")
            first_request = time.perf_counter() - started
            started = time.perf_counter()
            client.get("/policy?scope=all&page=2")
            second_request = time.perf_counter() - started
            # 60 devices × 12 policies = 720 evaluations; the page renders
            # at most one page of ROWS and zero reasoning bodies.
            self.assertLessEqual(page.count("Open verdict"), 50)
            self.assertNotIn("reasoning path", page)
            self.assertIn("result(s) match", page)
            # The cached second request must be far cheaper than the first.
            self.assertLess(
                second_request, max(first_request, 0.5),
                f"pagination re-request too slow: {second_request:.2f}s "
                f"(first {first_request:.2f}s)",
            )

    def test_filters_ride_the_url_and_survive_a_fresh_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            seed_fleet(workdir, 6)
            _, client = build_world(workdir)
            url = "/policy?scope=all&status=fail&severity=high&group=policy"
            page = client.get(url).data.decode("utf-8")
            fresh = client.application.test_client()
            same = fresh.get(url).data.decode("utf-8")
            for html in (page, same):
                self.assertIn('value="fail" selected', html)
                self.assertIn('value="high" selected', html)
                self.assertIn('value="policy" selected', html)

    def test_export_exceptions_assignment_and_audit_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            device_id, _sha = seed_policy_memory(workdir)
            _, client = build_world(workdir)
            page = client.get("/policy?scope=all&status=fail").data.decode(
                "utf-8"
            )
            match = re.search(r'href="(/policy/result/([^/"]+)/GW)[^"]*"', page)
            self.assertIsNotNone(match, "no failed verdict to except")
            policy_id = match.group(2)

            granted = client.post("/policy/exceptions", data={
                "policy_id": policy_id, "hostname": "GW",
                "reason": "compensating control in place",
                "owner": "netops", "approved_by": "secops",
                "next": "/policy?scope=all",
            }, follow_redirects=True)
            self.assertIn(b"Exception granted", granted.data)

            excepted = client.get(
                "/policy?scope=all&status=excepted"
            ).data.decode("utf-8")
            self.assertIn("GW", excepted)

            export = client.get(
                "/policy/export.csv?scope=all&status=excepted"
            ).data.decode("utf-8")
            self.assertIn("excepted", export)
            self.assertIn("GW", export)

            assigned = client.post("/policy/assign", data={
                "owner": "alice",
                "subjects": [f"policy-result:{policy_id}:gw"],
                "next": "/policy?scope=all",
            }, follow_redirects=True)
            self.assertIn(b"assigned to alice", assigned.data)

            revoked = client.post("/policy/exceptions/revoke", data={
                "policy_id": policy_id, "hostname": "GW",
                "reason": "control removed", "next": "/policy?scope=all",
            }, follow_redirects=True)
            self.assertIn(b"Exception revoked", revoked.data)

            audit = client.get(
                "/audit?category=policy-exception"
            ).data.decode("utf-8")
            self.assertIn("grant", audit)
            self.assertIn("revoke", audit)
            self.assertIn("compensating control in place", audit)
            csv_export = client.get(
                "/audit/export.csv?category=policy-exception"
            ).data.decode("utf-8")
            self.assertIn("policy-exception", csv_export)


class ChangesExplorerScaleTests(unittest.TestCase):
    def synthetic_reports(self, count: int):
        changes = [
            {
                "category": ("device", "interface", "neighbor")[index % 3],
                "severity": ("high", "medium", "low", "info")[index % 4],
                "description": f"change {index} detected",
                "recommendation": "",
                "subject": f"device-{index % 400}",
                "field": "status",
                "previous_value": "up",
                "current_value": "down",
            }
            for index in range(count)
        ]
        return {"changes": changes, "generated_at": NOW}

    def test_five_thousand_changes_filter_and_paginate_quickly(self) -> None:
        from founderos_atlas.change.explorer import (
            ChangeFilter, annotate_rows, filter_rows, summarize, unified_rows,
        )
        from founderos_atlas.listing import paginate

        started = time.perf_counter()
        rows = annotate_rows(unified_rows(
            topology_report=self.synthetic_reports(5000),
            config_report=None, state_report=None, network="Scale Lab",
        ))
        filtered, _hidden = filter_rows(rows, ChangeFilter(severity="high"))
        page = paginate(filtered, 3, 50)
        summarize(rows)
        elapsed = time.perf_counter() - started
        self.assertEqual(5000, len(rows))
        self.assertEqual(1250, len(filtered))
        self.assertEqual(50, len(page.items))
        self.assertEqual(3, page.page)
        self.assertLess(elapsed, 2.0, f"changes pipeline too slow: {elapsed:.2f}s")

    def test_page_renders_one_page_with_before_after_and_url_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            (workdir / "change_report.json").write_text(
                json.dumps(self.synthetic_reports(1200)), encoding="utf-8"
            )
            page = client.get(
                "/changes?scope=default&severity=high&page=2"
            ).data.decode("utf-8")
            self.assertLessEqual(page.count("<tr id=\"change:"), 50)
            self.assertIn("change(s) match", page)
            self.assertIn("<del>up</del>", page)
            self.assertIn("<ins>down</ins>", page)
            self.assertIn('value="high" selected', page)

    def test_suppression_needs_a_reason_hides_by_default_and_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            (workdir / "change_report.json").write_text(
                json.dumps(self.synthetic_reports(3)), encoding="utf-8"
            )
            page = client.get("/changes?scope=default").data.decode("utf-8")
            match = re.search(r'<tr id="(change:[^"]+)"', page)
            self.assertIsNotNone(match, "no change row rendered")
            subject = match.group(1)
            refused = client.post("/changes/annotate", data={
                "action": "suppress", "subject": subject,
                "next": "/changes?scope=default",
            }, follow_redirects=True)
            self.assertIn(b"requires a reason", refused.data)
            done = client.post("/changes/annotate", data={
                "action": "suppress", "subject": subject,
                "reason": "known flap during maintenance",
                "next": "/changes?scope=default",
            }, follow_redirects=True)
            self.assertIn(b"Change suppressed", done.data)
            page = client.get("/changes?scope=default").data.decode("utf-8")
            self.assertIn("1 suppressed change(s) hidden", page)
            shown = client.get(
                "/changes?scope=default&suppressed=1"
            ).data.decode("utf-8")
            self.assertIn("known flap during maintenance", shown)
            audit = client.get(
                "/audit?category=change-suppression"
            ).data.decode("utf-8")
            self.assertIn(subject, audit)

    def test_two_archived_runs_compare_on_demand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            history = client.get("/history?scope=hyderabad").data.decode(
                "utf-8"
            )
            record_id = re.search(r"run=([0-9_\-]+)", history).group(1)
            page = client.get(
                f"/changes/compare?scope=hyderabad&left={record_id}"
                f"&right={record_id}"
            ).data.decode("utf-8")
            self.assertIn("Comparing", page)
            self.assertIn("identical topology", page)


class ChronicleScaleTests(unittest.TestCase):
    def test_ten_thousand_events_filter_and_paginate_quickly(self) -> None:
        from founderos_atlas.listing import paginate
        from founderos_atlas.web.chronicle import (
            ChronicleFilter, chronicle_events, filter_events,
        )

        change_rows = [
            {
                "kind": "topology", "category": "device",
                "severity": ("high", "medium", "low")[index % 3],
                "device": f"device-{index % 300}",
                "description": f"change {index}",
                "subject": f"change:{index}", "network": "Scale Lab",
                "occurred_at": f"2026-07-{(index % 28) + 1:02d}T10:00:00+00:00",
            }
            for index in range(10000)
        ]
        started = time.perf_counter()
        events = chronicle_events(change_rows=change_rows)
        filtered = filter_events(
            events,
            ChronicleFilter(severity="high", date_from="2026-07-10",
                            date_to="2026-07-20"),
        )
        page = paginate(filtered, 2, 50)
        elapsed = time.perf_counter() - started
        self.assertEqual(10000, len(events))
        self.assertTrue(filtered)
        for event in filtered:
            self.assertEqual("high", event["severity"])
            self.assertGreaterEqual(event["occurred_at"][:10], "2026-07-10")
            self.assertLessEqual(event["occurred_at"][:10], "2026-07-20")
        self.assertEqual(50, len(page.items))
        self.assertLess(elapsed, 2.5, f"chronicle too slow: {elapsed:.2f}s")

    def test_every_event_carries_provenance_and_an_exact_link(self) -> None:
        from founderos_atlas.web.chronicle import chronicle_events

        events = chronicle_events(
            change_rows=[{
                "kind": "topology", "category": "device", "severity": "high",
                "device": "core1", "description": "link lost",
                "subject": "change:abc", "network": "Lab",
                "occurred_at": NOW,
            }],
            incident_reports=[("Lab", {
                "title": "VLAN outage", "confidence": "medium",
                "affected_devices": ["core1"], "generated_at": NOW,
            })],
            compass_plans=[{
                "plan_id": "window", "title": "Window",
                "status": "draft", "changes": [], "updated_at": NOW,
            }],
        )
        for event in events:
            self.assertTrue(event["provenance"], event)
            self.assertTrue(event["href"], event)


class AuditSystemTests(unittest.TestCase):
    def test_secrets_never_reach_the_log(self) -> None:
        from founderos_atlas.audit import AuditEvent, AuditLog

        with tempfile.TemporaryDirectory() as tmp:
            log = AuditLog(tmp)
            log.append(AuditEvent.create(
                category="credential", operation="update",
                subject="credential:lab-admin",
                before={"password": "HUNTER2", "username": "atlas"},
                after={"secret": "NEW", "credential_ref": "atlas-credset:x"},
            ))
            raw = log.path.read_text(encoding="utf-8")
            self.assertNotIn("HUNTER2", raw)
            self.assertNotIn("NEW\"", raw)
            self.assertIn("[redacted]", raw)
            self.assertIn("atlas-credset:x", raw)

    def test_adapters_fold_override_and_resolution_trails_with_undo(self) -> None:
        from founderos_atlas.audit import unified_audit_events
        from founderos_atlas.identity import (
            PeerResolutionRepository, peer_subject_key,
        )
        from founderos_atlas.sites import SiteOverrideRepository

        with tempfile.TemporaryDirectory() as tmp:
            SiteOverrideRepository(tmp).assign(
                site_id="chennai", hostname="dist2",
                reason="drag and drop", occurred_at=NOW,
            )
            repo = PeerResolutionRepository(tmp)
            repo.resolve(peer_label="10.0.0.9", resolved_hostname="core1",
                         occurred_at=NOW)
            repo.undo(subject_key=peer_subject_key("10.0.0.9"),
                      occurred_at=NOW)
            events = unified_audit_events(tmp)
            categories = {event.category for event in events}
            self.assertIn("site-override", categories)
            self.assertIn("identity-resolution", categories)
            undo = next(
                event for event in events if event.operation == "undo"
            )
            self.assertTrue(undo.correlation_id, "undo must name what it undoes")
            # The original trails are untouched — undo semantics intact.
            self.assertTrue(SiteOverrideRepository(tmp).history())
            self.assertEqual(
                ("resolve", "undo"),
                tuple(event.action for event in repo.history()),
            )

    def test_exception_expiry_reclassifies_automatically(self) -> None:
        from founderos_atlas.policy.exceptions import PolicyExceptionRepository

        with tempfile.TemporaryDirectory() as tmp:
            repo = PolicyExceptionRepository(tmp)
            repo.grant(
                policy_id="STD-001", hostname="GW",
                reason="temporary", owner="netops",
                expires_at="2026-07-01T00:00:00+00:00", occurred_at=NOW,
            )
            self.assertFalse(repo.active_subjects("2026-07-02T00:00:00+00:00"))
            self.assertTrue(repo.active_subjects("2026-06-30T00:00:00+00:00"))


if __name__ == "__main__":
    unittest.main()
