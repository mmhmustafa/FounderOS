# Atlas Interactive Topology Viewer

## Purpose

`TopologyRenderer` converts one immutable `TopologySnapshot` into a deterministic single HTML document. It does not discover devices, reconcile topology, mutate the Snapshot, write files, or open browsers.

The Viewer uses plain HTML, CSS, and JavaScript plus a pinned Cytoscape.js CDN reference. Python performs no network access. Opening the generated HTML requires browser access to the CDN unless Cytoscape is already cached.

## Features

- discovered and observed-neighbor nodes;
- logical, tiered, force, concentric, circle, and grid layouts;
- a folded, compact Site overview as the deliberate whole-estate default;
- an All devices mode that protects readable label scale and pans instead of
  auto-fitting a large graph into a thumbnail;
- zoom, pan, reset, site folding, and responsive details controls;
- role-specific thin-outline SVG stencils with restrained tint fills;
- thin, high-contrast relationship lines and on-demand interface labels;
- semantic zoom that hides unreadably small peer labels instead of painting
  tiny text;
- hostname/IP/vendor/platform search that focuses small result sets at a
  readable zoom;
- one explicit typography and colour-token contract shared by DOM and canvas;
- bounded 2x-2.5x canvas supersampling for crisp output without unbounded
  backing-canvas growth; and
- deterministic JSON embedding with script-termination escaping.

## Visual contract

All device and site art is produced by `visualization/stencils.py`. Every
stencil uses the same 512 x 512 intrinsic canvas, `0 0 64 64` viewBox,
geometric-precision rendering, round joins/caps, and 1.25-1.5 unit strokes.
Stencil SVGs contain no filters, shadows, raster images, or gradients. New
roles must use the shared wrapper and stroke constants so future imagery gets
the same thin, crisp treatment automatically.

The viewer template owns the text, surface, and relationship tokens. It passes
the computed font and edge colours into Cytoscape rather than maintaining a
second canvas-only palette. Node and aggregate labels have minimum painted
font sizes; device nameplates show the hostname at normal scale and add the
management address only at close zoom. Overview density is handled through
site folding, a readable zoom floor, and semantic zoom, not miniature type or
model-size-dependent font shrinking. The empty details pane starts closed and
opens on selection, leaving the graph its full width until details are useful.

## Saved-viewer compatibility

Each rendered document carries a deterministic visual-style marker derived
from the topology template and the complete stencil set. The local web GUI can
therefore detect an old current viewer and regenerate only that HTML from its
adjacent immutable snapshot. Snapshot evidence and discovery history are not
changed, and archived historical viewers are intentionally left as originally
generated.

## Boundaries

The renderer is a pure Atlas adapter. The FounderOS CLI owns the explicitly
requested output-file write and browser launch; the local web route owns the
bounded refresh of a stale current viewer. The renderer itself performs no
filesystem mutation or discovery. The local web route provides deliberate,
confirmed curation actions backed by the audited site-override repository;
historical snapshots remain immutable.

Site overview, All devices, OSPF areas, and BGP autonomous systems are separate
views. Protocol boundaries are derived only from normalized configuration or
operational evidence. Reused area/ASN values are split by observed
connectivity, multi-membership devices are marked, and unknown memberships
remain explicit. Operational state, VRF, address family, process/router IDs,
peer ASNs, and source commands survive enterprise federation as provenance.
