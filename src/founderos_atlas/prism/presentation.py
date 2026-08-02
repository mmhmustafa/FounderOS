"""Operator presentation of a semantically redacted explanation
(PR-166.2, Parts 5.1 and 5.2).

Two audiences read the same explanation, and they must not be served
the same thing:

* **The AI provider** receives alias text only. It never learns a
  hostname, and nothing here can change that — the payload was built
  and sent before this module runs.
* **The authenticated Atlas operator** reads the explanation in Atlas,
  where the alias is annotated and linked back to the real object:

      the Mumbai Core Router (hostname protected during AI processing)

  clickable through to the device page.

These are deliberately not identical. The provider is an outsider; the
operator is someone Atlas has already authenticated and authorised.

The permission decision is NOT made here. The caller passes
``can_view`` and ``can_reveal``, computed from the authenticated user's
existing permissions, and this module only honours them. A link is
emitted only when the user could have reached that page by navigating,
and an original name is disclosed only when the user could have read it
on that page — so this feature can never become a way to see something
the RBAC would otherwise refuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from . import semantic


PROTECTION_NOTES = {
    semantic.ALIAS: "name protected during AI processing",
    semantic.MASK: "value masked during AI processing",
    semantic.REMOVE: "value removed before AI processing",
}

KIND_NOTES = {
    "device": "hostname protected during AI processing",
    "site": "site name protected during AI processing",
    "address": "address masked during AI processing",
}


@dataclass
class PresentedSegment:
    """One run of explanation text, optionally standing for an alias."""

    text: str
    alias: Any = None
    href: str = ""
    note: str = ""
    original: str = ""
    protection: dict[str, Any] = field(default_factory=dict)

    @property
    def is_alias(self) -> bool:
        return self.alias is not None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": self.text}
        if self.is_alias:
            payload.update({
                "alias": True, "href": self.href, "note": self.note,
                "protection": self.protection,
            })
            if self.original:
                payload["original"] = self.original
        return payload


def visibility_for(principal) -> tuple[bool, bool]:
    """``(can_view, can_reveal)`` for one authenticated principal.

    Both flags name permissions the user must already hold to read the
    same value on the page it came from, so this can never disclose
    more than Atlas would anyway:

    * ``can_view`` — ``pages.view``, exactly what the device page
      requires. Without it the alias renders unlinked.
    * ``can_reveal`` — ``evidence.view``. The original identifier is
      part of the underlying evidence, so reading it back needs the
      evidence permission.

    A principal Atlas cannot identify gets neither.
    """

    from founderos_atlas.access.models import EVIDENCE_VIEW, PAGES_VIEW

    if principal is None:
        return False, False
    return bool(principal.can(PAGES_VIEW)), bool(principal.can(EVIDENCE_VIEW))


def _linkable(entries: tuple) -> list:
    """The entries that may be presented as a named Atlas object.

    Two exclusions, both about not attributing a name to the wrong
    thing:

    * **Removed** values are deliberately not correlatable — every one
      of them is the same token — so presenting one as "this device"
      would attach a real hostname to whichever entry happened to match
      first. A removed value has no identity to link to.
    * An alias string claimed by **more than one** original is
      ambiguous for the same reason, and is dropped rather than
      guessed at.
    """

    candidates = [
        entry for entry in entries
        if getattr(entry, "action", "") not in
        (semantic.PRESERVE, semantic.REMOVE)
        and getattr(entry, "alias", "")
    ]
    owners: dict[str, set[str]] = {}
    for entry in candidates:
        owners.setdefault(entry.alias, set()).add(entry.original)
    return [entry for entry in candidates if len(owners[entry.alias]) == 1]


def _entries(aliases) -> tuple:
    """Alias entries from either an AliasBook or a plain sequence.

    Callers normally pass the aliases that were ACTUALLY USED in the
    outgoing text, not the whole book: an alias the provider never
    received cannot appear in its answer, so matching against the whole
    estate would only create opportunities to mislabel.
    """

    if aliases is None:
        return ()
    if hasattr(aliases, "entries"):
        return tuple(aliases.entries())
    return tuple(aliases)


def protection_record(alias, *, active_profile: semantic.PrivacyProfile,
                      provider: str = "", model: str = "",
                      retained: bool = True) -> dict[str, Any]:
    """The answer to "Why was this protected?" (Part 5.2).

    States the active profile, the rule that fired, what kind of object
    it was, that Atlas still holds the original, and whether the
    provider ever received it. It never contains the original value —
    the caller adds that separately, and only for a user permitted to
    see it.
    """

    action = getattr(alias, "action", semantic.ALIAS)
    field_name = getattr(alias, "field", "")
    kind = getattr(alias, "kind", "value")
    basis = list(getattr(alias, "basis", ()) or ())

    if action == semantic.ALIAS:
        sent = (
            "The provider received the alias only — never the original "
            "value."
        )
    elif action == semantic.MASK:
        sent = (
            "The provider received a placeholder only — never the "
            "original value."
        )
    elif action == semantic.REMOVE:
        sent = "The value was removed; the provider received nothing in its place."
    else:
        sent = "The provider received this value unchanged."

    return {
        "profile": active_profile.label,
        "profile_key": active_profile.key,
        "rule": (
            f"{semantic.FIELD_LABELS.get(field_name, field_name)} → "
            f"{semantic.ACTION_LABELS.get(action, action)}"
        ),
        "object_type": kind,
        "action": action,
        "basis": basis,
        "basis_note": (
            "Built from: " + ", ".join(basis) if basis else
            "Atlas held no descriptive metadata for this object, so a "
            "generic alias was used rather than inventing one."
        ),
        "retained": bool(retained),
        "retained_note": (
            "Atlas still holds the original evidence, unchanged. "
            "Redaction applies to the copy sent for explanation, never "
            "to the record."
        ),
        "sent_note": sent,
        "provider": provider,
        "model": model,
    }


def present(text: str, *, aliases, active_profile: semantic.PrivacyProfile,
            can_view: bool = False, can_reveal: bool = False,
            provider: str = "", model: str = "") -> list[PresentedSegment]:
    """Turn provider text into operator-facing segments.

    Only aliases that Atlas minted are recognised. Text that merely
    resembles an alias is left alone: matching is against the alias
    book, so a model that invents "the Chennai Core Router" when Atlas
    never issued that alias produces no link and no claim of identity.
    """

    body = str(text or "")
    if aliases is None:
        return [PresentedSegment(body)] if body else []

    entries = _linkable(_entries(aliases))
    if not entries:
        return [PresentedSegment(body)] if body else []

    # Longest alias first, so "Mumbai Core Router 2" is not matched as
    # "Mumbai Core Router" followed by a stray digit.
    entries.sort(key=lambda item: len(item.alias), reverse=True)

    segments: list[PresentedSegment] = []
    _walk(body, entries, segments, active_profile=active_profile,
          can_view=can_view, can_reveal=can_reveal, provider=provider,
          model=model)
    return [item for item in segments if item.text]


def _walk(body: str, entries: list, segments: list[PresentedSegment], *,
          active_profile, can_view, can_reveal, provider, model) -> None:
    """Split ``body`` on the first alias that occurs in it, recursing
    on either side so every occurrence is found once."""

    best_index = -1
    best_entry = None
    for entry in entries:
        index = body.find(entry.alias)
        if index < 0:
            continue
        if best_index < 0 or index < best_index or (
            index == best_index
            and len(entry.alias) > len(getattr(best_entry, "alias", ""))
        ):
            best_index, best_entry = index, entry

    if best_entry is None:
        segments.append(PresentedSegment(body))
        return

    head = body[:best_index]
    tail = body[best_index + len(best_entry.alias):]
    if head:
        _walk(head, entries, segments, active_profile=active_profile,
              can_view=can_view, can_reveal=can_reveal, provider=provider,
              model=model)

    note = KIND_NOTES.get(
        best_entry.kind,
        PROTECTION_NOTES.get(best_entry.action, "protected during AI processing"),
    )
    segments.append(PresentedSegment(
        text=best_entry.alias,
        alias=best_entry,
        # A link only where the operator could already navigate.
        href=best_entry.href if (can_view and best_entry.href) else "",
        note=note,
        # The real name only where the operator is already permitted
        # to read it.
        original=best_entry.original if can_reveal else "",
        protection=protection_record(
            best_entry, active_profile=active_profile, provider=provider,
            model=model,
        ),
    ))

    if tail:
        _walk(tail, entries, segments, active_profile=active_profile,
              can_view=can_view, can_reveal=can_reveal, provider=provider,
              model=model)


def alias_legend(aliases, *, can_reveal: bool = False) -> list[dict[str, Any]]:
    """A table of the aliases used, for the transparency panel.

    Original names appear only when the caller says the user may see
    them; otherwise the legend shows the alias and its basis alone.
    """

    rows: list[dict[str, Any]] = []
    for entry in _entries(aliases):
        if entry.action == semantic.PRESERVE:
            continue
        rows.append(entry.to_dict(include_original=bool(can_reveal)))
    return rows


def describe_disclosure(active_profile: semantic.PrivacyProfile,
                        counts: dict[str, int]) -> str:
    """One sentence for the operator, above the explanation (Part 5)."""

    aliased = counts.get(semantic.ALIAS, 0)
    masked = counts.get(semantic.MASK, 0)
    removed = counts.get(semantic.REMOVE, 0)
    parts: list[str] = []
    if aliased:
        parts.append(f"{aliased} name(s) replaced by a descriptive alias")
    if masked:
        parts.append(f"{masked} value(s) masked")
    if removed:
        parts.append(f"{removed} value(s) removed")
    detail = "; ".join(parts) if parts else "nothing required protection"
    return (
        f"Privacy profile “{active_profile.label}”: {detail}. Aliases "
        "exist only for AI processing — Atlas holds the original "
        "evidence unchanged."
    )
