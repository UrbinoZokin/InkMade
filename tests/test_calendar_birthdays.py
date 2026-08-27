from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from inkycal import calendar_google
from inkycal.calendar_google import CONTACTS_BIRTHDAY_CALENDAR_ID, fetch_google_events
from inkycal.main import _google_calendar_ids

TZ = ZoneInfo("America/Phoenix")


class _FakeEvents:
    def __init__(self, pages_by_calendar, failing_calendars=()):
        self.pages_by_calendar = pages_by_calendar
        self.failing_calendars = set(failing_calendars)
        self.requested = []

    def list(self, **kwargs):
        self.requested.append(kwargs)
        return SimpleNamespace(execute=lambda: self._respond(**kwargs))

    def _respond(self, calendarId, pageToken=None, **_kwargs):
        if calendarId in self.failing_calendars:
            raise RuntimeError(f"404 not found: {calendarId}")
        pages = self.pages_by_calendar.get(calendarId, [{"items": []}])
        index = 0 if pageToken is None else int(pageToken)
        return pages[index]


class _FakeService:
    def __init__(self, events):
        self._events = events

    def events(self):
        return self._events


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(calendar_google, "_load_creds", lambda _path: object())

    def install(pages_by_calendar, failing_calendars=()):
        fake_events = _FakeEvents(pages_by_calendar, failing_calendars)
        monkeypatch.setattr(
            calendar_google, "build", lambda *_a, **_kw: _FakeService(fake_events)
        )
        return fake_events

    return install


def _fetch(calendar_ids):
    return fetch_google_events(
        calendar_ids,
        datetime(2026, 8, 27, 0, 0, tzinfo=TZ),
        datetime(2026, 8, 28, 0, 0, tzinfo=TZ),
        TZ,
        "/tmp/token.json",
    )


def test_contacts_birthday_calendar_is_added_to_the_configured_ids():
    cfg = SimpleNamespace(
        google=SimpleNamespace(calendar_ids=["primary"], birthdays_enabled=True)
    )

    assert _google_calendar_ids(cfg) == ["primary", CONTACTS_BIRTHDAY_CALENDAR_ID]


def test_contacts_birthday_calendar_is_left_out_when_disabled():
    cfg = SimpleNamespace(
        google=SimpleNamespace(calendar_ids=["primary"], birthdays_enabled=False)
    )

    assert _google_calendar_ids(cfg) == ["primary"]


def test_contacts_birthday_calendar_is_not_added_twice():
    cfg = SimpleNamespace(
        google=SimpleNamespace(
            calendar_ids=["primary", CONTACTS_BIRTHDAY_CALENDAR_ID],
            birthdays_enabled=True,
        )
    )

    assert _google_calendar_ids(cfg) == ["primary", CONTACTS_BIRTHDAY_CALENDAR_ID]


def test_birthdays_are_flagged_and_span_a_single_day(google):
    google({
        CONTACTS_BIRTHDAY_CALENDAR_ID: [{
            "items": [{
                "summary": "Jane Doe's birthday",
                "eventType": "birthday",
                "start": {"date": "2026-08-27"},
                "end": {"date": "2026-08-28"},
            }]
        }]
    })

    events = _fetch([CONTACTS_BIRTHDAY_CALENDAR_ID])

    assert len(events) == 1
    birthday = events[0]
    assert birthday.title == "Jane Doe's birthday"
    assert birthday.all_day is True
    assert birthday.birthday is True
    assert birthday.start == datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    assert birthday.end == datetime(2026, 8, 28, 0, 0, tzinfo=TZ)


def test_ordinary_events_are_not_flagged_as_birthdays(google):
    google({
        "primary": [{
            "items": [{
                "summary": "Standup",
                "start": {"dateTime": "2026-08-27T09:00:00-07:00"},
                "end": {"dateTime": "2026-08-27T09:30:00-07:00"},
            }]
        }]
    })

    events = _fetch(["primary"])

    assert [(e.title, e.birthday, e.all_day) for e in events] == [("Standup", False, False)]


def test_an_all_day_event_missing_its_end_date_still_covers_one_day(google):
    google({
        "primary": [{
            "items": [{
                "summary": "Trash Day",
                "start": {"date": "2026-08-27"},
                "end": {},
            }]
        }]
    })

    event = _fetch(["primary"])[0]

    assert event.start == datetime(2026, 8, 27, 0, 0, tzinfo=TZ)
    assert event.end == datetime(2026, 8, 28, 0, 0, tzinfo=TZ)


def test_an_unreadable_calendar_does_not_cost_the_others(google, capsys):
    google(
        {
            "primary": [{
                "items": [{
                    "summary": "Standup",
                    "start": {"dateTime": "2026-08-27T09:00:00-07:00"},
                    "end": {"dateTime": "2026-08-27T09:30:00-07:00"},
                }]
            }]
        },
        failing_calendars=[CONTACTS_BIRTHDAY_CALENDAR_ID],
    )

    events = _fetch(["primary", CONTACTS_BIRTHDAY_CALENDAR_ID])

    assert [e.title for e in events] == ["Standup"]
    assert "fetch failed; skipping it" in capsys.readouterr().out


def test_all_pages_of_a_calendar_are_read(google):
    fake_events = google({
        "primary": [
            {
                "items": [{
                    "summary": "First",
                    "start": {"date": "2026-08-27"},
                    "end": {"date": "2026-08-28"},
                }],
                "nextPageToken": "1",
            },
            {
                "items": [{
                    "summary": "Second",
                    "start": {"date": "2026-08-27"},
                    "end": {"date": "2026-08-28"},
                }]
            },
        ]
    })

    events = _fetch(["primary"])

    assert [e.title for e in events] == ["First", "Second"]
    assert [call["pageToken"] for call in fake_events.requested] == [None, "1"]


def test_a_cancelled_instance_without_times_is_skipped(google):
    google({
        "primary": [{
            "items": [
                {"status": "cancelled", "start": {}, "end": {}},
                {
                    "summary": "Standup",
                    "start": {"dateTime": "2026-08-27T09:00:00-07:00"},
                    "end": {"dateTime": "2026-08-27T09:30:00-07:00"},
                },
            ]
        }]
    })

    assert [e.title for e in _fetch(["primary"])] == ["Standup"]
