"""PR-174 — the topology site layout is confined, and the viewer
guards its own invariants.

The defect these tests pin: the site force pass attracts only site
pairs joined by a cross-site link, so an estate whose sites never link
to each other had NO inward force — 260 iterations of unopposed
repulsion inflated the seeded ring 12.5× into a 78,000-unit canvas
with the camera parked over the empty middle.

The physics tests run the REAL ``siteForceLayout`` extracted verbatim
from the template (between the ATLAS_SITE_FORCE markers) under node —
never a Python re-implementation, which would only prove the copy.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src" / "founderos_atlas" / "visualization" / "templates"
    / "topology.html"
)

BEGIN = "// ---- ATLAS_SITE_FORCE_BEGIN"
END = "// ---- ATLAS_SITE_FORCE_END"

NODE = shutil.which("node")


def _force_pass_source() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    start = text.index(BEGIN)
    stop = text.index(END)
    return text[start:stop]


def _run_layout(blocks: list[dict], links: dict[str, int]) -> dict:
    """Execute the template's own siteForceLayout under node."""

    source = _force_pass_source()
    weights = json.dumps(links)
    harness = f"""
{source}
const blocks = {json.dumps(blocks)};
const W = blocks.map(() => ({{}}));
const weights = {weights};
for (const key of Object.keys(weights)) {{
  const [a, b] = key.split('-').map(Number);
  W[a][b] = weights[key]; W[b][a] = weights[key];
}}
const frame = siteForceLayout(blocks, W);
const radii = blocks.map(b => Math.hypot(b.cx, b.cy));
const out = {{
  half: frame.half,
  k: frame.k,
  maxRadius: Math.max(...radii),
  meanRadius: radii.reduce((s, r) => s + r, 0) / radii.length,
  positions: blocks.map(b => ({{ cx: b.cx, cy: b.cy }})),
}};
console.log(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "harness.js"
        script.write_text(harness, encoding="utf-8")
        result = subprocess.run(
            [NODE, str(script)], capture_output=True, text=True,
            timeout=60, check=True,
        )
    return json.loads(result.stdout.strip())


def _ring(n: int, radius: float, rx: float = 450, ry: float = 320) -> list[dict]:
    """n ovals seeded on a circle — exactly how renderSiteOvalsGrid
    seeds them."""

    blocks = []
    for idx in range(n):
        ang = -math.pi / 2 + 2 * math.pi * idx / n
        blocks.append({
            "idx": idx, "rx": rx, "ry": ry,
            "hw": rx + 16, "hh": ry + 16,
            "cx": math.cos(ang) * radius,
            "cy": math.sin(ang) * radius,
        })
    return blocks


@unittest.skipUnless(NODE, "node is not available")
class SiteForcePhysicsTests(unittest.TestCase):
    def test_unconnected_sites_stay_inside_the_frame(self) -> None:
        """The headline (PR-174 root cause): 21 sites with ZERO
        cross-site links must settle inside the computed frame — the
        live estate measured a 39,253-unit ring before the fix."""

        result = _run_layout(_ring(21, 3150.0), {})
        self.assertLessEqual(result["maxRadius"],
                             result["half"] * math.sqrt(2) + 1)
        # And nowhere near the explosion: the old code reached 39,253.
        self.assertLess(result["maxRadius"], 8000)

    def test_the_frame_is_sized_from_the_ovals(self) -> None:
        """The frame is the area the ovals genuinely need — it grows
        with the estate, it is not an arbitrary constant."""

        small = _run_layout(_ring(4, 700.0), {})
        large = _run_layout(_ring(40, 6000.0), {})
        self.assertLess(small["half"], large["half"])
        # 21 ovals of 900x640 need roughly sqrt(21*900*640*4)/2 ~ 3.5k.
        typical = _run_layout(_ring(21, 3150.0), {})
        self.assertLess(2000, typical["half"])
        self.assertLess(typical["half"], 6000)

    def test_connected_sites_still_cluster(self) -> None:
        """No regression for estates WITH cross-site links: connected
        pairs must end nearer than unconnected ones."""

        links = {"0-1": 3, "1-2": 3, "2-3": 3}
        result = _run_layout(_ring(8, 1400.0), links)
        pos = result["positions"]

        def dist(a, b):
            return math.hypot(pos[a]["cx"] - pos[b]["cx"],
                              pos[a]["cy"] - pos[b]["cy"])

        connected = [dist(0, 1), dist(1, 2), dist(2, 3)]
        unconnected = [dist(0, 4), dist(1, 5), dist(2, 6), dist(3, 7),
                       dist(4, 6), dist(5, 7)]
        self.assertLess(
            sum(connected) / len(connected),
            sum(unconnected) / len(unconnected),
        )

    def test_single_site_is_untouched(self) -> None:
        result = _run_layout(_ring(1, 0.0), {})
        self.assertEqual(0.0, result["maxRadius"])


class ViewerInvariantContractTests(unittest.TestCase):
    """The template carries the landing guarantee and the
    development-mode diagnostics — asserted the way the visual-quality
    suite asserts its contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_the_force_pass_is_extracted_and_confined(self) -> None:
        self.assertIn(BEGIN, self.html)
        self.assertIn(END, self.html)
        self.assertIn("function siteForceLayout(blocks, W, opts)", self.html)
        # Gravity and the frame clamp — the two additions that keep an
        # unconnected estate bounded. Their absence is the PR-174 bug.
        self.assertIn("(gx - blocks[i].cx) * GRAVITY", self.html)
        self.assertIn("Math.max(-half, Math.min(half,", self.html)
        self.assertIn("siteForceLayout(blocks, W);", self.html)

    def test_the_viewport_never_rests_on_empty_space(self) -> None:
        self.assertIn("function nodesInExtent()", self.html)
        self.assertIn("nodesInExtent().length === 0", self.html)
        self.assertIn("cy.center(best)", self.html)
        self.assertIn(
            "Showing the nearest cluster - zoom out to see the whole "
            "estate",
            self.html,
        )

    def test_diagnostics_are_opt_in_and_cover_the_invariants(self) -> None:
        self.assertIn("const DIAG = /[?&]diag=1", self.html)
        self.assertIn("if (!DIAG) { return; }", self.html)
        self.assertIn("runViewerDiagnostics('viewport')", self.html)
        self.assertIn("runViewerDiagnostics('rebuild')", self.html)
        for invariant in (
            "non-finite coordinates",
            "the bounding box is not finite",
            "the camera transform is not finite",
            "no node is visible in the viewport",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, self.html)
        self.assertIn("diag-banner", self.html)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
