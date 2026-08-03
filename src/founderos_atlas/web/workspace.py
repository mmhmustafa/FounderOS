"""The Atlas workspace: where you are, what is related, what is next
(PR-170).

Atlas grew page by page. Each page is correct and each knows nothing
about the others, so an operator carries the connections in their head:
*where am I, how did I get here, what else touches this device, how do I
get back?*

This module answers those four questions from data Atlas **already
has** — the navigation registry, the active scope, and the object the
page is about. It introduces no new queries and no new source of truth.

    breadcrumbs   where you are, and every step back, clickable
    context       what this page is scoped to right now
    related       the other Atlas surfaces that hold this same object
    recents       where you have just been, per user
    favourites    where you keep going back to, per user

Two rules shape all of it:

1. **Never invent a destination.** A related link is offered only when
   Atlas can name the object it points at. A dead link in a "related"
   panel is worse than an absent one — it teaches the operator that the
   panel lies.
2. **Carry the context.** A link that drops the active scope sends the
   operator somewhere they then have to re-configure, which is the
   thing this module exists to stop.

It is page-agnostic on purpose: it takes keys and ids and returns plain
data, so any page can adopt it without importing another page.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

from .models import NAV_GROUPS, NAV_GROUP_FOR_ITEM


# The workspace's own slice of the per-user preference store. The store
# refuses any key outside its allowlist, so this prefix is declared
# there too — favourites and recents are per-USER and server-side, which
# is why they survive a restart, a new tab and a different browser.
PREFERENCE_PREFIX = "workspace:"
FAVOURITES_KEY = PREFERENCE_PREFIX + "favourites"
RECENTS_KEY = PREFERENCE_PREFIX + "recents"

MAX_RECENTS = 12
MAX_FAVOURITES = 24

# Every navigable page, flattened once: key -> (group label, group href,
# item label, item href). This IS the breadcrumb source — the nav
# registry already knows the hierarchy, so a page gets its trail without
# declaring one, and a page added to the nav gets breadcrumbs for free.
_PAGES: dict[str, dict[str, str]] = {
    item.key: {
        "key": item.key,
        "label": item.label,
        "href": item.href,
        "group_key": group.key,
        "group_label": group.label,
        "group_href": group.href,
    }
    for group in NAV_GROUPS
    for item in group.items
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def page(key: str) -> dict[str, str] | None:
    return _PAGES.get(_text(key))


def pages() -> tuple[dict[str, str], ...]:
    """Every page, for the command palette."""

    return tuple(_PAGES.values())


def with_scope(href: str, scope_id: str = "") -> str:
    """``href`` carrying the active scope.

    A workspace link that drops the scope lands the operator on a page
    showing a different estate than the one they were just looking at.
    An href that already names a scope is left alone — an explicit
    choice always wins over an inherited one.
    """

    target = _text(href)
    scope = _text(scope_id)
    if not target or not scope or target.startswith(("http://", "https://")):
        return target
    parts = urlsplit(target)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "scope" in query:
        return target
    query["scope"] = scope
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query),
         parts.fragment)
    )


# -- Part 1: breadcrumbs ----------------------------------------------------

def breadcrumbs(active: str, *, trail: Iterable[Mapping[str, Any]] = (),
                scope_id: str = "") -> list[dict[str, str]]:
    """Where this page sits, and every step back to Home.

    The first two levels come from the navigation registry, so they are
    always right and never hand-maintained. ``trail`` is what only the
    page knows — the investigation, the device, the protocol — appended
    in order. A trail entry without an href renders as plain text: the
    current position is not a link to itself.
    """

    crumbs: list[dict[str, str]] = [
        {"label": "Home", "href": with_scope("/", scope_id)}
    ]
    known = page(active)
    if known:
        if known["group_key"] != "home":
            crumbs.append({
                "label": known["group_label"],
                "href": with_scope(known["group_href"], scope_id),
            })
        crumbs.append({
            "label": known["label"],
            "href": with_scope(known["href"], scope_id),
        })
    for item in trail or ():
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("label"))
        if not label:
            continue
        crumbs.append({
            "label": label,
            "href": with_scope(_text(item.get("href")), scope_id),
        })
    # The last crumb is where the operator already is; linking it invites
    # a click that changes nothing.
    if crumbs:
        crumbs[-1] = dict(crumbs[-1], href="")
    return crumbs


# -- Part 2: the context panel ----------------------------------------------

def context_items(**values: Any) -> list[dict[str, str]]:
    """The page's current context, in a fixed operator-facing order.

    Only what is actually set is returned. A context strip padded with
    "—" teaches an operator to stop reading it.
    """

    order = (
        ("investigation", "Investigation"),
        ("site", "Site"),
        ("device", "Device"),
        ("protocol", "Protocol"),
        ("interface", "Interface"),
        ("time_range", "Time range"),
        ("filters", "Filters"),
        ("confidence", "Confidence"),
        ("discovery_age", "Discovery"),
        ("scope", "Scope"),
    )
    items: list[dict[str, str]] = []
    for key, label in order:
        value = _text(values.get(key))
        if value:
            items.append({"key": key, "label": label, "value": value})
    return items


# -- Part 3: related objects ------------------------------------------------

# What each kind of Atlas object is reachable from. Every entry names a
# real route; a link is emitted only when the caller supplies the id it
# needs, so the panel can never offer a destination Atlas cannot fill.
_DEVICE_RELATIONS = (
    ("topology", "Topology", "/topology", "where this device sits"),
    ("configuration", "Configuration", "/configuration",
     "its collected configuration"),
    ("timeline", "Timeline", "/timeline", "what happened, in order"),
    ("changes", "Changes", "/changes", "what changed recently"),
    ("memory", "Evidence", "/evidence", "the artifacts it appears in"),
    ("policy", "Policy", "/policy", "the checks that judge it"),
    ("incidents", "Incidents", "/incidents", "open operational issues"),
    ("paths", "Investigate", "/paths", "walk a path through it"),
)

_SITE_RELATIONS = (
    ("topology", "Topology", "/topology", "the site's devices and links"),
    ("timeline", "Timeline", "/timeline", "what happened at this site"),
    ("incidents", "Incidents", "/incidents", "open issues here"),
    ("policy", "Policy", "/policy", "policy results for this site"),
    ("history", "Discoveries", "/history", "how it was discovered"),
)


def related(kind: str, *, scope_id: str = "", device_id: str = "",
            label: str = "") -> list[dict[str, str]]:
    """The other Atlas surfaces that hold this same object.

    ``kind`` is ``device`` or ``site``. Every href carries the active
    scope, so following one keeps the operator in the estate they were
    already looking at.
    """

    table = {"device": _DEVICE_RELATIONS, "site": _SITE_RELATIONS}.get(
        _text(kind).casefold()
    )
    if not table:
        return []
    rows: list[dict[str, str]] = []
    for key, item_label, href, why in table:
        target = href
        # The device page is the one destination that needs the id
        # itself; the rest are scoped views the operator filters.
        if key == "topology" and device_id:
            target = f"{href}?focus={device_id}"
        rows.append({
            "key": key,
            "label": item_label,
            "href": with_scope(target, scope_id),
            "why": why,
        })
    return rows


# -- Parts 4 and 5: recents and favourites ----------------------------------

def _entry(kind: str, label: str, href: str) -> dict[str, str] | None:
    kind, label, href = _text(kind), _text(label), _text(href)
    if not label or not href:
        return None
    return {"kind": kind or "page", "label": label, "href": href}


def remember(existing: Any, *, kind: str, label: str, href: str,
             limit: int = MAX_RECENTS) -> list[dict[str, str]]:
    """``existing`` with this place moved to the front.

    Deduplicated by href so revisiting somewhere reorders rather than
    repeats, and bounded so the store cannot grow without limit.
    """

    entry = _entry(kind, label, href)
    if entry is None:
        return _clean(existing, limit)
    kept = [
        item for item in _clean(existing, limit)
        if item.get("href") != entry["href"]
    ]
    return ([entry] + kept)[:limit]


def toggle_favourite(existing: Any, *, kind: str, label: str,
                     href: str) -> tuple[list[dict[str, str]], bool]:
    """Pin or unpin. Returns the new list and whether it is now pinned."""

    entry = _entry(kind, label, href)
    current = _clean(existing, MAX_FAVOURITES)
    if entry is None:
        return current, False
    kept = [item for item in current if item.get("href") != entry["href"]]
    if len(kept) != len(current):
        return kept, False                      # it was pinned: unpin
    return (kept + [entry])[:MAX_FAVOURITES], True


def is_favourite(existing: Any, href: str) -> bool:
    target = _text(href)
    return any(
        item.get("href") == target for item in _clean(existing, MAX_FAVOURITES)
    )


def _clean(existing: Any, limit: int) -> list[dict[str, str]]:
    """A stored list, defensively. The store is per-user JSON that a
    previous version may have written differently; a bad entry must
    drop out rather than break the page that renders it."""

    rows: list[dict[str, str]] = []
    for item in (existing or []) if isinstance(existing, list) else []:
        if not isinstance(item, Mapping):
            continue
        entry = _entry(item.get("kind"), item.get("label"), item.get("href"))
        if entry is not None and entry["href"] not in {
            row["href"] for row in rows
        }:
            rows.append(entry)
    return rows[:limit]


# -- Part 6: the command palette's page and command index -------------------

# Commands are VERBS the palette can offer beside pages and devices.
# Each is a real destination; none performs an action from the palette
# itself, because a command palette that mutates on Enter is a way to
# run discovery by accident.
COMMANDS = (
    ("Ask Advisor a question", "/advisor", "analyze"),
    ("Run discovery", "/discovery", "administration"),
    ("Investigate a path", "/paths", "analyze"),
    ("Review recent changes", "/changes", "operations"),
    ("Open the action center", "/inbox", "home"),
    ("Check policy results", "/policy", "operations"),
    ("Open PRISM settings", "/settings/ai", "administration"),
    ("Open the audit log", "/audit", "administration"),
)


def palette_index(scope_id: str = "") -> list[dict[str, str]]:
    """Pages and commands for the Ctrl+K palette.

    Devices, interfaces and addresses already come from the live search
    endpoint; this adds the parts of Atlas that are not entities, so
    "where is that page?" stops being a question.
    """

    rows: list[dict[str, str]] = []
    for item in pages():
        rows.append({
            "kind": "page",
            "label": item["label"],
            "detail": item["group_label"],
            "href": with_scope(item["href"], scope_id),
        })
    for label, href, group in COMMANDS:
        rows.append({
            "kind": "command",
            "label": label,
            "detail": _PAGES.get(group, {}).get("group_label", "") or "Command",
            "href": with_scope(href, scope_id),
        })
    return rows
