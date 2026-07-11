"""Acceptance tests for PR-039 — Compass, the change-planning engine.

Compass plans MANY changes: every change is analysed through the
existing prediction engine, dependencies come from cited evidence only
(never invented), the recommended order is a deterministic topological
sort explained step by step, conflicts warn without blocking, and the
risk summary covers blast radius, rollback coverage, and known
unknowns. Compass is an advisor — the engineer remains in control.
"""

from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.compass import (
    ChangePlan,
    PlanRepository,
    PlannedChange,
    add_change,
    analyse_plan,
    analyse_plan_for_workspace,
    create_plan,
    detect_conflicts,
    remove_change,
)
from founderos_atlas.search import SearchService, search_enterprise

from tests.test_atlas_transport import PASSWORD
from tests.test_federation import hyderabad_network, secunderabad_network
from tests.test_prediction_architecture import NOW, chain, topology
from tests.test_profile_isolation import FIXED, add_profile, make_service, run_discover


def change(
    change_id: str,
    device: str,
    change_type: str,
    interface: str | None = None,
    **overrides,
) -> PlannedChange:
    return PlannedChange(
        change_id=change_id,
        device=device,
        interface=interface,
        change_type=change_type,
        **overrides,
    )


def plan(*changes: PlannedChange, **overrides) -> ChangePlan:
    values = {
        "plan_id": "p1",
        "title": "Test window",
        "maintenance_window": "Sat 02:00-06:00",
        "engineer": "netops",
        "created_at": NOW,
        "updated_at": NOW,
        "changes": tuple(changes),
    }
    values.update(overrides)
    return ChangePlan(**values)


def star() -> dict:
    """SW1 at the center of R1/R2/R3: rebooting SW1 cuts everything."""

    return topology(
        {
            "R1": ["Gi0/1"],
            "R2": ["Gi0/1"],
            "R3": ["Gi0/1"],
            "SW1": ["Gi0/1", "Gi0/2", "Gi0/3"],
        },
        (
            ("SW1", "Gi0/1", "R1", "Gi0/1"),
            ("SW1", "Gi0/2", "R2", "Gi0/1"),
            ("SW1", "Gi0/3", "R3", "Gi0/1"),
        ),
    )


class ModelTests(unittest.TestCase):
    def test_planned_change_round_trips(self) -> None:
        item = change(
            "c1", "SW1", "shutdown-interface", "Gi0/2",
            reason="decommission", estimated_duration_minutes=10,
            rollback_available=True, notes="coordinate",
        )
        self.assertEqual(item, PlannedChange.from_dict(item.to_dict()))
        self.assertEqual("Shutdown interface — SW1 Gi0/2", item.title)

    def test_unknown_change_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            change("c1", "SW1", "paint-the-router")

    def test_plan_round_trips(self) -> None:
        original = plan(change("c1", "R1", "ios-upgrade"), cab_reference="CAB-7")
        self.assertEqual(original, ChangePlan.from_dict(original.to_dict()))


class SingleChangeTests(unittest.TestCase):
    def test_single_change_is_analysed_via_prediction(self) -> None:
        assessment = analyse_plan(
            plan(change("c1", "SW1", "shutdown-interface", "Gi0/2")),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual(1, len(assessment.steps))
        step = assessment.steps[0]
        self.assertEqual(1, step.order)
        self.assertIn("Independent", step.reason)
        analysis = assessment.analyses[0]
        self.assertIn("SW2", analysis.blast_devices)
        self.assertLessEqual(analysis.confidence, 0.95)
        self.assertTrue(analysis.prediction_modeled)
        self.assertTrue(step.evidence)

    def test_ios_upgrade_is_predicted_through_reload_semantics(self) -> None:
        assessment = analyse_plan(
            plan(change("c1", "SW1", "ios-upgrade")),
            snapshot=chain(),
            generated_at=NOW,
        )
        analysis = assessment.analyses[0]
        self.assertTrue(analysis.prediction_modeled)
        self.assertTrue(analysis.blast_devices)
        # An upgrade reloads the device: not reversible.
        self.assertIs(False, analysis.rollback_reversible)


class OrderingTests(unittest.TestCase):
    def test_independent_changes_run_safest_first(self) -> None:
        snapshot = topology(
            {"R1": ["Gi0/1"], "SW1": ["Gi0/1", "Gi0/2", "Gi0/9"], "SW2": ["Gi0/1"]},
            (
                ("R1", "Gi0/1", "SW1", "Gi0/1"),
                ("SW1", "Gi0/2", "SW2", "Gi0/1"),
            ),
        )
        assessment = analyse_plan(
            plan(
                change("c1", "SW1", "shutdown-interface", "Gi0/2"),  # transit
                change("c2", "SW1", "shutdown-interface", "Gi0/9"),  # access
            ),
            snapshot=snapshot,
            generated_at=NOW,
        )
        self.assertEqual(["c2", "c1"], [step.change_id for step in assessment.steps])
        self.assertIn("Independent", assessment.steps[0].reason)
        self.assertLess(
            assessment.analysis_for("c2").risk_score,
            assessment.analysis_for("c1").risk_score,
        )

    def test_blast_radius_dependency_orders_dependent_work_first(self) -> None:
        """The ACL-before-shutdown story: work on a device that a later
        shutdown will cut off must run BEFORE the shutdown."""

        assessment = analyse_plan(
            plan(
                change("c1", "SW1", "shutdown-interface", "Gi0/2"),
                change("c2", "SW2", "acl-change"),
            ),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual(["c2", "c1"], [step.change_id for step in assessment.steps])
        dependency = assessment.dependencies[0]
        self.assertEqual("c2", dependency.before_change_id)
        self.assertEqual("c1", dependency.after_change_id)
        self.assertIn("blast radius", dependency.evidence[0])
        self.assertIn("Runs after", assessment.steps[1].reason)
        self.assertIn("SW2", assessment.steps[1].reason)
        self.assertIn("Scheduled early", assessment.steps[0].reason)

    def test_same_device_work_precedes_its_upgrade(self) -> None:
        assessment = analyse_plan(
            plan(
                change("c1", "R1", "ios-upgrade"),
                change("c2", "R1", "configuration-change"),
            ),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual(["c2", "c1"], [step.change_id for step in assessment.steps])
        self.assertIn("reloads R1", assessment.dependencies[0].reason)

    def test_largest_blast_radius_is_scheduled_last_for_a_separate_window(self) -> None:
        # In the star, shutting R1's only uplink strands every other
        # device relative to R1 (3 of 4) — the plan's largest blast.
        assessment = analyse_plan(
            plan(
                change("c1", "SW1", "ios-upgrade"),
                change("c2", "R1", "shutdown-interface", "Gi0/1"),
            ),
            snapshot=star(),
            generated_at=NOW,
        )
        last = assessment.steps[-1]
        self.assertEqual("c2", last.change_id)
        self.assertTrue(last.separate_window)
        self.assertIn("separate", last.reason)
        self.assertIn("blast radius", last.reason)
        self.assertEqual(
            3, assessment.risk.largest_blast_device_count
        )
        self.assertEqual("c2", assessment.risk.largest_blast_change_id)

    def test_circular_dependencies_are_reported_not_guessed(self) -> None:
        two = topology(
            {"R1": ["Gi0/1"], "SW1": ["Gi0/1"]},
            (("R1", "Gi0/1", "SW1", "Gi0/1"),),
        )
        assessment = analyse_plan(
            plan(
                change("c1", "R1", "shutdown-interface", "Gi0/1"),
                change("c2", "SW1", "shutdown-interface", "Gi0/1"),
            ),
            snapshot=two,
            generated_at=NOW,
        )
        # Both shutdowns isolate the other change's device: a true cycle.
        self.assertEqual(2, len(assessment.dependencies))
        self.assertTrue(
            any("Circular dependency" in item for item in assessment.unknowns)
        )
        self.assertEqual(2, len(assessment.steps))  # order still produced

    def test_identical_evidence_yields_identical_assessments(self) -> None:
        build = lambda: analyse_plan(  # noqa: E731
            plan(
                change("c1", "SW1", "shutdown-interface", "Gi0/2"),
                change("c2", "SW2", "acl-change"),
                change("c3", "R1", "ios-upgrade"),
            ),
            snapshot=chain(),
            generated_at=NOW,
        ).to_dict()
        self.assertEqual(
            json.dumps(build(), sort_keys=True), json.dumps(build(), sort_keys=True)
        )


class HonestyTests(unittest.TestCase):
    def test_unmodeled_change_types_state_unknown_dependencies(self) -> None:
        assessment = analyse_plan(
            plan(change("c1", "SW1", "acl-change")),
            snapshot=chain(),
            generated_at=NOW,
        )
        analysis = assessment.analyses[0]
        self.assertFalse(analysis.prediction_modeled)
        # Below the high-confidence band: unmodeled types are honest.
        self.assertLess(analysis.confidence, 0.72)
        self.assertTrue(
            any("no impact model" in item for item in assessment.unknowns)
        )
        self.assertTrue(
            any("unknown, not absent" in item for item in assessment.unknowns)
        )

    def test_no_evidence_means_no_dependencies(self) -> None:
        assessment = analyse_plan(
            plan(
                change("c1", "R1", "acl-change"),
                change("c2", "SW2", "vlan-change"),
            ),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual((), assessment.dependencies)

    def test_stale_evidence_is_disclosed(self) -> None:
        assessment = analyse_plan(
            plan(change("c1", "SW1", "shutdown-interface", "Gi0/2")),
            snapshot=chain(),
            generated_at=NOW,
            fresh=False,
        )
        self.assertTrue(
            any("freshness window" in item for item in assessment.unknowns)
        )


class ConflictTests(unittest.TestCase):
    def test_duplicate_change_is_warned(self) -> None:
        conflicts = detect_conflicts(
            plan(
                change("c1", "SW1", "shutdown-interface", "Gi0/1"),
                change("c2", "SW1", "shutdown-interface", "Gi0/1"),
            )
        )
        self.assertEqual("duplicate-change", conflicts[0].kind)

    def test_shutdown_and_enable_are_mutually_exclusive(self) -> None:
        conflicts = detect_conflicts(
            plan(
                change("c1", "SW1", "shutdown-interface", "Gi0/1"),
                change("c2", "SW1", "enable-interface", "Gi0/1"),
            )
        )
        self.assertEqual("mutually-exclusive", conflicts[0].kind)
        self.assertIn("final state", conflicts[0].detail)

    def test_two_changes_on_one_interface_are_flagged(self) -> None:
        conflicts = detect_conflicts(
            plan(
                change("c1", "SW1", "shutdown-interface", "Gi0/1"),
                change("c2", "SW1", "vlan-change", "Gi0/1"),
            )
        )
        self.assertEqual("same-interface", conflicts[0].kind)

    def test_double_upgrade_of_one_device_is_flagged(self) -> None:
        conflicts = detect_conflicts(
            plan(
                change("c1", "R1", "ios-upgrade"),
                change("c2", "R1", "ios-upgrade"),
            )
        )
        self.assertTrue(
            any(item.kind == "duplicate-upgrade" for item in conflicts)
        )

    def test_conflicts_warn_but_never_block_the_order(self) -> None:
        assessment = analyse_plan(
            plan(
                change("c1", "SW1", "shutdown-interface", "Gi0/1"),
                change("c2", "SW1", "shutdown-interface", "Gi0/1"),
            ),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertTrue(assessment.conflicts)
        self.assertEqual(2, len(assessment.steps))


class RiskSummaryTests(unittest.TestCase):
    def test_summary_covers_risk_blast_rollback_and_duration(self) -> None:
        assessment = analyse_plan(
            plan(
                change(
                    "c1", "SW1", "shutdown-interface", "Gi0/2",
                    rollback_available=True, estimated_duration_minutes=10,
                ),
                change(
                    "c2", "SW2", "acl-change",
                    rollback_available=False, estimated_duration_minutes=20,
                ),
                change("c3", "R1", "configuration-change"),
            ),
            snapshot=chain(),
            generated_at=NOW,
        )
        risk = assessment.risk
        self.assertEqual("c1", risk.highest_risk_change_id)
        self.assertEqual("c1", risk.largest_blast_change_id)
        self.assertGreaterEqual(risk.largest_blast_device_count, 1)
        # Targets R1/SW1/SW2 plus SW1's blast radius: the whole chain.
        self.assertEqual(3, risk.total_devices_impacted)
        self.assertEqual(1, risk.rollback_covered)
        self.assertEqual(1, risk.rollback_missing)
        self.assertEqual(1, risk.rollback_unknown)
        # One duration unknown -> the total is honestly unknown.
        self.assertIsNone(risk.estimated_total_minutes)

    def test_duration_totals_when_every_change_declares_one(self) -> None:
        assessment = analyse_plan(
            plan(
                change("c1", "R1", "ios-upgrade", estimated_duration_minutes=30),
                change("c2", "SW2", "acl-change", estimated_duration_minutes=15),
            ),
            snapshot=chain(),
            generated_at=NOW,
        )
        self.assertEqual(45, assessment.risk.estimated_total_minutes)


class ServiceTests(unittest.TestCase):
    def test_create_add_remove_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = PlanRepository(Path(tmp))
            first = create_plan(
                repository, title="Core work", maintenance_window="Sat",
                engineer="mustafa", created_at=NOW, cab_reference="CAB-9",
            )
            second = create_plan(
                repository, title="Core work", maintenance_window="Sun",
                engineer="mustafa", created_at=NOW,
            )
            self.assertEqual("core-work", first.plan_id)
            self.assertEqual("core-work-2", second.plan_id)
            updated = add_change(
                repository, first,
                change("c1", "R1", "ios-upgrade"),
                updated_at="2026-07-11T09:00:00+00:00",
            )
            self.assertEqual("draft", updated.status)
            self.assertEqual("2026-07-11T09:00:00+00:00", updated.updated_at)
            reloaded, assessment = repository.get("core-work")
            self.assertEqual(1, len(reloaded.changes))
            self.assertIsNone(assessment)
            trimmed = remove_change(
                repository, reloaded, "c1", updated_at=NOW
            )
            self.assertEqual((), trimmed.changes)

    def test_analyse_for_workspace_uses_the_enterprise_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Hyderabad", "10.0.0.1")
            add_profile(service, "Secunderabad", "10.0.1.1")
            run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
            run_discover(
                workdir, service, secunderabad_network(), "Secunderabad",
                FIXED + timedelta(minutes=30),
            )
            repository = PlanRepository(workdir)
            created = create_plan(
                repository, title="Cross-lab window", maintenance_window="Sat",
                engineer="netops", created_at=NOW,
            )
            created = add_change(
                repository, created,
                change("c1", "GW", "ios-upgrade"), updated_at=NOW,
            )
            created = add_change(
                repository, created,
                change("c2", "B1", "configuration-change"), updated_at=NOW,
            )
            analysed, assessment = analyse_plan_for_workspace(
                repository, created,
                base_output_dir=workdir,
                profiles=service.list_profiles(),
                generated_at=(FIXED + timedelta(hours=1)).isoformat(
                    timespec="seconds"
                ),
            )
            self.assertEqual("analysed", analysed.status)
            # The GW upgrade cuts Secunderabad's B1 off: evidence-based
            # cross-profile dependency — B1's work runs first.
            self.assertEqual(
                ["c2", "c1"], [step["change_id"] for step in
                               assessment.to_dict()["steps"]],
            )
            stored_plan, stored = repository.get(analysed.plan_id)
            self.assertEqual("analysed", stored_plan.status)
            self.assertEqual(assessment.to_dict(), stored)
            self.assertNotIn(
                PASSWORD, json.dumps(stored)
            )


class SearchIntegrationTests(unittest.TestCase):
    def test_plans_are_searchable_and_index_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service = make_service(workdir)
            add_profile(service, "Hyderabad", "10.0.0.1")
            run_discover(workdir, service, hyderabad_network(), "Hyderabad", FIXED)
            search_service = SearchService()
            index = search_service.index_for(workdir, service.list_profiles())
            self.assertEqual(0, search_enterprise(index, "CAB-1042").total)
            repository = PlanRepository(workdir)
            created = create_plan(
                repository, title="July core maintenance",
                maintenance_window="Sat", engineer="mustafa",
                created_at=NOW, cab_reference="CAB-1042",
            )
            add_change(
                repository, created,
                change("c1", "GW", "ios-upgrade"), updated_at=NOW,
            )
            index = search_service.index_for(workdir, service.list_profiles())
            for query in ("July core", "CAB-1042", "mustafa", "plan"):
                response = search_enterprise(index, query)
                plans = [g for g in response.groups if g.group_id == "plans"]
                self.assertTrue(plans, query)
                self.assertEqual(
                    "July core maintenance", plans[0].results[0].entry.title
                )
            by_device = search_enterprise(index, "GW")
            self.assertIn("plans", [g.group_id for g in by_device.groups])


class CompassGuiTests(unittest.TestCase):
    """The CML scenario end to end in the GUI."""

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
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app.test_client()

    def create_gui_plan(self, client) -> str:
        response = client.post(
            "/compass/new",
            data={
                "title": "July core maintenance",
                "maintenance_window": "Sat 02:00-06:00",
                "engineer": "mustafa",
                "cab_reference": "CAB-1042",
            },
        )
        return response.headers["Location"].rsplit("/", 1)[-1]

    def test_full_planning_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_world(Path(tmp))
            page = client.get("/compass").data
            self.assertIn(b"Maintenance Plans", page)
            self.assertIn(b"New Plan", page)
            plan_id = self.create_gui_plan(client)
            for data in (
                {"device": "GW", "change_type": "ios-upgrade",
                 "reason": "security patch", "rollback_available": "no",
                 "estimated_duration_minutes": "30"},
                {"device": "A1", "change_type": "shutdown-interface",
                 "interface": "GigabitEthernet0/1",
                 "reason": "decommission uplink", "rollback_available": "yes"},
                {"device": "A2", "change_type": "acl-change",
                 "reason": "cleanup before shutdown"},
            ):
                response = client.post(
                    f"/compass/{plan_id}/changes", data=data,
                    follow_redirects=True,
                )
                self.assertIn(b"Added:", response.data)
            response = client.post(
                f"/compass/{plan_id}/analyse", follow_redirects=True
            )
            body = response.data
            self.assertIn(b"Risk Summary", body)
            self.assertIn(b"Recommended Execution Order", body)
            self.assertIn(b"Overall plan risk", body)
            self.assertIn(b"Rollback covered", body)
            self.assertIn(b"Evidence:", body)
            self.assertIn(b"What Atlas Cannot See", body)
            # The ACL change on A2 must precede the A1 shutdown that
            # would cut A2 off — visible with its WHY in the timeline
            # (search inside the ordered section: the add-change form
            # above it also mentions the change-type labels).
            text = body.decode("utf-8")
            timeline = text[text.index("Recommended Execution Order"):]
            self.assertLess(
                timeline.index("ACL change — A2"),
                timeline.index("Shutdown interface — A1"),
            )
            self.assertIn("must complete first", timeline)
            self.assertNotIn(PASSWORD, text)

    def test_gui_validates_devices_against_enterprise_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_world(Path(tmp))
            plan_id = self.create_gui_plan(client)
            response = client.post(
                f"/compass/{plan_id}/changes",
                data={"device": "GHOST", "change_type": "ios-upgrade"},
                follow_redirects=True,
            )
            self.assertIn(b"not in the enterprise", response.data)
            response = client.post(
                f"/compass/{plan_id}/changes",
                data={"device": "A1", "change_type": "shutdown-interface",
                      "interface": "Gi0/9"},
                follow_redirects=True,
            )
            self.assertIn(b"Interface not accepted", response.data)

    def test_conflicts_are_warned_in_the_gui(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_world(Path(tmp))
            plan_id = self.create_gui_plan(client)
            for _ in range(2):
                client.post(
                    f"/compass/{plan_id}/changes",
                    data={"device": "A1", "change_type": "shutdown-interface",
                          "interface": "GigabitEthernet0/1"},
                )
            response = client.post(
                f"/compass/{plan_id}/analyse", follow_redirects=True
            )
            self.assertIn(b"Conflicts (warnings", response.data)
            self.assertIn(b"duplicate-change", response.data)
            self.assertIn(b"Recommended Execution Order", response.data)

    def test_unknown_plan_redirects_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.build_world(Path(tmp))
            response = client.get("/compass/no-such-plan", follow_redirects=True)
            self.assertIn(b"no longer exists", response.data)


if __name__ == "__main__":
    unittest.main()
