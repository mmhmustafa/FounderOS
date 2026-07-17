"""Rendering-boundary time formatting.

Atlas **stores** every instant as timezone-aware UTC. That is deliberate and
does not change: UTC is deterministic, sortable, unambiguous across sites,
and immune to DST. Engines reason in UTC and only in UTC.

This module exists for the one place that is not an engine: the screen a
human reads. A local operator on 127.0.0.1 whose clock says 14:30 should not
have to mentally subtract 5:30 from ``2026-07-14T09:00:02+00:00`` to learn
that a discovery ran two minutes ago.

Rules:

- Default to the operator's own system clock (``auto``) — the loopback GUI is
  read by the person sitting at the machine.
- Allow an explicit override, because network engineers legitimately work in
  UTC to correlate against device syslog, which is usually UTC.
- **Always** name the zone. A bare ``09:00`` is the bug.
- An unknown zone degrades to system local rather than guessing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

try:  # pragma: no cover - availability differs by platform
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass


AUTO = "auto"

_DISPLAY_FORMAT = "%d-%b-%Y %H:%M"


def resolve_timezone(setting: str | None) -> tzinfo | None:
    """The timezone to render in. ``None`` means the local system zone.

    ``None`` is a real answer, not a failure: ``datetime.astimezone(None)``
    converts to the system zone, which is what ``auto`` means.

    An unrecognised zone name resolves to system local. Atlas never guesses
    at a zone it cannot verify, and never fails a page render over a display
    preference.
    """

    value = (setting or AUTO).strip()
    if not value or value.casefold() == AUTO:
        return None
    if value.casefold() == "utc":
        return timezone.utc
    if ZoneInfo is None:  # pragma: no cover - no tzdata available
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def parse_instant(value: str | datetime | None) -> datetime | None:
    """Parse a stored timestamp into an aware datetime, or ``None``.

    A stored timestamp without an offset is read as UTC — that is what every
    Atlas writer produces, and inventing a different zone for it would be a
    guess.
    """

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _abbreviate(name: str) -> str:
    """``India Standard Time`` -> ``IST``.

    Windows reports zone long names where POSIX reports abbreviations. The
    long form is correct but unreadable in a table cell, and every such name
    is a title-cased phrase whose initials are the standard abbreviation
    (Pacific Standard Time -> PST). UTC is spelled out by Windows as
    "Coordinated Universal Time", whose initials would be wrong, so it is
    named explicitly.
    """

    words = name.split()
    if len(words) < 2:
        return name
    if name.casefold().startswith("coordinated universal"):
        return "UTC"
    if not all(word[:1].isupper() for word in words):
        return name
    return "".join(word[0] for word in words).upper()


def timezone_label(tz: tzinfo | None, *, at: datetime | None = None) -> str:
    """The short name of ``tz`` at a given instant (DST-correct).

    Never returns empty: an unnamed zone falls back to its numeric offset,
    because an unlabelled time is the ambiguity this module exists to remove.
    """

    moment = at or datetime.now(timezone.utc)
    local = moment.astimezone(tz)
    name = local.strftime("%Z")
    if not name or name.startswith(("+", "-")) or name[:1].isdigit():
        # Some platforms report an offset (or nothing) instead of a name.
        offset = local.utcoffset() or timedelta(0)
        total = int(offset.total_seconds())
        sign = "+" if total >= 0 else "-"
        hours, minutes = divmod(abs(total) // 60, 60)
        return f"UTC{sign}{hours:02d}:{minutes:02d}"
    return _abbreviate(name)


def format_timestamp(
    value: str | datetime | None,
    *,
    tz: tzinfo | None = None,
    with_zone: bool = True,
) -> str:
    """Render a stored instant for a human, in ``tz``, named.

    Unparseable input is returned unchanged rather than dropped — showing the
    operator the raw value beats showing them nothing.
    """

    if value is None or value == "":
        return "never"
    moment = parse_instant(value)
    if moment is None:
        return str(value)
    local = moment.astimezone(tz)
    rendered = local.strftime(_DISPLAY_FORMAT)
    if with_zone:
        return f"{rendered} {timezone_label(tz, at=moment)}"
    return rendered


def format_relative(
    value: str | datetime | None, *, now: datetime | None = None
) -> str:
    """A coarse "how long ago", or "" when it cannot be determined.

    Deterministic given ``now``; the caller supplies the clock.
    """

    moment = parse_instant(value)
    if moment is None:
        return ""
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    seconds = int((reference - moment).total_seconds())
    if seconds < 0:
        return "in the future"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def format_with_relative(
    value: str | datetime | None,
    *,
    tz: tzinfo | None = None,
    now: datetime | None = None,
) -> str:
    """``14:30 IST (2 minutes ago)`` — absolute truth, human context."""

    absolute = format_timestamp(value, tz=tz)
    if absolute in ("never",):
        return absolute
    relative = format_relative(value, now=now)
    return f"{absolute} ({relative})" if relative else absolute


def display_date(value: str | datetime | None, tz: tzinfo | None = None) -> str:
    """The calendar date ``value`` falls on **in ``tz``**.

    This is why day-grouping cannot slice the ISO string: 02:00 on the 15th
    in UTC+05:30 is 20:30 on the *14th* in UTC, and an operator grouping
    their own changes by day means their own days.
    """

    moment = parse_instant(value)
    if moment is None:
        return "unknown"
    return moment.astimezone(tz).strftime("%Y-%m-%d")


def day_key_for(tz: tzinfo | None):
    """A ``day_of`` callable for :func:`config_memory.group_by_day`."""

    def _key(value: str) -> str:
        return display_date(value, tz)

    return _key
