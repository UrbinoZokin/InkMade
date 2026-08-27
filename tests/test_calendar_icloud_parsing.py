from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import vobject

from inkycal import calendar_icloud
from inkycal.calendar_icloud import fetch_icloud_events

TZ = ZoneInfo("America/Phoenix")


class _FakeCalendarObject:
    def __init__(self, ics: str):
        self.vobject_instance = vobject.readOne(ics)


class _FakeCalendar:
    def __init__(self, name: str, ics_objects):
        self.name = name
        self._objects = [_FakeCalendarObject(ics) for ics in ics_objects]
        self.searched = []

    def date_search(self, start, end):
        self.searched.append((start, end))
        return self._objects


def _fetch(monkeypatch, calendars):
    monkeypatch.setattr(
        calendar_icloud,
        "caldav",
        SimpleNamespace(
            DAVClient=lambda **_kw: SimpleNamespace(
                principal=lambda: SimpleNamespace(calendars=lambda: calendars)
            )
        ),
    )
    return fetch_icloud_events(
        datetime(2026, 8, 27, 0, 0, tzinfo=TZ),
        datetime(2026, 8, 28, 0, 0, tzinfo=TZ),
        TZ,
        "user@example.com",
        "app-password",
        [],
    )


def _ics(*vevents: str) -> str:
    body = "\n".join(vevents)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//test//EN\n{body}\nEND:VCALENDAR\n"


def test_all_day_event_covers_exactly_one_day(monkeypatch):
    ics = _ics(
        "BEGIN:VEVENT\nUID:1\nDTSTART;VALUE=DATE:20260827\n"
        "DTEND;VALUE=DATE:20260828\nSUMMARY:Trash Day\nEND:VEVENT"
    )

    events = _fetch(monkeypatch, [_FakeCalendar("Home", [ics])])

    assert len(events) == 1
    assert events[0].all_day is True
    assert events[0].start == datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    assert events[0].end - events[0].start == timedelta(days=1)


def test_all_day_event_without_dtend_covers_one_day(monkeypatch):
    ics = _ics(
        "BEGIN:VEVENT\nUID:1\nDTSTART;VALUE=DATE:20260827\nSUMMARY:Trash Day\nEND:VEVENT"
    )

    events = _fetch(monkeypatch, [_FakeCalendar("Home", [ics])])

    assert events[0].end - events[0].start == timedelta(days=1)


def test_all_day_event_with_an_inclusive_dtend_still_covers_one_day(monkeypatch):
    ics = _ics(
        "BEGIN:VEVENT\nUID:1\nDTSTART;VALUE=DATE:20260827\n"
        "DTEND;VALUE=DATE:20260827\nSUMMARY:Trash Day\nEND:VEVENT"
    )

    events = _fetch(monkeypatch, [_FakeCalendar("Home", [ics])])

    assert events[0].end - events[0].start == timedelta(days=1)


def test_duration_is_used_when_there_is_no_dtend(monkeypatch):
    ics = _ics(
        "BEGIN:VEVENT\nUID:1\nDTSTART:20260827T090000Z\n"
        "DURATION:PT90M\nSUMMARY:Standup\nEND:VEVENT"
    )

    events = _fetch(monkeypatch, [_FakeCalendar("Home", [ics])])

    assert events[0].all_day is False
    assert events[0].end - events[0].start == timedelta(minutes=90)


def test_every_expanded_occurrence_in_one_object_is_read(monkeypatch):
    # caldav expands recurrences in place, so one object can carry several
    # VEVENTs; reading only the first would drop the rest of the week.
    ics = _ics(
        "BEGIN:VEVENT\nUID:1\nRECURRENCE-ID;VALUE=DATE:20260827\n"
        "DTSTART;VALUE=DATE:20260827\nDTEND;VALUE=DATE:20260828\n"
        "SUMMARY:Daily Walk\nEND:VEVENT",
        "BEGIN:VEVENT\nUID:1\nRECURRENCE-ID;VALUE=DATE:20260828\n"
        "DTSTART;VALUE=DATE:20260828\nDTEND;VALUE=DATE:20260829\n"
        "SUMMARY:Daily Walk\nEND:VEVENT",
    )

    events = _fetch(monkeypatch, [_FakeCalendar("Home", [ics])])

    assert [e.start.date().isoformat() for e in events] == ["2026-08-27", "2026-08-28"]


def test_a_calendar_named_birthdays_flags_its_events(monkeypatch):
    ics = _ics(
        "BEGIN:VEVENT\nUID:1\nDTSTART;VALUE=DATE:20260827\n"
        "DTEND;VALUE=DATE:20260828\nSUMMARY:Jane Doe's birthday\nEND:VEVENT"
    )

    events = _fetch(monkeypatch, [_FakeCalendar("Birthdays", [ics])])

    assert events[0].birthday is True


def test_events_from_other_calendars_are_not_flagged_as_birthdays(monkeypatch):
    ics = _ics(
        "BEGIN:VEVENT\nUID:1\nDTSTART;VALUE=DATE:20260827\n"
        "DTEND;VALUE=DATE:20260828\nSUMMARY:Trash Day\nEND:VEVENT"
    )

    events = _fetch(monkeypatch, [_FakeCalendar("Home", [ics])])

    assert events[0].birthday is False
