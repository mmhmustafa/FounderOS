"""Packet trace (Phase 1): the topology viewer's animated path trace.

One engine, one record: /api/paths/trace runs the SAME deterministic
path investigation as the Paths page and persists to the same history,
returning per-hop verdicts the animation draws. Declared protocol/port
ride as recorded intent with the standing honesty note — ACL/firewall
policy is NOT evaluated in this phase, and the UI says so.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_polish import build_world

VIEWER = Path("src/founderos_atlas/visualization/templates/topology.html")


def _two_devices(client) -> tuple[str, str]:
    # build_world's Hyderabad fixture: A1 -- A2 with GW attached.
    return "A1", "A2"


class TraceApiTests(unittest.TestCase):
    def test_trace_returns_hops_and_persists_to_paths_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            source, destination = _two_devices(client)
            response = client.post("/api/paths/trace", json={
                "source": source, "destination": destination,
                "protocol": "tcp", "port": 443,
            })
            self.assertEqual(200, response.status_code)
            body = response.get_json()
            self.assertIn("hops", body)
            self.assertIn("status", body)
            for hop in body["hops"]:
                self.assertIn(
                    hop["status"], ("pass", "warning", "failed", "unknown")
                )
            # Declared intent is recorded with the honesty note.
            self.assertEqual(
                {"protocol": "tcp", "port": "443"}, body.get("intent")
            )
            self.assertIn("NOT", body.get("intent_note", ""))
            # Same record the Paths page shows.
            paths = client.get("/paths?scope=all").get_data(as_text=True)
            self.assertIn(source, paths)

    def test_validation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            no_source = client.post("/api/paths/trace", json={
                "destination": "x",
            })
            self.assertEqual(400, no_source.status_code)
            bad_protocol = client.post("/api/paths/trace", json={
                "source": "a", "destination": "b", "protocol": "gre",
            })
            self.assertEqual(400, bad_protocol.status_code)
            bad_port = client.post("/api/paths/trace", json={
                "source": "a", "destination": "b", "protocol": "tcp",
                "port": 99999,
            })
            self.assertEqual(400, bad_port.status_code)
            icmp_port = client.post("/api/paths/trace", json={
                "source": "a", "destination": "b", "protocol": "icmp",
                "port": 80,
            })
            self.assertEqual(400, icmp_port.status_code)

    def test_unknown_devices_get_an_honest_engine_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, client = build_world(Path(tmp))
            response = client.post("/api/paths/trace", json={
                "source": "does-not-exist", "destination": "also-missing",
            })
            # The engine answers with an evidence-based unknown result,
            # not a 500 and not an invented path.
            self.assertEqual(200, response.status_code)
            body = response.get_json()
            self.assertNotEqual("connected", body.get("status"))

    def test_viewer_cannot_run_a_trace(self) -> None:
        from tests.test_production_security import (
            production_world, sign_in,
        )

        with production_world() as (app, _workdir):
            viewer, csrf = sign_in(app, "viewer")
            response = viewer.post(
                "/api/paths/trace",
                json={"source": "a", "destination": "b"},
                headers={"X-Atlas-CSRF": csrf},
            )
            self.assertEqual(403, response.status_code)


class ViewerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.viewer = VIEWER.read_text(encoding="utf-8")

    def test_right_click_sets_source_and_destination(self) -> None:
        self.assertIn("Trace packet from here", self.viewer)
        self.assertIn("Trace packet to here", self.viewer)
        self.assertIn("atlasTraceSet", self.viewer)

    def test_panel_offers_protocol_and_port(self) -> None:
        self.assertIn('id="trace-proto"', self.viewer)
        self.assertIn('id="trace-port"', self.viewer)
        # ICMP has no port; the panel enforces it like the API does.
        self.assertIn("protoSelect.value === 'icmp'", self.viewer)

    def test_animation_stops_at_the_failed_hop(self) -> None:
        self.assertIn("the packet goes no further", self.viewer)
        self.assertIn("trace-failed", self.viewer)
        self.assertIn("Stopped at ", self.viewer)

    def test_honesty_notes_are_present(self) -> None:
        # Un-evaluated hops are dashed, never painted healthy, and a
        # connected verdict caveats that port policy is not evaluated.
        self.assertIn("trace-unknown", self.viewer)
        self.assertIn("policy is not evaluated yet", self.viewer)

    def test_reduced_motion_is_respected(self) -> None:
        self.assertIn("prefers-reduced-motion", self.viewer)

    def test_the_trace_path_is_not_green(self) -> None:
        """A healthy BGP/OSPF link is drawn green (#16a34a). The trace
        used the SAME green, so on a path of healthy links the packet's
        route was invisible — the operator's exact complaint. The pass
        style must not carry that green."""

        pass_style = self.viewer.split("edge.trace-pass", 1)[1][:160]
        self.assertNotIn("#16a34a", pass_style)
        self.assertIn("#0891b2", pass_style)   # cyan — unused elsewhere

    def test_the_trace_colour_beats_a_healthy_links_style(self) -> None:
        """The real defect behind the green trace: a healthy BGP/OSPF
        edge carries an ATTRIBUTE style (bgp_health/ospf_health), and in
        Cytoscape an attribute selector outranks a class selector — so
        the .trace-pass CLASS lost and the packet's route stayed link-
        green. The trace must paint its colour on as an inline element
        style, which outranks both."""

        self.assertIn("function styleTraceEdge", self.viewer)
        self.assertIn("styleTraceEdge(edge,", self.viewer)
        self.assertIn("TRACE_EDGE_INLINE", self.viewer)
        # And the overlays are torn down, not left painted on.
        self.assertIn("removeStyle(TRACE_EDGE_PROPS)", self.viewer)

    def test_a_connected_path_flows_a_packet(self) -> None:
        """The hop-by-hop reveal draws the route but does not read as a
        packet moving; a dot that circulates the connected path does."""

        self.assertIn("startFlow(nodes)", self.viewer)
        self.assertIn("function startFlow", self.viewer)

    def test_the_flow_stops_when_the_trace_is_cleared(self) -> None:
        # A dot left animating over a cleared trace is a leak the eye
        # reads as a live packet on a path that is no longer shown.
        clear = self.viewer.split("function clearTrace", 1)[1][:160]
        self.assertIn("stopFlow()", clear)

    def test_the_packet_does_not_flow_a_path_it_could_not_complete(self) -> None:
        """A stopped packet must not then be shown flowing to the
        destination. The flow is gated on reduced motion and only ever
        started from the connected verdict."""

        flow = self.viewer.split("function startFlow", 1)[1][:200]
        self.assertIn("if (reducedMotion) { return; }", flow)

    def test_a_policy_drop_offers_a_what_if_fix(self) -> None:
        """When the trace stops at an ACL or firewall deny, the operator can
        simulate the fix: re-run assuming that hop permits the flow, to see
        if it then gets through (or where it stops next). The offer is
        scoped to policy drops — a link or management failure has no rule to
        permit away."""

        self.assertIn('id="trace-whatif"', self.viewer)
        self.assertIn("assume_permit_at: assume", self.viewer)
        self.assertIn("firewall-deny", self.viewer)
        self.assertIn("state.whatIfDevice = f.device", self.viewer)
        # The offer is gated on a policy failure_type, not any failure.
        gate = self.viewer.split("var policyDeny", 1)[1][:160]
        self.assertIn("'acl-deny'", gate)
        self.assertIn("'firewall-deny'", gate)

    def test_the_flow_can_name_which_address_it_is_for(self) -> None:
        """A device owns several addresses. Without naming one, a route to
        ANY of them satisfies the forwarding check — which can validate the
        management path instead of the flow being asked about."""

        self.assertIn('id="trace-dst-ip"', self.viewer)
        self.assertIn("destination_address:", self.viewer)
        # Both surfaces that run the engine offer it, or the two disagree
        # about what a trace means.
        paths = Path(
            "src/founderos_atlas/web/templates/paths.html"
        ).read_text(encoding="utf-8")
        self.assertIn('name="destination_address"', paths)

    def test_the_two_ends_of_the_question_are_marked_apart(self) -> None:
        """Every hop wore the same cyan ring, so on a long path the source
        and destination were indistinguishable from the transit devices
        between them."""

        self.assertIn("node.trace-endpoint-src", self.viewer)
        self.assertIn("node.trace-endpoint-dst", self.viewer)
        self.assertIn("addClass('trace-endpoint-src')", self.viewer)
        self.assertIn("addClass('trace-endpoint-dst')", self.viewer)
        # The marks are explained, or a coloured ring means nothing.
        self.assertIn('id="trace-key"', self.viewer)

    def test_the_destination_mark_is_the_device_that_was_asked_for(self) -> None:
        """NOT the last hop reached. On a blocked trace they differ, and
        badging the blocking firewall as the destination would misreport
        the answer — so the mark follows the declared destination, which
        stays visible even when the packet never got there."""

        self.assertIn("var dstNode = nodeFor(state.destination);", self.viewer)
        marked = self.viewer.split("var dstNode = nodeFor", 1)[1][:400]
        self.assertIn("pathColl = pathColl.union(dstNode)", marked)

    def test_the_destination_mark_never_borrows_a_measured_colour(self) -> None:
        # Violet is the peer edge and the live probe's OBSERVED path. An
        # endpoint mark in that colour would read as "this was measured".
        dst = self.viewer.split("node.trace-endpoint-dst", 1)[1][:260]
        self.assertNotIn("#7c3aed", dst)
        self.assertIn("#db2777", dst)

    def test_everything_off_the_path_recedes(self) -> None:
        """On an estate of 58 links the path competed with the whole map.
        Dimmed, never hidden: the context stays, and nothing is removed
        from the map to make the answer look tidier."""

        self.assertIn(".trace-dimmed", self.viewer)
        self.assertIn("addClass('trace-dimmed')", self.viewer)
        self.assertIn("difference(pathColl.union(pathEdges))", self.viewer)
        # The regions live on their own canvas, out of reach of element
        # dimming, and would otherwise stay vivid while the map receded.
        self.assertIn("function setRegionsFaded", self.viewer)
        self.assertIn("protocol-region-canvas", self.viewer)

    def test_clearing_a_trace_leaves_nothing_faded_or_badged(self) -> None:
        clear = self.viewer.split("function clearTrace", 1)[1][:1400]
        self.assertIn("trace-dimmed", clear)
        self.assertIn("trace-endpoint-src", clear)
        self.assertIn("setRegionsFaded(false)", clear)

    def test_the_routes_a_path_relies_on_can_be_withdrawn(self) -> None:
        """"What breaks if this route goes away?" — the panel lists the route
        each hop forwarded on and offers to withdraw it and re-run. It reads
        hop.route structurally rather than parsing the evidence sentence, and
        lists only hops that HAD a captured table, so it is never padded with
        guesses."""

        self.assertIn('id="trace-routes"', self.viewer)
        self.assertIn("function renderRoutes", self.viewer)
        self.assertIn("if (!hop.route || !hop.route.prefix) { return; }",
                      self.viewer)
        self.assertIn("withdraw_routes: state.withdrawn", self.viewer)
        self.assertIn("Withdraw", self.viewer)

    def test_every_assumption_can_be_taken_back(self) -> None:
        """An assumption with no way back is a trap: once a hop was assumed
        to permit, or a route withdrawn, every later verdict was
        hypothetical and the only escape was clearing the whole trace and
        setting it up again. Revert drops BOTH kinds and re-runs."""

        self.assertIn('id="trace-revert"', self.viewer)
        self.assertIn("function assumptionsActive", self.viewer)
        revert = self.viewer.split("revertButton.addEventListener", 1)[1][:420]
        self.assertIn("state.assumePermit = []", revert)
        self.assertIn("state.withdrawn = []", revert)
        self.assertIn("runTrace()", revert)

    def test_a_single_withdrawal_can_be_undone_on_its_own(self) -> None:
        """With several assumptions in play, the blanket revert is the
        wrong tool for questioning just one of them: it drops the lot. Each
        withdrawn route carries its own Restore, which leaves every other
        assumption standing."""

        self.assertIn("'Restore'", self.viewer)
        restore = self.viewer.split("button.textContent = 'Restore'", 1)[1][:520]
        self.assertIn("state.withdrawn.filter", restore)
        self.assertIn("runTrace()", restore)
        # Filtered by BOTH device and prefix — the same prefix withdrawn at
        # two devices is two separate assumptions.
        self.assertIn("item.device === entry.device", restore)
        self.assertIn("item.prefix === entry.prefix", restore)

    def test_a_withdrawn_route_stays_listed_when_it_breaks_the_path(self) -> None:
        """The row used to be derived purely from the report, so a
        withdrawal that broke the path took its own hop off the re-run and
        the row vanished — removing the only per-route way back at exactly
        the moment it was wanted. The withdrawal list is state, and rows
        are the union of it and the report."""

        render = self.viewer.split("function renderRoutes", 1)[1][:1500]
        self.assertIn("state.withdrawn.forEach", render)
        self.assertIn("if (seen[routeKey(item.device, item.prefix)]) { return; }",
                      render)

    def test_the_blanket_revert_says_it_is_blanket(self) -> None:
        # With a per-route Restore alongside it, a button labelled just
        # "Revert what-if" reads as undoing the one you are looking at.
        self.assertIn(">Revert all</button>", self.viewer)
        self.assertIn("Drop EVERY assumption at once", self.viewer)

    def test_the_way_back_is_offered_exactly_when_it_applies(self) -> None:
        # Shown whenever an assumption is live — including a withdrawn
        # route, which had no revert at all — and hidden once none is.
        self.assertIn("revertButton.hidden = !assumptionsActive()", self.viewer)
        self.assertIn("state.withdrawn.length > 0", self.viewer)

    def test_the_routes_it_relies_on_are_shown_in_full(self) -> None:
        """A truncated prefix or next hop is not evidence anyone can act
        on, and long next hops (IPv6, %-scoped) are normal — so the route
        text wraps onto its own line instead of being ellipsised."""

        style = self.viewer.split("#trace-routes .trace-route-what", 1)[1][:200]
        self.assertNotIn("text-overflow: ellipsis", style)
        self.assertNotIn("white-space: nowrap", style)
        self.assertIn("overflow-wrap: anywhere", style)

    def test_the_panel_cannot_push_its_own_content_offscreen(self) -> None:
        # A long route list grew the panel past the viewport, so the rows
        # at the bottom could not be read at all — the reported symptom.
        panel = self.viewer.split("#trace-panel { position", 1)[1][:340]
        self.assertIn("max-height: calc(100% - 24px)", panel)
        self.assertIn("overflow-y: auto", panel)

    def test_a_withdrawal_is_named_in_every_line_it_produces(self) -> None:
        prefix = self.viewer.split("function whatIfPrefix", 1)[1][:600]
        self.assertIn("withdrawn from", prefix)
        # A fresh trace and Clear both forget the withdrawals.
        run = self.viewer.split("runButton.addEventListener", 1)[1][:260]
        self.assertIn("state.withdrawn = []", run)

    def test_a_what_if_result_is_labelled_hypothetical(self) -> None:
        """Every line a what-if produces names the assumed hops, so it can
        never be mistaken for the real verdict."""

        self.assertIn("function whatIfPrefix", self.viewer)
        self.assertIn("assuming ", self.viewer)
        # A fresh trace and a Clear both forget the assumed hops.
        run = self.viewer.split("runButton.addEventListener", 1)[1][:200]
        self.assertIn("state.assumePermit = []", run)

    def test_the_flow_can_be_paused_and_resumed(self) -> None:
        """A packet looping forever with no off switch is a nuisance; the
        operator must be able to stop it without clearing the trace, and
        start it again."""

        self.assertIn('id="trace-flow"', self.viewer)
        self.assertIn("if (flowActive) { stopFlow(); }", self.viewer)
        self.assertIn("else if (state.flowNodes) { startFlow(state.flowNodes)",
                      self.viewer)
        self.assertIn("'Pause flow' : 'Resume flow'", self.viewer)

    def test_the_animation_speed_is_adjustable(self) -> None:
        """Fixed timing suited nobody — too slow to skim, too fast to
        follow a long path. The Speed selector re-times the very next hop
        of both the reveal and the flow."""

        self.assertIn('id="trace-speed"', self.viewer)
        self.assertIn("function speedFactor", self.viewer)
        self.assertIn("620 * speedFactor()", self.viewer)   # hop reveal
        self.assertIn("430 * speedFactor()", self.viewer)   # flowing packet

    def test_replay_reframes_the_whole_path(self) -> None:
        """A failed trace ends centred on the blocked hop, so a Replay
        that did not reframe started from an off-screen source and the
        packet's start was never seen — the reported bug."""

        run = self.viewer.split("function runAnimation", 1)[1][:3200]
        self.assertIn("fit: { eles: pathColl", run)


if __name__ == "__main__":
    unittest.main()
