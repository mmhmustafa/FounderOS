"""The Atlas device stencil set: role icons for the topology viewer.

Original geometric SVG glyphs — no vendor artwork. The ICON encodes the
device role; COLOR and BORDER encode operational state (never shape
alone), so the set stays readable in grayscale. Each stencil is a
self-contained SVG rendered as a Cytoscape node background image.
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


_STROKE = "#334155"
_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" '
    f'fill="none" stroke="{_STROKE}" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round">'
)


def _svg(body: str, *, dashed: bool = False) -> str:
    head = _HEAD
    if dashed:
        head = head.replace('stroke-width="2.4"', 'stroke-width="2.4" stroke-dasharray="4 3"')
    return head + body + "</svg>"


# Role glyphs. Router: circle with four arrows. Switch: rectangle with
# opposing traffic arrows (L3 adds a routed corner arrow). Firewall:
# brick wall. AP: radiating arcs. Server: rack slots. Linux host:
# terminal prompt. Load balancer: one-to-many fanout. Cloud: cloud
# outline. Unknown: hexagon with a question mark. Unresolved peer:
# dashed circle with a question mark.
STENCILS: dict[str, str] = {
    ROLE_ROUTER: _svg(
        '<circle cx="24" cy="24" r="17"/>'
        '<path d="M15 20h11m0 0-4-4m4 4-4 4"/>'
        '<path d="M33 28H22m0 0 4-4m-4 4 4 4"/>'
    ),
    ROLE_L2_SWITCH: _svg(
        '<rect x="7" y="15" width="34" height="18" rx="3"/>'
        '<path d="M13 21h12m0 0-3.5-3.5M25 21l-3.5 3.5"/>'
        '<path d="M35 27H23m0 0 3.5-3.5M23 27l3.5 3.5"/>'
    ),
    ROLE_L3_SWITCH: _svg(
        '<rect x="7" y="17" width="34" height="16" rx="3"/>'
        '<path d="M13 23h11m0 0-3-3m3 3-3 3"/>'
        '<path d="M35 29H24m0 0 3-3m-3 3 3 3"/>'
        '<path d="M24 17V9m0 0-4 4m4-4 4 4"/>'
    ),
    ROLE_FIREWALL: _svg(
        '<rect x="8" y="13" width="32" height="22" rx="2"/>'
        '<path d="M8 20.3h32M8 27.6h32"/>'
        '<path d="M18 13v7.3M30 13v7.3M12 20.3v7.3M24 20.3v7.3M36 20.3v7.3M18 27.6V35M30 27.6V35"/>'
    ),
    ROLE_ACCESS_POINT: _svg(
        '<circle cx="24" cy="30" r="3.2" fill="#334155"/>'
        '<path d="M15 22a12.8 12.8 0 0 1 18 0"/>'
        '<path d="M10.5 16.5a19 19 0 0 1 27 0"/>'
    ),
    ROLE_SERVER: _svg(
        '<rect x="11" y="9" width="26" height="30" rx="2.5"/>'
        '<path d="M11 19h26M11 29h26"/>'
        '<circle cx="16.5" cy="14" r="1.4" fill="#334155"/>'
        '<circle cx="16.5" cy="24" r="1.4" fill="#334155"/>'
        '<circle cx="16.5" cy="34" r="1.4" fill="#334155"/>'
    ),
    ROLE_LINUX_HOST: _svg(
        '<rect x="8" y="11" width="32" height="22" rx="2.5"/>'
        '<path d="M14 18l5 4-5 4M22 27h8"/>'
        '<path d="M18 39h12M24 33v6"/>'
    ),
    ROLE_LOAD_BALANCER: _svg(
        '<circle cx="13" cy="24" r="4.5"/>'
        '<path d="M17.5 24h6M23.5 24l9-9m-9 9 9 0m-9 0 9 9"/>'
        '<circle cx="36.5" cy="12.5" r="3.4"/>'
        '<circle cx="36.5" cy="24" r="3.4"/>'
        '<circle cx="36.5" cy="35.5" r="3.4"/>'
    ),
    ROLE_CLOUD: _svg(
        '<path d="M14.5 33a7 7 0 0 1-.9-13.9 9.5 9.5 0 0 1 18.5-2.4A7.5 7.5 0 0 1 33.5 33z"/>'
    ),
    ROLE_UNKNOWN: _svg(
        '<path d="M24 6l15 9v18l-15 9-15-9V15z"/>'
        '<path d="M20.5 19.5a3.8 3.8 0 1 1 5.4 3.6c-1.3.7-1.9 1.4-1.9 3"/>'
        '<circle cx="24" cy="31" r="1.5" fill="#334155"/>'
    ),
    ROLE_UNRESOLVED: _svg(
        '<circle cx="24" cy="24" r="16"/>'
        '<path d="M20.8 19.5a3.6 3.6 0 1 1 5.1 3.4c-1.2.6-1.9 1.3-1.9 2.8"/>'
        '<circle cx="24" cy="30.5" r="1.5" fill="#334155"/>',
        dashed=True,
    ),
}


def stencil_svg(role: str) -> str:
    """The SVG markup for a role (unknown when the role is unmapped)."""

    return STENCILS.get(role, STENCILS[ROLE_UNKNOWN])


def stencil_data_uri(role: str) -> str:
    """The stencil as a Cytoscape-ready background-image data URI."""

    return "data:image/svg+xml;utf8," + quote(stencil_svg(role))
