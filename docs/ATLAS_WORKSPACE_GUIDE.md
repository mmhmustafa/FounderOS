# The Atlas Workspace Guide

**How Atlas connects its pages.** Companion to the
[Atlas Experience Guide](ATLAS_EXPERIENCE_GUIDE.md), which governs what a *page* says; this one
governs how an operator *moves between* them.

---

## 1. The premise

Atlas grew page by page. Each page is correct, and each knows nothing about the others — so the
operator carries the connections in their head:

> *Where am I? How did I get here? What else touches this device? How do I get back?*

A workspace answers those four questions so the operator does not have to. Navigation succeeds when
it **disappears** — when nobody has to think about it to use Atlas.

**Task-oriented, not page-oriented.** Menus are a fallback, not the design.

---

## 2. The four answers

| Question | Answer | Where |
|---|---|---|
| Where am I? | breadcrumbs | above every page |
| What is this scoped to? | the context strip | below the breadcrumbs |
| What else touches this? | related objects | after the content |
| Where have I been / where do I keep going? | recent + pinned | after the content |

Everything is built from data Atlas **already has**: the navigation registry, the active scope, and
the object the page is about. The workspace introduces **no new source of truth** and no new query.

---

## 3. Breadcrumbs

The first two levels are derived from the navigation registry (`NAV_GROUPS`), so a page added to the
nav gets its trail **for free** and no trail is ever hand-maintained out of date:

```
Home  /  Analyze  /  Advisor  /  Investigation  /  BGP
└── from the registry ──────┘  └── from the page ───┘
```

Rules:

- The **last crumb is the current page** and is not a link — clicking it would change nothing.
- A page appends what only it knows (`trail=[{label, href}]`). A trail entry without an `href`
  renders as text.
- Every crumb **carries the active scope** (§5).
- A page that authors a richer trail itself (device, configuration, compass plan) overrides the
  `workspace_bar` block so it never grows two breadcrumb bars. All of them render the **same**
  `_breadcrumbs.html` macro — one implementation, two ways to feed it.

---

## 4. The context strip

What this page is scoped to *right now*, in a fixed order: investigation, site, device, protocol,
interface, time range, filters, confidence, discovery age, scope.

**Only what is actually set is shown.** A strip padded with `—` teaches an operator to stop reading
it, and a strip that reads differently on every page teaches them the same thing.

---

## 5. Smart navigation: carry the context

> A link that drops the active scope lands the operator on a page showing a different estate than the
> one they were just looking at.

`with_scope()` adds the active scope to every workspace link. Two rules:

- **An explicit scope always wins.** An href that already names one was a deliberate choice.
- Other query parameters and fragments survive; external links are never rewritten.

This is why breadcrumbs, related links and palette results all keep the operator where they were.

---

## 6. Related objects

Every object kind declares the other Atlas surfaces that hold it — a device relates to Topology,
Configuration, Timeline, Changes, Evidence, Policy, Incidents and Investigate.

- **Never offer a destination Atlas cannot fill.** A dead link in a "related" panel teaches the
  operator that the panel lies; an absent one costs them one search.
- **Every link explains itself** in a few words (*"what changed recently"*), because a list of page
  names is a menu, and menus are what this replaces.
- Related surfaces render **after** the content — they are ways onward, not part of the answer.

---

## 7. Recent and pinned

Both live in the **per-user preference store** (`workspace:` namespace), not `localStorage`:

- they follow the operator to another browser and survive a restart;
- the store is already per-user, size-bounded, prefix-allowlisted and atomically written;
- recording one is **best-effort** — failing to write a convenience list must never fail the page the
  operator actually asked for.

Rules: recents deduplicate by href (revisiting reorders, it never repeats) and are bounded. Only
in-app paths can be pinned — an absolute or protocol-relative href would turn a convenience list
into a redirect surface.

---

## 8. The command palette

Ctrl+K already searched **entities**. The workspace adds **pages and commands** as one more group in
the *same* response — so ranking, keyboard handling, "show all" and recent searches are inherited
rather than reimplemented, and there is one overlay, not two.

- **RBAC by construction**: the page index is built from the nav groups this principal can see, so
  the palette can never offer a page the sidebar hides.
- **Every row is a destination.** The palette performs no action, because a palette that mutates on
  Enter is a way to run discovery by accident.
- A query shorter than two characters returns no pages — otherwise typing one letter buries the
  device you were looking for under the whole sitemap.

---

## 9. Deep links and multiple windows

A URL is the workspace's save format. Anything an operator can reach, they should be able to send.

- Scope rides in `?scope=`; the topology focus in `?focus=`; the Advisor's stored answer in
  `?conversation=`.
- A scope that no longer exists is answered **explicitly** — the page falls back to the enterprise
  view and says so, rather than silently showing a different estate than the link promised.
- Opening any workspace link in a new tab yields a fully-formed page: state travels in the URL and in
  the per-user store, never in memory.

---

## 10. Extending the workspace

To adopt this on a page:

1. Pass a `trail` if the page is about a specific object.
2. Pass `workspace_context` for what the page is scoped to.
3. Pass `workspace_related` for the surfaces that hold the same object.
4. Call `_remember_place()` when the page is about an object worth returning to.
5. Do not build a second breadcrumb, palette or store — import `web/workspace.py`.

To add a new object kind, add its relation table in `web/workspace.py` beside `_DEVICE_RELATIONS`.
Every entry must name a route that exists.

---

## 11. What this does not do yet

Named honestly, because a guide that implies more than ships is worse than one that admits its edges:

- **No drag-and-drop ordering of pins.** They are ordered by when they were pinned.
- **No scroll-position restoration.**
- **No separate OS-level workspaces.** "Open in a new workspace" is a deep link in a new tab — which
  restores state, but is not an independent window with its own history.
- **Context and related panels are wired on the device page and Advisor**, not yet on every page. The
  mechanism is page-agnostic; adoption is per page.
- **Recents record devices and pinned pages**, not every visited page — recording a write on every
  navigation would put a per-user file write in the path of every request.

## Reference implementation

`src/founderos_atlas/web/workspace.py` — breadcrumbs, scope carrying, relations, recents, palette
`src/founderos_atlas/web/templates/base.html` — the workspace bar, context strip and rail
`src/founderos_atlas/web/templates/_breadcrumbs.html` — the shared crumb macro
`tests/test_workspace_experience.py` — the behaviour, pinned
