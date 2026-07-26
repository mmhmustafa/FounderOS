"""Web composition for operational telemetry and contextual integrations."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from founderos_atlas.audit import AuditLog
from founderos_atlas.telemetry import (
    FACT_DEVICE_HEALTH,
    MappingTelemetryAdapter,
)
from founderos_atlas.web import create_app


class TelemetryWebTests(unittest.TestCase):
    def test_registered_provider_collects_through_audited_web_boundary(
        self,
    ) -> None:
        observed = datetime.now(timezone.utc).isoformat()
        adapter = MappingTelemetryAdapter(
            "rest-provider",
            lambda: [{
                "kind": FACT_DEVICE_HEALTH,
                "entity_id": "edge-1",
                "metric": "reachability",
                "value": "down",
                "unit": "state",
                "observed_at": observed,
                "provider_ref": "event:42",
                "metadata": {"access_token": "WEB-CANARY"},
            }],
            source="rest",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = create_app(
                output_dir=root / "out",
                workspace_root=root / "workspace",
                telemetry_adapters=(adapter,),
            )
            app.config.update(TESTING=True)
            client = app.test_client()

            page = client.get("/telemetry")
            self.assertEqual(200, page.status_code)
            self.assertIn(b"rest-provider", page.data)
            self.assertIn(b"configured", page.data)
            self.assertNotIn(b"WEB-CANARY", page.data)

            collected = client.post(
                "/telemetry/collect",
                data={"adapter": "rest-provider", "scope": "lab"},
            )
            self.assertEqual(302, collected.status_code)
            rendered = client.get("/telemetry?scope=lab")
            self.assertIn(b"edge-1", rendered.data)
            self.assertIn(b"event:42", rendered.data)
            self.assertIn(b"collection:", rendered.data)
            self.assertNotIn(b"WEB-CANARY", rendered.data)

            topology = client.get("/topology?scope=all")
            self.assertEqual(200, topology.status_code)
            self.assertIn(b"Live context", topology.data)
            settings = client.get("/settings")
            self.assertEqual(200, settings.status_code)
            self.assertIn(b"Operational telemetry", settings.data)

            events = AuditLog(root / "workspace").events(
                category="telemetry-collection"
            )
            self.assertEqual(1, len(events))
            self.assertEqual("success", events[0].outcome)
            self.assertNotIn(
                "WEB-CANARY",
                AuditLog(root / "workspace").path.read_text(
                    encoding="utf-8"
                ),
            )

    def test_web_provider_failure_never_returns_provider_exception(self) -> None:
        def fail():
            raise RuntimeError("authorization=WEB-FAIL-CANARY")

        adapter = MappingTelemetryAdapter("cloud", fail, source="api")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = create_app(
                output_dir=root / "out",
                workspace_root=root / "workspace",
                telemetry_adapters=(adapter,),
            )
            app.config.update(TESTING=True)
            client = app.test_client()
            response = client.post(
                "/telemetry/collect",
                data={"adapter": "cloud", "scope": "enterprise"},
                follow_redirects=True,
            )
            self.assertEqual(200, response.status_code)
            self.assertIn(
                b"provider could not complete collection", response.data
            )
            self.assertNotIn(b"WEB-FAIL-CANARY", response.data)
            self.assertNotIn(
                "WEB-FAIL-CANARY",
                AuditLog(root / "workspace").path.read_text(
                    encoding="utf-8"
                ),
            )


if __name__ == "__main__":
    unittest.main()
