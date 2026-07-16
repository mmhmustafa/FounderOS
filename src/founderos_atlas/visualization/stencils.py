"""The Atlas device stencil set: role icons for the topology viewer.

Original, filled device icons — no vendor artwork. Each icon is drawn to
read as network gear at a glance (a router puck, a switch, a server, a
monitor), the way a Packet-Tracer diagram does, while remaining Atlas's own
art so it is safe to ship and works offline.

Two channels carry meaning, deliberately kept separate so the set survives
grayscale and colour-blindness:

- **SHAPE** encodes the device *role* — a router is always a disc, a switch
  always a box, whatever the colour.
- **COLOUR** here is a role accent (so the diagram is legible and pleasant);
  operational *state* — new / changed / removed / selected — is carried by
  the node border ring in the viewer, never by the icon. So the icon says
  "what", the ring says "how it's doing".
"""

from __future__ import annotations

from urllib.parse import quote

from founderos_atlas.platforms.classify import (
    ROLE_ACCESS_POINT,
    ROLE_CLOUD,
    ROLE_FIREWALL,
    ROLE_L2_SWITCH,
    ROLE_L3_SWITCH,
    ROLE_LINUX_HOST,
    ROLE_LOAD_BALANCER,
    ROLE_ROUTER,
    ROLE_SERVER,
    ROLE_UNKNOWN,
    ROLE_UNRESOLVED,
)


# Role accent palette. Main = face, dark = shaded side/base, light = top
# highlight, line = white detail. Chosen to be distinct and calm.
_PALETTE = {
    ROLE_ROUTER: ("#3b82f6", "#1d4ed8", "#93c5fd"),
    ROLE_L2_SWITCH: ("#14b8a6", "#0f766e", "#5eead4"),
    ROLE_L3_SWITCH: ("#0ea5e9", "#0369a1", "#7dd3fc"),
    ROLE_FIREWALL: ("#ef4444", "#b91c1c", "#fca5a5"),
    ROLE_SERVER: ("#64748b", "#334155", "#cbd5e1"),
    ROLE_LINUX_HOST: ("#6366f1", "#4338ca", "#c7d2fe"),
    ROLE_ACCESS_POINT: ("#8b5cf6", "#6d28d9", "#ddd6fe"),
    ROLE_LOAD_BALANCER: ("#f59e0b", "#b45309", "#fcd34d"),
    ROLE_CLOUD: ("#38bdf8", "#0284c7", "#e0f2fe"),
    ROLE_UNKNOWN: ("#94a3b8", "#475569", "#e2e8f0"),
    ROLE_UNRESOLVED: ("#cbd5e1", "#94a3b8", "#f1f5f9"),
}

_LINE = "#ffffff"


# The viewer rasterizes each icon to a bitmap texture. A large intrinsic
# size (viewBox stays 64, but the SVG declares 512×512) means that bitmap is
# rendered at 8× — so the icon stays crisp at node size and when zoomed in,
# instead of the soft, upscaled look a bare viewBox gives.
def _svg(body: str) -> str:
    # A soft grounding shadow under the device (drawn first, so it sits
    # behind) makes each icon read as a physical thing resting on the canvas
    # rather than a flat sticker.
    shadow = '<ellipse cx="32" cy="57" rx="17" ry="3.2" fill="#0f172a" opacity="0.14"/>'
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
        'viewBox="0 0 64 64" '
        'fill="none" stroke-linecap="round" stroke-linejoin="round">'
        + shadow
        + body
        + "</svg>"
    )


def _router(main: str, dark: str, light: str) -> str:
    # A short cylinder (puck) seen slightly from above, with the classic
    # four bidirectional routing arrows on its top face.
    return _svg(
        f'<ellipse cx="32" cy="44" rx="23" ry="8" fill="{dark}"/>'
        f'<rect x="9" y="24" width="46" height="20" fill="{main}"/>'
        f'<ellipse cx="32" cy="24" rx="23" ry="9" fill="{light}"/>'
        f'<g stroke="{main}" stroke-width="2.6" fill="none">'
        f'<path d="M18 24h12m-3-3 3 3-3 3"/>'
        f'<path d="M46 24H34m3-3-3 3 3 3"/>'
        f'<path d="M27 20l5-4 5 4"/>'
        f'<path d="M27 28l5 4 5-4"/>'
        f"</g>"
    )


def _switch_box(main: str, dark: str, light: str, *, routed: bool) -> str:
    # A flat 3-D box with opposing traffic arrows on its face. L3 adds an
    # upward routed arrow.
    routed_arrow = (
        f'<path d="M32 33V21m-4 4 4-4 4 4" stroke="{light}" stroke-width="2.6"/>'
        if routed
        else ""
    )
    return _svg(
        f'<polygon points="12,22 52,22 58,16 18,16" fill="{light}"/>'
        f'<polygon points="52,22 58,16 58,40 52,46" fill="{dark}"/>'
        f'<rect x="12" y="22" width="40" height="24" rx="2" fill="{main}"/>'
        f'<g stroke="{_LINE}" stroke-width="2.4" fill="none">'
        f'<path d="M19 31h13m-4-4 4 4-4 4"/>'
        f'<path d="M45 39H32m4-4-4 4 4 4"/>'
        f"</g>"
        + routed_arrow
    )


def _server(main: str, dark: str, light: str) -> str:
    # A rack/tower with drive slots and status LEDs.
    return _svg(
        f'<rect x="18" y="8" width="28" height="48" rx="3" fill="{main}"/>'
        f'<rect x="18" y="8" width="6" height="48" rx="3" fill="{dark}"/>'
        f'<g stroke="{light}" stroke-width="2.2">'
        f'<path d="M28 18h14M28 30h14M28 42h14"/>'
        f"</g>"
        f'<circle cx="21" cy="16" r="1.7" fill="#4ade80"/>'
        f'<circle cx="21" cy="28" r="1.7" fill="{light}"/>'
        f'<circle cx="21" cy="40" r="1.7" fill="{light}"/>'
    )


def _host(main: str, dark: str, light: str) -> str:
    # A desktop monitor — the everyday "a machine lives here" glyph.
    return _svg(
        f'<rect x="8" y="12" width="48" height="30" rx="3" fill="{dark}"/>'
        f'<rect x="11" y="15" width="42" height="24" rx="2" fill="{main}"/>'
        f'<path d="M18 22l6 5-6 5" stroke="{light}" stroke-width="2.4" fill="none"/>'
        f'<path d="M28 33h10" stroke="{light}" stroke-width="2.4"/>'
        f'<path d="M26 42h12l2 8H24z" fill="{dark}"/>'
        f'<rect x="20" y="50" width="24" height="4" rx="2" fill="{main}"/>'
    )


def _firewall(main: str, dark: str, light: str) -> str:
    # A brick wall.
    rows = "".join(
        f'<path d="M8 {y}h48" stroke="{light}" stroke-width="2"/>' for y in (24, 33, 42)
    )
    verts = (
        f'<path d="M24 15v9M40 15v9M18 24v9M32 24v9M46 24v9'
        f'M24 33v9M40 33v9M18 42v9M32 42v9M46 42v9" '
        f'stroke="{light}" stroke-width="2"/>'
    )
    return _svg(
        f'<rect x="8" y="15" width="48" height="36" rx="2.5" fill="{main}"/>'
        + rows
        + verts
    )


def _access_point(main: str, dark: str, light: str) -> str:
    return _svg(
        f'<rect x="14" y="34" width="36" height="14" rx="7" fill="{main}"/>'
        f'<circle cx="24" cy="41" r="2.4" fill="{light}"/>'
        f'<circle cx="40" cy="41" r="2.4" fill="{dark}"/>'
        f'<g stroke="{main}" stroke-width="2.6" fill="none">'
        f'<path d="M20 26a17 17 0 0 1 24 0"/>'
        f'<path d="M14 20a25 25 0 0 1 36 0"/>'
        f"</g>"
    )


def _load_balancer(main: str, dark: str, light: str) -> str:
    return _svg(
        f'<circle cx="16" cy="32" r="9" fill="{main}"/>'
        f'<path d="M22 22l6 4-6 4" fill="none" stroke="{light}" stroke-width="2.6"/>'
        f'<g stroke="{main}" stroke-width="2.6" fill="none">'
        f'<path d="M25 32h9M34 32l8-9M34 32l8 9"/>'
        f"</g>"
        f'<circle cx="46" cy="16" r="6" fill="{dark}"/>'
        f'<circle cx="48" cy="32" r="6" fill="{main}"/>'
        f'<circle cx="46" cy="48" r="6" fill="{dark}"/>'
    )


def _cloud(main: str, dark: str, light: str) -> str:
    return _svg(
        f'<path d="M20 46a10 10 0 0 1-1.3-19.9 13 13 0 0 1 25-3.3A10 10 0 0 1 46 46z" '
        f'fill="{main}"/>'
        f'<path d="M20 46a10 10 0 0 1-1.3-19.9 13 13 0 0 1 6-6" fill="{light}" '
        f'opacity="0.4"/>'
    )


def _unknown(main: str, dark: str, light: str) -> str:
    return _svg(
        f'<path d="M32 8l21 12v24L32 56 11 44V20z" fill="{main}"/>'
        f'<path d="M32 8l21 12-21 12-21-12z" fill="{light}"/>'
        f'<path d="M27 27a5 5 0 1 1 7 4.6c-1.7.9-2.5 1.9-2.5 4" '
        f'stroke="{_LINE}" stroke-width="2.6" fill="none"/>'
        f'<circle cx="32" cy="43" r="2" fill="{_LINE}"/>'
    )


def _unresolved(main: str, dark: str, light: str) -> str:
    # A dashed, hollow disc with a question mark: observed, not identified.
    return _svg(
        f'<circle cx="32" cy="32" r="20" fill="{main}" fill-opacity="0.25" '
        f'stroke="{dark}" stroke-width="2.6" stroke-dasharray="5 4"/>'
        f'<path d="M27 27a5 5 0 1 1 7 4.6c-1.7.9-2.5 1.9-2.5 4" '
        f'stroke="{dark}" stroke-width="2.6" fill="none"/>'
        f'<circle cx="32" cy="43" r="2" fill="{dark}"/>'
    )


def _build() -> dict[str, str]:
    p = _PALETTE
    return {
        ROLE_ROUTER: _router(*p[ROLE_ROUTER]),
        ROLE_L2_SWITCH: _switch_box(*p[ROLE_L2_SWITCH], routed=False),
        ROLE_L3_SWITCH: _switch_box(*p[ROLE_L3_SWITCH], routed=True),
        ROLE_FIREWALL: _firewall(*p[ROLE_FIREWALL]),
        ROLE_SERVER: _server(*p[ROLE_SERVER]),
        ROLE_LINUX_HOST: _host(*p[ROLE_LINUX_HOST]),
        ROLE_ACCESS_POINT: _access_point(*p[ROLE_ACCESS_POINT]),
        ROLE_LOAD_BALANCER: _load_balancer(*p[ROLE_LOAD_BALANCER]),
        ROLE_CLOUD: _cloud(*p[ROLE_CLOUD]),
        ROLE_UNKNOWN: _unknown(*p[ROLE_UNKNOWN]),
        ROLE_UNRESOLVED: _unresolved(*p[ROLE_UNRESOLVED]),
    }


STENCILS: dict[str, str] = _build()

# PR-050 (SKYLINE): a SITE is a place on the network diagram, not a literal
# box. The glyph is a campus outline sheltering three linked device dots --
# the same icon-plus-nameplate language as every device stencil. Standalone
# SVG: it needs none of the per-role helpers.
STENCILS["site"] = '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="144" viewBox="0 0 640 512"><defs><linearGradient id="scg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#dbe4ff"/></linearGradient></defs><ellipse cx="320" cy="488" rx="230" ry="22" fill="#0f172a" opacity="0.08"/><path d="M0 336c0 79.5 64.5 144 144 144H512c70.7 0 128-57.3 128-128c0-61.9-44-113.6-102.4-125.4c4.1-10.7 6.4-22.4 6.4-34.6c0-53-43-96-96-96c-19.7 0-38.1 6-53.3 16.2C367 64.2 315.3 32 256 32C167.6 32 96 103.6 96 192c0 2.7 .1 5.4 .2 8.1C40.2 219.8 0 273.2 0 336z" fill="url(#scg)" stroke="#4f46e5" stroke-width="22" stroke-linejoin="round"/><circle cx="236" cy="330" r="30" fill="#4f46e5"/><circle cx="404" cy="330" r="30" fill="#4f46e5"/><circle cx="320" cy="240" r="30" fill="#818cf8"/><path d="M266 330 L374 330 M252 306 L300 262 M388 306 L340 262" stroke="#4338ca" stroke-width="12" stroke-linecap="round"/></svg>'


def stencil_svg(role: str) -> str:
    """The SVG markup for a role (unknown when the role is unmapped)."""

    return STENCILS.get(role, STENCILS[ROLE_UNKNOWN])


def stencil_data_uri(role: str) -> str:
    """The stencil as a Cytoscape-ready background-image data URI."""

    return "data:image/svg+xml;utf8," + quote(stencil_svg(role))


def role_accent(role: str) -> str:
    """The role's accent colour, for legends and chips."""

    if role == "site":
        return "#4f46e5"
    return _PALETTE.get(role, _PALETTE[ROLE_UNKNOWN])[0]
