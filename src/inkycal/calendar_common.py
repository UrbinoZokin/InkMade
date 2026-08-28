from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from .models import Event


def normalize_all_day_bounds(
    start: datetime,
    end: Optional[datetime],
    tz: ZoneInfo,
) -> Tuple[datetime, datetime]:
    """Snap an all-day event onto whole local days.

    All-day events are date-granular, but feeds express them in a mix of ways:
    a plain date, a midnight timestamp in some other zone, an inclusive end
    date, or no end at all. Normalizing every one of them to
    ``[local midnight, exclusive local midnight)`` is what keeps a one-day
    event on exactly one day everywhere downstream (range filtering, the
    weekly view's day expansion, the daily view's all-day merge).
    """
    start_local = start.astimezone(tz)
    day_start = start_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if end is None:
        return day_start, day_start + timedelta(days=1)

    # Anchor on the start day and carry the event's own length across, rather
    # than rounding each end outward: outward rounding is itself a way to turn
    # a one-day event into a two-day one. Rounding the elapsed time to whole
    # days also absorbs the 23h/25h days a DST change produces.
    elapsed = end.astimezone(tz) - start_local
    days = max(1, round(elapsed / timedelta(days=1)))
    return day_start, day_start + timedelta(days=days)


def event_overlaps_range(
    event: Event,
    range_start: datetime,
    range_end: datetime,
    tz: ZoneInfo,
) -> bool:
    """Does `event` fall inside the half-open window [range_start, range_end)?

    All-day events are compared by local date rather than by timestamp. Both
    backends hand back all-day events that only *touch* the requested window:
    CalDAV time-ranges are sent in UTC (RFC 4791 §9.9) while a date-valued
    DTSTART/DTEND is floating, so an all-day event leaks into the neighbouring
    day's query for any zone offset from UTC; Google resolves all-day events in
    the calendar's own zone, which drifts the same way when that differs from
    ours. Comparing dates here keeps such an event on its own day only.
    """
    if range_end <= range_start:
        return False

    if event.all_day:
        first_day = range_start.astimezone(tz).date()
        last_day = (range_end.astimezone(tz) - timedelta(microseconds=1)).date()
        start_day = event.start.astimezone(tz).date()
        end_day = event.end.astimezone(tz).date()  # exclusive
        if end_day <= start_day:
            end_day = start_day + timedelta(days=1)
        return start_day <= last_day and end_day > first_day

    if event.end <= event.start:
        # Zero-length (point-in-time) event: it counts if it starts in range.
        return range_start <= event.start < range_end

    return event.start < range_end and event.end > range_start


def clip_events_to_range(
    events: List[Event],
    range_start: datetime,
    range_end: datetime,
    tz: ZoneInfo,
) -> List[Event]:
    """Drop events the backends returned that don't really fall in the window."""
    return [e for e in events if event_overlaps_range(e, range_start, range_end, tz)]
