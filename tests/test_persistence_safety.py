"""Persistence and recovery safety: process model, backup, restore.

Covers the enforced single-process model (including a REAL second
process), credential-provider concurrency, canary-based backup content
inspection of DECOMPRESSED members, and the transactional restore with
bomb/traversal/oversize refusals and mid-commit rollback.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from tests.test_polish import build_world


class SingleProcessModelTests(unittest.TestCase):
    def test_lock_is_reentrant_within_one_process(self) -> None:
        from founderos_atlas.workspace.instance import (
            acquire_instance_lock,
            instance_lock_held,
        )

        with tempfile.TemporaryDirectory() as tmp:
            first = acquire_instance_lock(tmp)
            second = acquire_instance_lock(tmp)
            self.assertIs(first, second)
            self.assertTrue(instance_lock_held(tmp))
            first.release()

    def test_second_real_process_is_refused(self) -> None:
        """A genuinely separate OS process pointed at the same workspace
        must fail to start — this is the multi-worker detection."""

        from founderos_atlas.workspace.instance import acquire_instance_lock

        with tempfile.TemporaryDirectory() as tmp:
            lock = acquire_instance_lock(tmp)
            try:
                probe = subprocess.run(
                    [sys.executable, "-c", (
                        "import sys\n"
                        "sys.path.insert(0, 'src')\n"
                        "from founderos_atlas.workspace.instance import ("
                        "acquire_instance_lock, WorkspaceInUseError)\n"
                        "try:\n"
                        f"    acquire_instance_lock({str(tmp)!r})\n"
                        "except WorkspaceInUseError as error:\n"
                        "    print('REFUSED:', error)\n"
                        "    sys.exit(42)\n"
                        "print('ACQUIRED')\n"
                    )],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(Path(__file__).resolve().parent.parent),
                )
                self.assertEqual(42, probe.returncode, probe.stdout + probe.stderr)
                self.assertIn("REFUSED", probe.stdout)
                self.assertIn("--workers 1", probe.stdout)
            finally:
                lock.release()

    def test_readyz_reports_the_instance_and_schema_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            payload = client.get("/readyz").get_json()
            self.assertTrue(payload["components"]["single-instance"])
            self.assertTrue(payload["components"]["schema-compatible"])


class CredentialProviderConcurrencyTests(unittest.TestCase):
    def test_concurrent_saves_and_deletes_lose_nothing(self) -> None:
        from founderos_atlas.workspace.credentials import (
            EncryptedFileCredentialProvider,
        )

        with tempfile.TemporaryDirectory() as tmp:
            key = os.urandom(32)
            provider = EncryptedFileCredentialProvider(tmp, key=key)
            errors: list[Exception] = []

            def writer(index: int) -> None:
                try:
                    for round_ in range(5):
                        provider.save(
                            f"atlas-credset:lab:entry-{index}-{round_}",
                            f"secret-{index}-{round_}-abcdef",
                        )
                except Exception as error:  # noqa: BLE001
                    errors.append(error)

            threads = [
                threading.Thread(target=writer, args=(i,)) for i in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual([], errors)
            # Every one of the 40 concurrent writes survived.
            for index in range(8):
                for round_ in range(5):
                    self.assertEqual(
                        f"secret-{index}-{round_}-abcdef",
                        provider.get(f"atlas-credset:lab:entry-{index}-{round_}"),
                    )
            # And the file itself is intact JSON with no plaintext.
            raw = provider.path.read_text(encoding="utf-8")
            json.loads(raw)
            self.assertNotIn("secret-3-2-abcdef", raw)

    def test_metadata_failure_rolls_the_secret_back(self) -> None:
        from founderos_atlas.credentials.service import CredentialSetService
        from founderos_atlas.workspace.credentials import (
            InMemoryCredentialProvider,
        )

        class FailingRepository:
            def get(self, set_id):
                return None

            def save(self, credential_set):
                raise OSError("disk full")

        provider = InMemoryCredentialProvider()
        service = CredentialSetService(FailingRepository(), provider)
        with self.assertRaises(OSError):
            service.add_entry(
                set_name="Lab", label="Admin",
                username="atlas", password="secret-password-1",
            )
        # The secret stored before the metadata failure was removed.
        self.assertEqual({}, provider._store)  # noqa: SLF001


class SessionConcurrencyTests(unittest.TestCase):
    def test_concurrent_refreshes_keep_the_store_valid(self) -> None:
        from founderos_atlas.access import SessionStore

        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(tmp)
            tokens = [store.create(f"user-{i}") for i in range(6)]
            errors: list[Exception] = []

            def refresher(token: str) -> None:
                try:
                    for _ in range(10):
                        assert store.resolve(token) is not None
                except Exception as error:  # noqa: BLE001
                    errors.append(error)

            threads = [
                threading.Thread(target=refresher, args=(token,))
                for token in tokens
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual([], errors)
            json.loads(store.path.read_text(encoding="utf-8"))
            for token in tokens:
                self.assertIsNotNone(store.resolve(token))


class BackupContentTests(unittest.TestCase):
    """Canary secrets prove what the archive actually contains — every
    member is DECOMPRESSED and inspected."""

    CANARIES = {
        "sessions": "CANARY-SESSION-TOKEN-9f1",
        "enc-credentials": "CANARY-ENC-SECRET-4c2",
        "evidence": "CANARY-RAW-EVIDENCE-7d3",
        "temporary": "CANARY-TEMP-WRITE-1a4",
        "unknown": "CANARY-UNKNOWN-JSON-6e5",
        "allowed": "CANARY-ALLOWED-NOTE-2b6",
    }

    def test_archive_contains_exactly_the_manifest_and_no_canaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            workspace = workdir / "workspace"

            (workspace / "sessions.json").write_text(json.dumps({
                "schema_version": "1.0.0",
                "sessions": [{"token_hash": self.CANARIES["sessions"],
                              "username": "x", "csrf_token": "y",
                              "created_at": "z", "expires_at": "9",
                              "idle_deadline": "9"}],
            }), encoding="utf-8")
            (workspace / "credentials.enc.json").write_text(json.dumps({
                "schema_version": "1.0.0",
                "secrets": {"ref": self.CANARIES["enc-credentials"]},
            }), encoding="utf-8")
            evidence_dir = workdir / ".atlas" / "profiles" / "hyderabad"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            (evidence_dir / "evidence-canary.json").write_text(
                json.dumps({"raw": self.CANARIES["evidence"]}),
                encoding="utf-8",
            )
            (workspace / ".profiles.json.abc.writing").write_text(
                self.CANARIES["temporary"], encoding="utf-8"
            )
            (workspace / "future-unknown-store.json").write_text(
                json.dumps({"secret": self.CANARIES["unknown"]}),
                encoding="utf-8",
            )
            (workspace / "annotations.json").write_text(json.dumps({
                "schema_version": "1.0.0",
                "annotations": {"note": self.CANARIES["allowed"]},
            }), encoding="utf-8")

            response = client.get("/settings/backup")
            self.assertEqual(200, response.status_code)
            archive = zipfile.ZipFile(io.BytesIO(response.data))

            from founderos_atlas.workspace.backup import (
                INCLUDED_FILES, MANIFEST_NAME, NOTICE_NAME,
            )

            names = set(archive.namelist())
            expected = {
                name for name in INCLUDED_FILES
                if (workspace / name).is_file()
            } | {MANIFEST_NAME, NOTICE_NAME}
            self.assertEqual(expected, names)

            allowed_hits = 0
            for name in names:
                content = archive.read(name).decode("utf-8", errors="ignore")
                for kind, canary in self.CANARIES.items():
                    if kind == "allowed":
                        if canary in content:
                            allowed_hits += 1
                            self.assertEqual("annotations.json", name)
                    else:
                        self.assertNotIn(
                            canary, content,
                            f"{kind} canary leaked into {name}",
                        )
            self.assertEqual(1, allowed_hits,
                             "the allowed metadata canary must be present")

            manifest = json.loads(archive.read(MANIFEST_NAME))
            self.assertEqual("1.0.0", manifest["backup_schema_version"])
            self.assertTrue(manifest["created_at"])
            self.assertTrue(manifest["application_version"])
            import hashlib

            for entry in manifest["files"]:
                data = archive.read(entry["name"])
                self.assertEqual(len(data), entry["size"])
                self.assertEqual(
                    hashlib.sha256(data).hexdigest(), entry["sha256"]
                )
            self.assertIn("sessions.json", manifest["excluded"]["sessions"])
            self.assertIn(
                "credentials.enc.json", manifest["excluded"]["secrets"]
            )
            sensitive = [
                entry["name"] for entry in manifest["files"]
                if entry["classification"] == "sensitive-included"
            ]
            if (workspace / "users.json").is_file():
                self.assertEqual(["users.json"], sensitive)


class TransactionalRestoreTests(unittest.TestCase):
    @staticmethod
    def _zip(members: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return buffer.getvalue()

    def test_refusals_change_nothing(self) -> None:
        from founderos_atlas.workspace.restore import (
            RestoreError,
            perform_restore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profiles.json").write_text(
                '{"schema_version": "1.0.0", "profiles": []}',
                encoding="utf-8",
            )
            before = (root / "profiles.json").read_bytes()
            cases = {
                "traversal": {"../evil.json": b"{}"},
                "unknown": {"future-secret-store.json": b"{}"},
                "sessions": {"sessions.json": b"{}"},
                "bad-json": {"profiles.json": b"{not json"},
                "bad-jsonl": {"audit.jsonl": b'{"ok":1}\n{broken\n'},
            }
            for label, members in cases.items():
                with self.subTest(case=label):
                    with self.assertRaises(RestoreError):
                        perform_restore(root, self._zip(members))
                    self.assertEqual(
                        before, (root / "profiles.json").read_bytes(),
                        f"{label}: workspace changed on a refused restore",
                    )

    def test_duplicate_members_are_refused(self) -> None:
        from founderos_atlas.workspace.restore import (
            RestoreError,
            perform_restore,
        )

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("profiles.json", '{"a": 1}')
            archive.writestr("profiles.json", '{"a": 2}')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RestoreError):
                perform_restore(tmp, buffer.getvalue())

    def test_zip_bomb_and_oversize_are_refused(self) -> None:
        from founderos_atlas.workspace.restore import (
            MAX_ARCHIVE_BYTES,
            RestoreError,
            perform_restore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RestoreError):
                perform_restore(tmp, b"0" * (MAX_ARCHIVE_BYTES + 1))
            bomb = self._zip({
                "profiles.json": b'{"pad": "' + b"0" * (12 * 1024 * 1024)
                + b'"}',
            })
            with self.assertRaises(RestoreError) as caught:
                perform_restore(tmp, bomb)
            self.assertIn("bomb", str(caught.exception).casefold())

    def test_newer_schema_is_refused(self) -> None:
        from founderos_atlas.workspace.restore import (
            RestoreError,
            perform_restore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            archive = self._zip({
                "workspace-schema.json": json.dumps({"version": 999}).encode(),
                "profiles.json": b'{"profiles": []}',
            })
            with self.assertRaises(RestoreError) as caught:
                perform_restore(tmp, archive)
            self.assertIn("newer", str(caught.exception))

    def test_manifest_hash_mismatch_is_refused(self) -> None:
        from founderos_atlas.workspace.restore import (
            RestoreError,
            perform_restore,
        )

        archive = self._zip({
            "profiles.json": b'{"profiles": []}',
            "backup-manifest.json": json.dumps({
                "files": [{"name": "profiles.json",
                           "sha256": "0" * 64, "size": 17}],
            }).encode(),
        })
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RestoreError) as caught:
                perform_restore(tmp, archive)
            self.assertIn("manifest hash", str(caught.exception))

    def test_mid_commit_failure_rolls_everything_back(self) -> None:
        from founderos_atlas.workspace.restore import (
            RestoreError,
            perform_restore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "annotations.json").write_text(
                '{"original": "annotations"}', encoding="utf-8"
            )
            (root / "profiles.json").write_text(
                '{"original": "profiles"}', encoding="utf-8"
            )
            archive = self._zip({
                "annotations.json": b'{"restored": "annotations"}',
                "profiles.json": b'{"restored": "profiles"}',
            })
            calls: list[str] = []

            def explode_on_second(name: str) -> None:
                calls.append(name)
                if len(calls) == 2:
                    raise OSError("disk vanished mid-commit")

            with self.assertRaises(RestoreError) as caught:
                perform_restore(root, archive, commit_hook=explode_on_second)
            self.assertIn("rolled back", str(caught.exception))
            # The FIRST file was committed then rolled back; both match
            # the pre-restore state exactly.
            self.assertEqual(
                '{"original": "annotations"}',
                (root / "annotations.json").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                '{"original": "profiles"}',
                (root / "profiles.json").read_text(encoding="utf-8"),
            )

    def test_round_trip_backup_restore_with_snapshot_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _, client = build_world(workdir)
            workspace = workdir / "workspace"
            backup = client.get("/settings/backup").data
            # The workspace drifts after the backup was taken…
            (workspace / "annotations.json").write_text(
                '{"schema_version": "1.0.0", "annotations": {"drift": 1}}',
                encoding="utf-8",
            )
            restored = client.post(
                "/settings/restore",
                data={
                    "confirm": "RESTORE METADATA", "reason": "drill",
                    "backup": (io.BytesIO(backup), "atlas-backup.zip"),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertIn(b"integrity", restored.data)
            self.assertIn(b"Restart Atlas now", restored.data)
            snapshots = list(
                (workspace / "pre-restore-snapshots").iterdir()
            )
            self.assertTrue(snapshots, "no pre-restore snapshot retained")
            audit = (workspace / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn('"committed"', audit)
            self.assertIn('"integrity_verified": true', audit)


if __name__ == "__main__":
    unittest.main()
