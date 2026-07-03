# Atlas Interactive Topology Viewer

## Purpose

`TopologyRenderer` converts one immutable `TopologySnapshot` into a deterministic single HTML document. It does not discover devices, reconcile topology, mutate the Snapshot, write files, or open browsers.

The Viewer uses plain HTML, CSS, and JavaScript plus a pinned Cytoscape.js CDN reference. Python performs no network access. Opening the generated HTML requires browser access to the CDN unless Cytoscape is already cached.

## Features

- discovered and observed-neighbor nodes;
- directed edges and automatic COSE layout;
- zoom, pan, and fit controls;
- vendor-based node colors;
- hover labels and click details;
- hostname/IP/vendor/platform search; and
- deterministic JSON embedding with script-termination escaping.

## Boundaries

The renderer is a pure Atlas adapter. The FounderOS CLI owns the explicitly requested output-file write and browser launch. There is no GUI framework, React, Electron, persistence, database, authentication, editing, real-time update, SSH, SNMP, or AI behavior.
