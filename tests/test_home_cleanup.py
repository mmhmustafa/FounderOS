"""Home cleanup: plan archive and the Continue Working clean slate.

"Taken care of" never means deleted: an archived plan leaves Home
attention, Continue Working, and the default Compass list, but its
record, assessment, audit trail, and activity history remain, and
unarchive is one click. The clean slate is a per-user cutoff instant —
other operators' Home is untouched and no domain data moves.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world


def _make_plan(client, title="fw reboots") -> str:
    response = client.post("/compass/new", data={
        "title": title, "maintenance_window": "Sat 02:00",
        "engineer": "priya",
    })
    return response.headers["Location"].rstrip("/").split("/")[-1]


class PlanArchiveTests(unittest.TestCase):
    def test_archive_removes_from_home_but_keeps_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            plan_id = _make_plan(client)
            home = client.get("/?scope=all").get_data(as_text=True)
            self.assertIn("have not been analysed yet", home)
            client.post(f"/compass/{plan_id}/archive", data={})
            home = client.get("/?scope=all").get_data(as_text=True)
            self.assertNotIn("have not been analysed yet", home)
            # The record itself is intact and visible behind the toggle.
            default = client.get("/compass").get_data(as_text=True)
            self.assertNotIn("fw reboots", default)
            self.assertIn("Show archived (1)", default)
            archived = client.get("/compass?archived=1").get_data(
                as_text=True
            )
            self.assertIn("fw reboots", archived)
            self.assertIn("archived", archived)

    def test_unarchive_restores_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            plan_id = _make_plan(client)
            client.post(f"/compass/{plan_id}/archive", data={})
            client.post(f"/compass/{plan_id}/archive", data={
                "action": "unarchive",
            })
            default = client.get("/compass").get_data(as_text=True)
            self.assertIn("fw reboots", default)
            home = client.get("/?scope=all").get_data(as_text=True)
            self.assertIn("have not been analysed yet", home)

    def test_archive_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            plan_id = _make_plan(client)
            client.post(f"/compass/{plan_id}/archive", data={
                "reason": "maintenance done",
            })
            audit = client.get(
                "/audit?category=compass-plan"
            ).get_data(as_text=True)
            self.assertIn("archive", audit)
            self.assertIn("maintenance done", audit)


class CleanSlateTests(unittest.TestCase):
    def test_clean_slate_empties_the_card_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            _make_plan(client, title="os upgrade R1")
            home = client.get("/?scope=all").get_data(as_text=True)
            self.assertIn("os upgrade R1", home)
            self.assertIn("Clean slate", home)
            client.post("/home/continue-working/clear", data={})
            home = client.get("/?scope=all").get_data(as_text=True)
            card = home.split("Continue Working")[1].split("</section>")[0]
            self.assertNotIn("os upgrade R1", card)
            # Nothing was deleted: Compass still lists the plan.
            self.assertIn(
                "os upgrade R1",
                client.get("/compass").get_data(as_text=True),
            )

    def test_new_work_reappears_after_a_clean_slate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            _make_plan(client, title="old plan")
            client.post("/home/continue-working/clear", data={})
            _make_plan(client, title="new plan")
            home = client.get("/?scope=all").get_data(as_text=True)
            card = home.split("Continue Working")[1].split("</section>")[0]
            self.assertIn("new plan", card)
            self.assertNotIn("old plan", card)

    def test_clean_slate_is_per_user(self) -> None:
        from tests.test_production_security import (
            production_world, sign_in,
        )

        with production_world() as (app, _workdir):
            operator, operator_csrf = sign_in(app, "operator")
            viewer, _ = sign_in(app, "viewer")
            operator.post("/home/continue-working/clear", data={
                "_csrf": operator_csrf,
            })
            # The preference lands on the operator's account only.
            from founderos_atlas.workspace.user_preferences import (
                UserPreferenceStore,
            )

            store = UserPreferenceStore(
                app.config["ATLAS_WORKSPACE_ROOT"]
            )
            self.assertTrue(
                store.ui_value("operator", "workflow:continue-cleared")
            )
            self.assertIsNone(
                store.ui_value("viewer", "workflow:continue-cleared")
            )


if __name__ == "__main__":
    unittest.main()
