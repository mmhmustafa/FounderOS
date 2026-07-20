"""Unclaimed per-profile artifact folders: seeing them, setting them aside.

Deleting a profile has never removed the files it collected, and nothing
reads them afterwards. They are inert but invisible, which is the actual
harm: 21 folders and 70MB accumulated in a real workspace and became the
first suspect when something looked stale. These tests pin the safety
properties, because the failure mode here is losing live data.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from founderos_atlas.workspace.orphan_scopes import (
    ORPHAN_ARCHIVE_PREFIX,
    archive_orphan_scopes,
    find_orphan_scopes,
    list_orphan_archives,
    orphan_summary,
)
from founderos_atlas.workspace.scopes import PROFILE_SCOPES_SUBDIR


class FakeProfile:
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id


def make_scope(base: Path, scope_id: str, *, files=(("a.txt", "x"),)) -> Path:
    scope = base / PROFILE_SCOPES_SUBDIR / scope_id
    scope.mkdir(parents=True, exist_ok=True)
    for name, body in files:
        target = scope / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return scope


class FindOrphanTests(unittest.TestCase):
    def test_only_folders_no_profile_claims_are_listed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "live")
            make_scope(base, "dead")
            orphans = find_orphan_scopes(base, [FakeProfile("live")])
            self.assertEqual(["dead"], [item.scope_id for item in orphans])

    def test_an_archived_profile_still_claims_its_folder(self) -> None:
        """An archived profile is a profile. Offering to move its
        artifacts would be offering to lose live data."""

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "archived-but-saved")
            orphans = find_orphan_scopes(
                base, [FakeProfile("archived-but-saved")]
            )
            self.assertEqual((), orphans)

    def test_previous_sweeps_are_never_swept_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / PROFILE_SCOPES_SUBDIR
            (root / f"{ORPHAN_ARCHIVE_PREFIX}20260720T101010").mkdir(
                parents=True
            )
            self.assertEqual((), find_orphan_scopes(base, []))

    def test_size_and_contents_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "dead", files=(
                ("topology_snapshot.json", "{}"),
                ("configs/dev/running_config.txt", "hostname x"),
                ("history/run/record.json", "{}"),
            ))
            orphan = find_orphan_scopes(base, [])[0]
            self.assertEqual(3, orphan.file_count)
            self.assertGreater(orphan.size_bytes, 0)
            self.assertIn("topology snapshot", orphan.holds)
            self.assertIn("captured configurations", orphan.holds)
            self.assertIn("discovery history", orphan.holds)
            self.assertIsNotNone(orphan.last_modified)

    def test_summary_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "a")
            make_scope(base, "b")
            summary = orphan_summary(find_orphan_scopes(base, []))
            self.assertEqual(2, summary["count"])
            self.assertEqual(2, len(summary["scopes"]))

    def test_missing_profiles_directory_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual((), find_orphan_scopes(Path(tmp), []))


class ArchiveTests(unittest.TestCase):
    def test_folders_are_moved_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "dead", files=(("keep.txt", "precious"),))
            manifest = archive_orphan_scopes(base, ["dead"], actor="admin")

            self.assertEqual(1, manifest["moved_count"])
            self.assertFalse(
                (base / PROFILE_SCOPES_SUBDIR / "dead").exists()
            )
            archived = Path(manifest["archive_dir"]) / "dead" / "keep.txt"
            self.assertTrue(archived.is_file())
            # The bytes survived the move — this is the whole promise.
            self.assertEqual("precious", archived.read_text(encoding="utf-8"))

    def test_a_folder_claimed_since_the_screen_loaded_is_skipped(self) -> None:
        """The list an operator acted on may be minutes old. A profile
        created since must not have its artifacts moved out from under
        it, so the orphan set is re-derived at execution."""

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "claimed-since")
            manifest = archive_orphan_scopes(
                base, ["claimed-since"],
                profiles=[FakeProfile("claimed-since")],
            )
            self.assertEqual(0, manifest["moved_count"])
            self.assertEqual(1, len(manifest["skipped"]))
            self.assertIn("no longer", manifest["skipped"][0]["reason"])
            self.assertTrue(
                (base / PROFILE_SCOPES_SUBDIR / "claimed-since").is_dir()
            )

    def test_a_manifest_records_exactly_what_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "one")
            make_scope(base, "two")
            manifest = archive_orphan_scopes(
                base, ["one", "two"], actor="operator-a",
            )
            written = json.loads(
                (Path(manifest["archive_dir"]) / "manifest.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual("operator-a", written["actor"])
            self.assertEqual(2, written["moved_count"])
            self.assertEqual(
                {"one", "two"},
                {item["scope_id"] for item in written["moved"]},
            )

    def test_unknown_names_move_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "real")
            manifest = archive_orphan_scopes(base, ["not-a-folder"])
            self.assertEqual(0, manifest["moved_count"])
            self.assertTrue((base / PROFILE_SCOPES_SUBDIR / "real").is_dir())

    def test_sweeps_are_listed_newest_first_and_stay_findable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            make_scope(base, "old-one")
            archive_orphan_scopes(
                base, ["old-one"], actor="a", now="2026-07-20T10:00:00+00:00",
            )
            make_scope(base, "old-two")
            archive_orphan_scopes(
                base, ["old-two"], actor="b", now="2026-07-21T10:00:00+00:00",
            )
            archives = list_orphan_archives(base)
            self.assertEqual(2, len(archives))
            self.assertGreater(archives[0]["name"], archives[1]["name"])
            self.assertEqual("b", archives[0]["actor"])
            # A second find must not offer the archives themselves.
            self.assertEqual((), find_orphan_scopes(base, []))


class StorageScreenTests(unittest.TestCase):
    def _client(self, tmp: Path):
        from tests.test_polish import build_world

        _, client = build_world(tmp)
        return client

    def test_the_screen_names_the_folders_and_their_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            client = self._client(base)
            make_scope(base, "abandoned-lab", files=(
                ("topology_snapshot.json", "{}"),
            ))
            page = client.get("/settings/storage")
            self.assertEqual(200, page.status_code)
            body = page.get_data(as_text=True)
            self.assertIn("abandoned-lab", body)
            self.assertIn("topology snapshot", body)
            # The promise is on the page, not only in the code.
            self.assertIn("never deletes it", body)

    def test_reclaiming_moves_and_says_where(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            client = self._client(base)
            make_scope(base, "abandoned-lab")
            response = client.post(
                "/settings/storage/reclaim",
                data={"scope_id": "abandoned-lab"},
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            body = response.get_data(as_text=True)
            self.assertIn("MOVED, not", body)
            self.assertFalse(
                (base / PROFILE_SCOPES_SUBDIR / "abandoned-lab").exists()
            )

    def test_selecting_nothing_moves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            client = self._client(base)
            make_scope(base, "abandoned-lab")
            response = client.post(
                "/settings/storage/reclaim", data={}, follow_redirects=True,
            )
            self.assertIn("nothing was moved", response.get_data(as_text=True))
            self.assertTrue(
                (base / PROFILE_SCOPES_SUBDIR / "abandoned-lab").is_dir()
            )

    def test_reclaiming_is_administrator_work(self) -> None:
        from tests.test_production_security import production_world, sign_in

        with production_world() as (app, _workdir):
            for username in ("viewer", "operator", "investigator"):
                client, csrf = sign_in(app, username)
                self.assertEqual(
                    403,
                    client.get("/settings/storage").status_code,
                    username,
                )
                self.assertEqual(
                    403,
                    client.post(
                        "/settings/storage/reclaim",
                        data={"scope_id": "x"},
                        headers={"X-Atlas-CSRF": csrf},
                    ).status_code,
                    username,
                )
            admin, csrf = sign_in(app, "admin")
            self.assertEqual(200, admin.get("/settings/storage").status_code)


if __name__ == "__main__":
    unittest.main()
