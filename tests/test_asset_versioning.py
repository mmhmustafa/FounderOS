"""Static assets carry content-hash versions (cache correctness).

Browsers heuristically cache static files without revalidating, so an
upgraded server kept serving pages whose JavaScript was yesterday's from
the browser cache — a fix that was live in the code stayed broken on the
operator's screen. Content-hashed URLs make an asset's address change
exactly when its bytes do.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from tests.test_polish import build_world

STATIC = Path("src/founderos_atlas/web/static")


class AssetVersioningTests(unittest.TestCase):
    def test_every_rendered_asset_url_is_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            for path in ("/", "/discovery/wizard", "/credentials",
                         "/incidents", "/compass"):
                page = client.get(path).get_data(as_text=True)
                for ref in re.findall(
                    r'(?:src|href)="(/static/[^"]+)"', page
                ):
                    self.assertIn(
                        "?v=", ref,
                        f"{path}: unversioned static asset {ref}",
                    )

    def test_version_is_the_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp), discover=False)
            page = client.get("/discovery/wizard").get_data(as_text=True)
            match = re.search(
                r'src="/static/(atlas-wizard\.js)\?v=([0-9a-f]{12})"', page
            )
            self.assertIsNotNone(match, "wizard script not found")
            expected = sha256(
                (STATIC / match.group(1)).read_bytes()
            ).hexdigest()[:12]
            self.assertEqual(
                expected, match.group(2),
                "the version must change exactly when the file does",
            )

    def test_no_template_bypasses_the_helper(self) -> None:
        for template in Path(
            "src/founderos_atlas/web/templates"
        ).glob("*.html"):
            self.assertNotIn(
                "url_for('static'",
                template.read_text(encoding="utf-8"),
                f"{template.name}: use asset_url() for static assets",
            )


if __name__ == "__main__":
    unittest.main()
