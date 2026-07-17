"""The Atlas device stencil set: role icons for the topology viewer.

Original, thin-outline device icons -- no vendor artwork. Each icon is drawn
to read as network gear at a glance (a router puck, a switch, a server, a
monitor), the way a network diagram does, while remaining Atlas's own art so
it is safe to ship and works offline.

Every stencil follows one rendering contract: a 64-unit viewBox, a 512-pixel
intrinsic canvas for Cytoscape's bitmap texture, geometric-precision paths,
and 1.25-1.5 unit outlines over restrained tint fills. Keeping device and site
art on the same contract makes future roles inherit the same visual quality.

Two channels carry meaning, deliberately kept separate so the set survives
grayscale and colour-blindness:

- **SHAPE** encodes the device *role* -- a router is always a disc, a switch
  always a box, whatever the colour.
- **COLOUR** here is a role accent (so the diagram is legible and pleasant);
  operational *state* -- new / changed / removed / selected -- is carried by
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


# Main = role accent/outline, dark = fine detail, light = restrained tint.
# Operational state remains outside these colours and is rendered by the
# viewer's node border ring.
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

_CANVAS_SIZE = 512
_VIEW_BOX = "0 0 64 64"
_STROKE_WIDTH = "1.5"
_DETAIL_STROKE_WIDTH = "1.25"
_SURFACE = "#ffffff"
_SITE_PALETTE = ("#4f46e5", "#3730a3", "#e0e7ff")
_WAN_PALETTE = ("#2563eb", "#1e40af", "#dbeafe")
_INTERNET_PALETTE = ("#0284c7", "#075985", "#e0f2fe")
_CLOUD_SITE_PALETTE = ("#7c3aed", "#5b21b6", "#ede9fe")


def _svg(body: str) -> str:
    """Wrap stencil geometry in the shared high-resolution SVG contract."""

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_CANVAS_SIZE}" '
        f'height="{_CANVAS_SIZE}" viewBox="{_VIEW_BOX}" fill="none" '
        'shape-rendering="geometricPrecision" stroke-linecap="round" '
        'stroke-linejoin="round">'
        + body
        + "</svg>"
    )


def _router(main: str, dark: str, light: str) -> str:
    # A shallow router puck with four directional arrows on its top face.
    return _svg(
        f'<path d="M10 27v10c0 5 9.8 9 22 9s22-4 22-9V27" '
        f'fill="{light}" fill-opacity="0.28" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<ellipse cx="32" cy="27" rx="22" ry="9" fill="{_SURFACE}" '
        f'stroke="{main}" stroke-width="{_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<path d="M18 27h11m-3-3 3 3-3 3"/>'
        '<path d="M46 27H35m3-3-3 3 3 3"/>'
        '<path d="M29 23l3-3 3 3"/>'
        '<path d="M29 31l3 3 3-3"/>'
        "</g>"
    )


def _switch_box(main: str, dark: str, light: str, *, routed: bool) -> str:
    # L2 and L3 keep the same switch chassis; L3 adds the upward route arrow.
    routed_arrow = (
        f'<path d="M32 34V23m-3 3 3-3 3 3" fill="none" '
        f'stroke="{main}" stroke-width="{_DETAIL_STROKE_WIDTH}"/>'
        if routed
        else ""
    )
    return _svg(
        f'<rect x="8" y="17" width="48" height="30" rx="4" '
        f'fill="{light}" fill-opacity="0.26" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<path d="M8 25h48" stroke="{main}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<path d="M15 34h13m-3-3 3 3-3 3"/>'
        '<path d="M49 40H36m3-3-3 3 3 3"/>'
        "</g>"
        + routed_arrow
        + f'<g fill="{main}">'
        '<circle cx="15" cy="21" r="1"/>'
        '<circle cx="20" cy="21" r="1"/>'
        '<circle cx="25" cy="21" r="1"/>'
        "</g>"
    )


def _server(main: str, dark: str, light: str) -> str:
    # A three-bay rack with fine drive lines and status indicators.
    return _svg(
        f'<rect x="18" y="6" width="28" height="52" rx="4" '
        f'fill="{light}" fill-opacity="0.24" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{main}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<path d="M18 23h28M18 40h28"/>'
        "</g>"
        f'<g fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<path d="M27 15h13M27 32h13M27 49h13"/>'
        "</g>"
        f'<g fill="{main}">'
        '<circle cx="23" cy="15" r="1.25"/>'
        '<circle cx="23" cy="32" r="1.25"/>'
        '<circle cx="23" cy="49" r="1.25"/>'
        "</g>"
    )


def _host(main: str, dark: str, light: str) -> str:
    # A desktop monitor with a small command prompt and an outlined stand.
    return _svg(
        f'<rect x="7" y="9" width="50" height="35" rx="4" '
        f'fill="{light}" fill-opacity="0.22" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<rect x="11" y="13" width="42" height="27" rx="2" '
        f'fill="{_SURFACE}" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{main}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<path d="M18 22l5 4-5 4"/>'
        '<path d="M27 31h10"/>'
        '<path d="M27 44h10l2 8H25z"/>'
        '<path d="M20 54h24"/>'
        "</g>"
    )


def _firewall(main: str, dark: str, light: str) -> str:
    # Brick geometry keeps the firewall recognisable without a heavy fill.
    return _svg(
        f'<rect x="8" y="14" width="48" height="38" rx="3" '
        f'fill="{light}" fill-opacity="0.24" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<path d="M8 24h48M8 34h48M8 44h48"/>'
        '<path d="M23 14v10M41 14v10M17 24v10M32 24v10M47 24v10M23 34v10M41 34v10M17 44v8M32 44v8M47 44v8"/>'
        "</g>"
    )


def _access_point(main: str, dark: str, light: str) -> str:
    return _svg(
        f'<rect x="14" y="36" width="36" height="14" rx="7" '
        f'fill="{light}" fill-opacity="0.28" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}">'
        '<path d="M21 29a16 16 0 0 1 22 0"/>'
        '<path d="M15 22a24 24 0 0 1 34 0"/>'
        "</g>"
        f'<circle cx="25" cy="43" r="1.5" fill="{main}"/>'
        f'<circle cx="39" cy="43" r="1.5" fill="{dark}"/>'
    )


def _load_balancer(main: str, dark: str, light: str) -> str:
    return _svg(
        f'<circle cx="15" cy="32" r="9" fill="{light}" '
        f'fill-opacity="0.28" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<path d="M24 32h10M34 32l8-14M34 32h8M34 32l8 14"/>'
        '<path d="M11 32h8m-3-3 3 3-3 3"/>'
        "</g>"
        f'<g fill="{_SURFACE}" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}">'
        '<circle cx="46" cy="16" r="6"/>'
        '<circle cx="48" cy="32" r="6"/>'
        '<circle cx="46" cy="48" r="6"/>'
        "</g>"
    )


def _cloud(main: str, dark: str, light: str) -> str:
    del dark  # the cloud silhouette needs only its role outline and pale tint
    return _svg(
        f'<path d="M18 48a11 11 0 0 1-1.6-21.9A15 15 0 0 1 45 22.5 11 11 0 0 1 47 48z" '
        f'fill="{light}" fill-opacity="0.32" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
    )


def _unknown(main: str, dark: str, light: str) -> str:
    return _svg(
        f'<path d="M32 7l21 12v26L32 57 11 45V19z" '
        f'fill="{light}" fill-opacity="0.22" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<path d="M11 19l21 12 21-12M32 31v26" fill="none" '
        f'stroke="{main}" stroke-width="{_DETAIL_STROKE_WIDTH}"/>'
        f'<path d="M27.5 28a5 5 0 1 1 7 4.6c-1.7.9-2.5 1.9-2.5 4" '
        f'fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}"/>'
        f'<circle cx="32" cy="43" r="1.4" fill="{dark}"/>'
    )


def _unresolved(main: str, dark: str, light: str) -> str:
    # A dashed, hollow disc: observed in evidence, not yet identified.
    return _svg(
        f'<circle cx="32" cy="32" r="21" fill="{light}" '
        f'fill-opacity="0.22" stroke="{dark}" '
        f'stroke-width="{_STROKE_WIDTH}" stroke-dasharray="4 4"/>'
        f'<path d="M27 27a5 5 0 1 1 7 4.6c-1.7.9-2.5 1.9-2.5 4" '
        f'fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}"/>'
        f'<circle cx="32" cy="43" r="1.4" fill="{main}"/>'
    )


def _site() -> str:
    """A normal site cloud; the viewer paints its name inside the shape."""

    main, _dark, light = _SITE_PALETTE
    return _svg(
        f'<path d="M13 48a11 11 0 0 1-1.2-21.9A16 16 0 0 1 42.5 22 '
        f'A12 12 0 0 1 49 45.2 12 12 0 0 1 46 48z" '
        f'fill="{light}" fill-opacity="0.26" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
    )


def _wan_site() -> str:
    """Explicit private WAN cloud -- never used for unknowns."""

    main, _dark, light = _WAN_PALETTE
    return _svg(
        f'<path d="M9 48a11 11 0 0 1 1.5-21.8A17 17 0 0 1 43 21.5 '
        f'A12 12 0 0 1 50 45.2 12 12 0 0 1 47 48z" '
        f'fill="{light}" fill-opacity="0.30" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
    )


def _internet_site() -> str:
    """Explicit Internet boundary."""

    main, dark, light = _INTERNET_PALETTE
    return _svg(
        f'<circle cx="32" cy="32" r="28" fill="{_SURFACE}" '
        f'stroke="{main}" stroke-width="{_STROKE_WIDTH}"/>'
        f'<circle cx="32" cy="32" r="18" fill="{light}" '
        f'fill-opacity="0.32" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
        f'<g fill="none" stroke="{dark}" '
        f'stroke-width="{_DETAIL_STROKE_WIDTH}">'
        '<ellipse cx="32" cy="32" rx="8" ry="18"/>'
        '<path d="M15 26h34M15 38h34"/>'
        '</g>'
    )


def _cloud_site() -> str:
    main, _dark, light = _CLOUD_SITE_PALETTE
    return _svg(
        f'<path d="M13 48a11 11 0 0 1-1.2-21.9A16 16 0 0 1 42.5 22 '
        f'A12 12 0 0 1 49 45.2 12 12 0 0 1 46 48z" '
        f'fill="{light}" fill-opacity="0.34" stroke="{main}" '
        f'stroke-width="{_STROKE_WIDTH}"/>'
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
        "site": _site(),
        "site-wan": _wan_site(),
        "site-internet": _internet_site(),
        "site-cloud": _cloud_site(),
        # Premises refinements share the premises glyph; transit shares the
        # WAN glyph; an explicitly unclassified or custom site renders with
        # the same quality as a regular site — never as a lesser shape.
        "site-branch": _site(),
        "site-campus": _site(),
        "site-datacenter": _site(),
        "site-transit": _wan_site(),
        "site-unclassified": _site(),
        "site-custom": _site(),
    }


STENCILS: dict[str, str] = _build()


def stencil_svg(role: str) -> str:
    """The SVG markup for a role (unknown when the role is unmapped)."""

    return STENCILS.get(role, STENCILS[ROLE_UNKNOWN])


def stencil_data_uri(role: str) -> str:
    """The stencil as a Cytoscape-ready background-image data URI."""

    return "data:image/svg+xml;utf8," + quote(stencil_svg(role))


def role_accent(role: str) -> str:
    """The role's accent colour, for legends and chips."""

    if role in ("site", "site-branch", "site-campus", "site-datacenter",
                "site-unclassified", "site-custom"):
        return _SITE_PALETTE[0]
    if role in ("site-wan", "site-transit"):
        return _WAN_PALETTE[0]
    if role == "site-internet":
        return _INTERNET_PALETTE[0]
    if role == "site-cloud":
        return _CLOUD_SITE_PALETTE[0]
    return _PALETTE.get(role, _PALETTE[ROLE_UNKNOWN])[0]
