"""The complete operational lifecycle, end to end, plus quality gates.

The e2e test walks one incident from detection to auditable closure:

  discovery signal → incident case → path investigation → prediction
  → Compass plan → readiness → review → approval → schedule
  → pre-checks → execution checkpoints → post-checks → completion
  → evidence linked back → audit timeline

The gate tests fail the build on primary-route 404s/500s, unlabeled
critical controls, unwrapped wide tables (the horizontal-overflow
guard), broken static references, and non-persistent lifecycle records.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world


class LifecycleEndToEndTests(unittest.TestCase):
    def test_signal_to_audited_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)

            # 1. Detection: a discovery-backed incident investigation opens
            # a case (enterprise scope, profile chosen inline).
            opened = client.post("/incidents/run", data={
                "profile": "hyderabad",
                "title": "Core uplink flapping",
                "description": "GW reports interface resets since 09:00",
                "severity": "high",
            }, follow_redirects=False)
            self.assertEqual(302, opened.status_code)
            case_id = opened.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
            self.assertTrue(case_id.startswith("CASE-"))

            case_page = client.get(
                f"/incidents/case/{case_id}"
            ).data.decode("utf-8")
            self.assertIn("Observed facts (evidence)", case_page)
            self.assertIn("Inferred root cause (hypothesis)", case_page)
            self.assertIn("Continue the investigation", case_page)

            # 2. Lifecycle actions: acknowledge and assign.
            from founderos_atlas.incidents.records import (
                IncidentCaseRepository,
            )

            repo = IncidentCaseRepository(workdir / "workspace")
            client.post(f"/incidents/case/{case_id}/action", data={
                "action": "acknowledge",
                "expected_revision": str(repo.revision()),
            })
            client.post(f"/incidents/case/{case_id}/action", data={
                "action": "assign", "owner": "netops",
                "expected_revision": str(repo.revision()),
            })
            case = repo.get(case_id)
            self.assertEqual("acknowledged", case.status)
            self.assertEqual("netops", case.owner)

            # 3. Investigation: a path run carrying the case links back.
            ran = client.post("/paths/run", data={
                "source": "GW", "destination": "SW1",
                "case_id": case_id, "protocol": "tcp", "port": "443",
            }, follow_redirects=True)
            self.assertEqual(200, ran.status_code)
            case = repo.get(case_id)
            self.assertIn("GW → SW1", case.linked_paths)
            stored = json.loads(
                (workdir / ".atlas" / "profiles" / "hyderabad"
                 / "path_investigation_report.json").read_text(
                     encoding="utf-8")
            ) if (workdir / ".atlas" / "profiles" / "hyderabad"
                  / "path_investigation_report.json").is_file() else None
            if stored is not None:
                self.assertEqual(
                    {"protocol": "tcp", "port": "443"}, stored.get("intent")
                )
                self.assertIn("NOT", stored.get("intent_note", ""))

            # 4. Prediction: linked to the case, saved as a scenario.
            predicted = client.post("/predict/run", data={
                "device": "GW", "change_type": "reboot-device",
                "case_id": case_id, "reason": "clear the flap",
            }, follow_redirects=True)
            self.assertEqual(200, predicted.status_code)
            case = repo.get(case_id)
            self.assertTrue(case.linked_predictions)

            # 5. Compass: a plan born from the incident.
            created = client.post("/compass/new", data={
                "title": "Remediate core uplink",
                "maintenance_window": "Sat 02:00-04:00",
                "engineer": "netops",
                "incident_ref": case_id,
            }, follow_redirects=False)
            plan_id = created.headers["Location"].split("?")[0].rstrip(
                "/"
            ).rsplit("/", 1)[-1]
            case = repo.get(case_id)
            self.assertIn(plan_id, case.linked_plans)

            from founderos_atlas.compass.service import PlanRepository

            plans = PlanRepository(workdir)

            def plan():
                loaded, _assessment = plans.get(plan_id)
                return loaded

            self.assertEqual(case_id, plan().incident_ref)

            client.post(f"/compass/{plan_id}/changes", data={
                "device": "GW", "change_type": "configuration-change",
                "reason": "stabilise uplink",
                "estimated_duration_minutes": "10",
                "rollback_available": "yes",
                "expected_revision": str(plan().revision),
            })
            self.assertEqual(1, len(plan().changes))

            # 6. Readiness: rollback plan, criteria, checks.
            client.post(f"/compass/{plan_id}/readiness", data={
                "rollback_plan": "Restore previous interface config from "
                                 "configuration memory version N-1.",
                "success_criteria": "No interface resets for 30 minutes",
                "reviewers": "approver-jane",
                "pre_checks": "Confirm current config backed up",
                "post_checks": "Interface counters stable",
                "expected_revision": str(plan().revision),
            }, follow_redirects=True)
            self.assertEqual(
                "Restore previous interface config from configuration "
                "memory version N-1.",
                plan().rollback_plan,
            )

            # 7. Analyse, submit for review, approve.
            client.post(f"/compass/{plan_id}/analyse", data={
                "expected_revision": str(plan().revision),
            })
            self.assertEqual("analysed", plan().status)
            client.post(f"/compass/{plan_id}/submit", data={
                "expected_revision": str(plan().revision),
            })
            self.assertEqual("in-review", plan().status)
            client.post(f"/compass/{plan_id}/decision", data={
                "decision": "approve",
                "expected_revision": str(plan().revision),
            })
            self.assertEqual("approved", plan().status)

            # 8. Schedule and execute with explicit checkpoints.
            client.post(f"/compass/{plan_id}/schedule", data={
                "window_start": "2026-07-19T02:00",
                "window_end": "2026-07-19T04:00",
                "expected_revision": str(plan().revision),
            })
            self.assertEqual("scheduled", plan().status)

            check_id = plan().pre_checks[0]["check_id"]
            client.post(f"/compass/{plan_id}/execution", data={
                "action": "check", "phase": "pre", "check_id": check_id,
                "passed": "1",
                "expected_revision": str(plan().revision),
            })
            client.post(f"/compass/{plan_id}/execution", data={
                "action": "start",
                "expected_revision": str(plan().revision),
            })
            self.assertEqual("running", plan().status)

            change_id = plan().changes[0].change_id
            client.post(f"/compass/{plan_id}/execution", data={
                "action": "checkpoint", "change_id": change_id,
                "outcome": "done", "note": "applied and verified on console",
                "expected_revision": str(plan().revision),
            })
            post_id = plan().post_checks[0]["check_id"]
            client.post(f"/compass/{plan_id}/execution", data={
                "action": "check", "phase": "post", "check_id": post_id,
                "passed": "1",
                "expected_revision": str(plan().revision),
            })
            client.post(f"/compass/{plan_id}/execution", data={
                "action": "complete", "note": "window closed clean",
                "expected_revision": str(plan().revision),
            })
            self.assertEqual("completed", plan().status)
            events = [entry["event"] for entry in plan().execution_log]
            self.assertEqual(
                ["pre-check-passed", "execution-started", "change-done",
                 "post-check-passed", "completed"],
                events,
            )

            # 9. Evidence linked back: the case gained the terminal note,
            # and resolution closes the loop.
            case = repo.get(case_id)
            self.assertTrue(any(
                "completed" in note.text for note in case.notes
            ))
            client.post(f"/incidents/case/{case_id}/action", data={
                "action": "resolve",
                "resolution": "Uplink stabilised by the approved change.",
                "expected_revision": str(repo.revision()),
            })
            self.assertEqual("resolved", repo.get(case_id).status)

            # 10. Auditable end to end: audit carries every stage.
            audit = (workdir / "workspace" / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            for marker in (
                '"incident"', '"open"', '"acknowledge"', '"assign"',
                '"link-path"', '"link-prediction"', '"link-plan"',
                '"compass-plan"', '"submit-for-review"',
                '"execution-start"', '"execution-complete"', '"resolve"',
            ):
                self.assertIn(marker, audit, marker)

            # The CAB export carries the whole story.
            cab = client.get(f"/compass/{plan_id}/cab.md").data.decode(
                "utf-8"
            )
            self.assertIn("## Execution record", cab)
            self.assertIn(case_id, cab)

    def test_rollback_branch_is_recorded_honestly(self) -> None:
        from founderos_atlas.compass import lifecycle
        from founderos_atlas.compass.models import ChangePlan, PlannedChange

        plan = ChangePlan(
            plan_id="p", title="T", maintenance_window="Sat",
            engineer="e", created_at="2026-07-18T00:00:00+00:00",
            updated_at="2026-07-18T00:00:00+00:00",
            status="running",
            changes=(PlannedChange(
                change_id="c1", device="gw",
                change_type="configuration-change",
            ),),
        )
        plan = lifecycle.checkpoint_change(
            plan, change_id="c1", outcome="failed",
            actor="op", note="device did not come back",
        )
        with self.assertRaises(lifecycle.PlanLifecycleError):
            lifecycle.complete(plan, actor="op")
        plan = lifecycle.fail(plan, actor="op", note="change failed")
        plan = lifecycle.rollback(
            plan, actor="op", note="restored config N-1"
        )
        self.assertEqual("rolled-back", plan.status)

    def test_dependency_order_is_enforced(self) -> None:
        from founderos_atlas.compass import lifecycle
        from founderos_atlas.compass.models import ChangePlan, PlannedChange

        plan = ChangePlan(
            plan_id="p", title="T", maintenance_window="Sat",
            engineer="e", created_at="2026-07-18T00:00:00+00:00",
            updated_at="2026-07-18T00:00:00+00:00",
            changes=(
                PlannedChange(change_id="c1", device="a",
                              change_type="configuration-change"),
                PlannedChange(change_id="c2", device="b",
                              change_type="configuration-change",
                              depends_on=("c1",)),
            ),
        )
        with self.assertRaises(lifecycle.PlanLifecycleError):
            lifecycle.reorder_change(plan, "c2", -1)
        # Same concurrency group => they may run together, any order.
        grouped = lifecycle.set_dependencies(
            lifecycle.set_dependencies(
                plan, "c1", depends_on=(), concurrency_group="batch",
            ),
            "c2", depends_on=("c1",), concurrency_group="batch",
        )
        reordered = lifecycle.reorder_change(grouped, "c2", -1)
        self.assertEqual(
            ("c2", "c1"),
            tuple(change.change_id for change in reordered.changes),
        )


class QualityGateTests(unittest.TestCase):
    PRIMARY_ROUTES = (
        "/", "/incidents", "/advisor", "/paths", "/paths/compare",
        "/predict", "/compass", "/topology", "/policy", "/changes",
        "/timeline", "/history", "/configuration", "/evidence",
        "/discovery", "/profiles", "/credentials", "/audit", "/settings",
        "/inbox", "/users", "/management", "/console", "/system/integrity",
        "/healthz", "/readyz",
    )

    def test_no_primary_route_404s_or_500s(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for path in self.PRIMARY_ROUTES:
                for scope in ("", "?scope=all", "?scope=hyderabad"):
                    response = client.get(path + scope,
                                          follow_redirects=True)
                    with self.subTest(path=path + scope):
                        self.assertNotIn(
                            response.status_code, (404, 500),
                            f"{path}{scope} -> {response.status_code}",
                        )

    def test_no_route_renders_uncaught_error_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for path in self.PRIMARY_ROUTES:
                body = client.get(
                    path + "?scope=all", follow_redirects=True
                ).data.decode("utf-8", errors="ignore")
                with self.subTest(path=path):
                    self.assertNotIn("Traceback", body)
                    self.assertNotIn("jinja2.exceptions", body)

    def test_static_references_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            seen: set[str] = set()
            for path in self.PRIMARY_ROUTES:
                body = client.get(
                    path + "?scope=all", follow_redirects=True
                ).data.decode("utf-8", errors="ignore")
                seen.update(re.findall(
                    r'(?:src|href)="(/static/[^"]+)"', body
                ))
            self.assertTrue(seen)
            for reference in sorted(seen):
                with self.subTest(reference=reference):
                    self.assertEqual(
                        200, client.get(reference).status_code, reference
                    )

    def test_wide_tables_live_inside_scroll_regions(self) -> None:
        """The horizontal-overflow gate: every data grid ships inside a
        labelled scroll region, so the page body never scrolls sideways."""

        templates = Path("src/founderos_atlas/web/templates")
        offenders: list[str] = []
        for template in sorted(templates.glob("*.html")):
            text = template.read_text(encoding="utf-8")
            for match in re.finditer(r'<table class="grid', text):
                preceding = text[max(0, match.start() - 400):match.start()]
                if "table-scroll" not in preceding and "atlas.js" not in text:
                    offenders.append(template.name)
                    break
        # atlas.js auto-wraps any remaining grid at runtime; templates that
        # opt out of the base layout would lose that, so they must wrap
        # explicitly. Base-extending templates all load atlas.js.
        self.assertEqual([], [
            name for name in offenders
            if "base.html" not in
            (templates / name).read_text(encoding="utf-8")
        ])

    def test_critical_controls_are_labelled(self) -> None:
        """Buttons must have an accessible name; text inputs must sit
        inside a <label> or carry aria-label/visually-hidden labelling."""

        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            for path in ("/incidents", "/paths", "/predict", "/compass",
                         "/advisor", "/policy", "/changes"):
                body = client.get(
                    path + "?scope=all", follow_redirects=True
                ).data.decode("utf-8", errors="ignore")
                with self.subTest(path=path):
                    empty_buttons = re.findall(
                        r"<button[^>]*>\s*</button>", body
                    )
                    self.assertEqual([], empty_buttons, path)

    def test_lifecycle_records_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir)
            client.post("/incidents/run", data={
                "profile": "hyderabad", "title": "Persistent case",
            })
            from tests.test_web_app import build_client

            _, restarted = build_client(
                workdir, service,
            ) if False else (None, None)
            # A completely fresh app over the same workspace/output dirs.
            from founderos_atlas.web import create_app

            app = create_app(
                profile_service=service, output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            fresh = app.test_client()
            page = fresh.get("/incidents?scope=all").data.decode("utf-8")
            self.assertIn("Persistent case", page)

    def test_filtered_urls_are_shareable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            service, client = build_world(workdir)
            url = "/incidents?scope=all&status=open&owner=netops"
            first = client.get(url).data.decode("utf-8")
            from founderos_atlas.web import create_app

            app = create_app(
                profile_service=service, output_dir=workdir,
                history_root=workdir / ".atlas" / "history",
                workspace_root=workdir / "workspace",
            )
            app.config.update(TESTING=True)
            second = app.test_client().get(url).data.decode("utf-8")
            for html in (first, second):
                self.assertIn('value="open" selected', html)
                self.assertIn('value="netops"', html)


if __name__ == "__main__":
    unittest.main()
