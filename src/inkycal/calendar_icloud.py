from __future__ import annotations
from datetime import datetime, timedelta
import logging
from typing import List, Optional
from zoneinfo import ZoneInfo

import caldav
from caldav.elements import dav

from .calendar_common import normalize_all_day_bounds
from .models import Event

ICLOUD_CALDAV_URL = "https://caldav.icloud.com/"
# iCloud does not publish the Contacts-derived birthday calendar over
# CalDAV, but a shared or manually kept birthday calendar shows up like any
# other; recognize it by name so those events group with Google's.
BIRTHDAY_CALENDAR_NAMES = {"birthdays", "birthday"}
_ICAL_COMPAT_MSG = "Ical data was modified to avoid compatibility issues"


class _IcalCompatibilityFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _ICAL_COMPAT_MSG not in record.getMessage()


def _install_ical_compatibility_filter() -> None:
    root_logger = logging.getLogger()
    if any(isinstance(f, _IcalCompatibilityFilter) for f in root_logger.filters):
        return
    root_logger.addFilter(_IcalCompatibilityFilter())


def _calendar_display_name(cal) -> str:
    name = getattr(cal, "name", None)
    if name:
        return str(name)
    props = cal.get_properties([dav.DisplayName()])
    return str(props.get(dav.DisplayName(), "") or "")


def _vevents(calendar_object) -> list:
    """Every VEVENT in one CalDAV object.

    caldav expands recurrences in place, so a single object can hold several
    occurrences; reading only `.vevent` would silently drop all but the first.
    """
    vobj = calendar_object.vobject_instance
    if vobj is None:
        return []
    contents = getattr(vobj, "contents", None)
    if contents:
        return list(contents.get("vevent", []))
    vevent = getattr(vobj, "vevent", None)
    return [vevent] if vevent is not None else []


def _text_value(vevent, field: str, default: Optional[str] = None) -> Optional[str]:
    attr = getattr(vevent, field, None)
    if attr is None or attr.value is None:
        return default
    return str(attr.value)


def _dtend_value(vevent, dtstart):
    """DTEND, or what RFC 5545 says it is when the event only carries DURATION.

    Birthday and anniversary feeds in particular tend to ship DTSTART plus a
    DURATION (or nothing at all) rather than an explicit DTEND.
    """
    dtend = getattr(vevent, "dtend", None)
    if dtend is not None and dtend.value is not None:
        return dtend.value

    duration = getattr(vevent, "duration", None)
    if duration is not None and duration.value is not None:
        return dtstart + duration.value

    if isinstance(dtstart, datetime):
        return dtstart
    return dtstart + timedelta(days=1)


def _to_aware(value, tz: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(tz) if value.tzinfo else value.replace(tzinfo=tz)
    return datetime.combine(value, datetime.min.time(), tzinfo=tz)


def _parse_vevent(vevent, tz: ZoneInfo, is_birthday_calendar: bool) -> Optional[Event]:
    dtstart_attr = getattr(vevent, "dtstart", None)
    if dtstart_attr is None or dtstart_attr.value is None:
        return None

    dtstart = dtstart_attr.value
    dtend = _dtend_value(vevent, dtstart)

    # A date (rather than datetime) DTSTART is what marks an all-day event.
    all_day = not isinstance(dtstart, datetime)
    start = _to_aware(dtstart, tz)
    end = _to_aware(dtend, tz)
    if all_day:
        start, end = normalize_all_day_bounds(start, end, tz)

    return Event(
        source="icloud",
        title=_text_value(vevent, "summary", "(No title)") or "(No title)",
        start=start,
        end=end,
        all_day=all_day,
        birthday=is_birthday_calendar,
        location=_text_value(vevent, "location"),
    )


def fetch_icloud_events(
    day_start: datetime,
    day_end: datetime,
    tz: ZoneInfo,
    username: str,
    app_password: str,
    calendar_name_allowlist: List[str],
) -> List[Event]:
    _install_ical_compatibility_filter()

    client = caldav.DAVClient(
        url=ICLOUD_CALDAV_URL,
        username=username,
        password=app_password,
    )
    principal = client.principal()
    calendars = principal.calendars()

    events: List[Event] = []

    for cal in calendars:
        name = _calendar_display_name(cal)
        if calendar_name_allowlist and name not in calendar_name_allowlist:
            continue

        is_birthday_calendar = name.strip().lower() in BIRTHDAY_CALENDAR_NAMES
        results = cal.date_search(day_start, day_end)

        for r in results:
            for vevent in _vevents(r):
                event = _parse_vevent(vevent, tz, is_birthday_calendar)
                if event is not None:
                    events.append(event)

    return events
