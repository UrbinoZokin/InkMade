from __future__ import annotations
from datetime import datetime
import logging
from typing import List
from zoneinfo import ZoneInfo

import caldav
from caldav.elements import dav

from .models import Event

ICLOUD_CALDAV_URL = "https://caldav.icloud.com/"
_ICAL_COMPAT_MSG = "Ical data was modified to avoid compatibility issues"


class _IcalCompatibilityFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _ICAL_COMPAT_MSG not in record.getMessage()


def _install_ical_compatibility_filter() -> None:
    root_logger = logging.getLogger()
    if any(isinstance(f, _IcalCompatibilityFilter) for f in root_logger.filters):
        return
    root_logger.addFilter(_IcalCompatibilityFilter())

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
        name = getattr(cal, "name", None) or cal.get_properties([dav.DisplayName()]).get(dav.DisplayName(), "")
        if calendar_name_allowlist and name not in calendar_name_allowlist:
            continue

        results = cal.date_search(day_start, day_end)

        for r in results:
            vobj = r.vobject_instance
            vevent = getattr(vobj, "vevent", None)
            if vevent is None:
                continue

            title = str(getattr(vevent, "summary", None).value) if hasattr(vevent, "summary") else "(No title)"
            location = str(getattr(vevent, "location", None).value) if hasattr(vevent, "location") else None

            dtstart = vevent.dtstart.value
            dtend = vevent.dtend.value

            # dtstart may be date (all-day) or datetime
            if isinstance(dtstart, datetime):
                start = dtstart.astimezone(tz) if dtstart.tzinfo else dtstart.replace(tzinfo=tz)
                end = dtend.astimezone(tz) if isinstance(dtend, datetime) and dtend.tzinfo else (
                    dtend.replace(tzinfo=tz) if isinstance(dtend, datetime) else datetime.combine(dtend, datetime.min.time(), tzinfo=tz)
                )
                all_day = False
            else:
                # date-only all-day event
                start = datetime.combine(dtstart, datetime.min.time(), tzinfo=tz)
                # dtend for all-day is usually the next day (exclusive)
                if isinstance(dtend, datetime):
                    end = dtend.replace(tzinfo=tz)
                else:
                    end = datetime.combine(dtend, datetime.min.time(), tzinfo=tz)
                all_day = True

            events.append(Event(
                source="icloud",
                title=title,
                start=start,
                end=end,
                all_day=all_day,
                location=location,
            ))

    return events
