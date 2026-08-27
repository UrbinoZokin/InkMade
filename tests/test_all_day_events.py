from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from inkycal.calendar_common import clip_events_to_range, normalize_all_day_bounds
from inkycal.main import _fetch_events_for_range, _merge_all_day_events
from inkycal.models import Event

TZ = ZoneInfo("America/Phoenix")


def _all_day(title: str, start: datetime, end: datetime, birthday: bool = False) -> Event:
    return Event(source="google", title=title, start=start, end=end, all_day=True, birthday=birthday)


def _day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 0, 0, tzinfo=TZ)


def test_normalize_snaps_partial_days_to_whole_local_days_without_stretching():
    # A feed that expresses an all-day event as UTC midnights reads as 5pm in
    # Phoenix; snapping each end outward would smear one day across two.
    start = datetime(2026, 8, 27, 0, 0, tzinfo=ZoneInfo("UTC"))
    end = datetime(2026, 8, 28, 0, 0, tzinfo=ZoneInfo("UTC"))

    normalized_start, normalized_end = normalize_all_day_bounds(start, end, TZ)

    assert normalized_start == _day(2026, 8, 26)
    assert (normalized_end - normalized_start) == timedelta(days=1)


def test_normalize_keeps_local_midnight_bounds_as_they_are():
    start, end = _day(2026, 8, 27), _day(2026, 8, 28)

    assert normalize_all_day_bounds(start, end, TZ) == (start, end)


def test_normalize_preserves_the_length_of_a_multiday_event():
    start, end = _day(2026, 8, 27), _day(2026, 8, 30)

    assert normalize_all_day_bounds(start, end, TZ) == (start, end)


def test_normalize_survives_a_dst_change_without_adding_a_day():
    tz = ZoneInfo("America/Denver")
    # 2026-11-01 falls back, making the local day 25 hours long.
    start = datetime(2026, 11, 1, 0, 0, tzinfo=tz)
    end = datetime(2026, 11, 2, 0, 0, tzinfo=tz)

    assert normalize_all_day_bounds(start, end, tz) == (start, end)


def test_normalize_gives_a_missing_or_inclusive_end_a_full_single_day():
    start = _day(2026, 8, 27)

    assert normalize_all_day_bounds(start, None, TZ) == (start, _day(2026, 8, 28))
    # DTEND == DTSTART (zero length) still means one whole day.
    assert normalize_all_day_bounds(start, start, TZ) == (start, _day(2026, 8, 28))


def test_all_day_event_is_dropped_from_the_neighbouring_days_range():
    # CalDAV time-ranges go out in UTC, so a floating all-day event on 8/27
    # also matches the server-side query for 8/26 and for 8/28.
    event = _all_day("Anniversary", _day(2026, 8, 27), _day(2026, 8, 28))

    def clipped(day: int):
        return clip_events_to_range([event], _day(2026, 8, day), _day(2026, 8, day + 1), TZ)

    assert clipped(26) == []
    assert clipped(27) == [event]
    assert clipped(28) == []


def test_multiday_all_day_event_survives_every_day_it_covers():
    trip = _all_day("Family Trip", _day(2026, 8, 27), _day(2026, 8, 30))

    for day in (27, 28, 29):
        assert clip_events_to_range([trip], _day(2026, 8, day), _day(2026, 8, day + 1), TZ) == [trip]
    assert clip_events_to_range([trip], _day(2026, 8, 30), _day(2026, 8, 31), TZ) == []


def test_timed_events_are_kept_only_while_they_overlap_the_window():
    meeting = Event(
        source="google",
        title="Standup",
        start=datetime(2026, 8, 27, 9, 0, tzinfo=TZ),
        end=datetime(2026, 8, 27, 9, 30, tzinfo=TZ),
    )
    overnight = Event(
        source="google",
        title="Red-eye",
        start=datetime(2026, 8, 27, 22, 0, tzinfo=TZ),
        end=datetime(2026, 8, 28, 6, 0, tzinfo=TZ),
    )
    window = (_day(2026, 8, 28), _day(2026, 8, 29))

    assert clip_events_to_range([meeting, overnight], *window, TZ) == [overnight]


def test_zero_length_event_is_kept_on_the_day_it_starts():
    ping = Event(
        source="google",
        title="Ping",
        start=datetime(2026, 8, 27, 9, 0, tzinfo=TZ),
        end=datetime(2026, 8, 27, 9, 0, tzinfo=TZ),
    )

    assert clip_events_to_range([ping], _day(2026, 8, 27), _day(2026, 8, 28), TZ) == [ping]
    assert clip_events_to_range([ping], _day(2026, 8, 28), _day(2026, 8, 29), TZ) == []


def test_fetch_for_range_clips_events_the_backend_over_returned(monkeypatch):
    cfg = SimpleNamespace(
        google=SimpleNamespace(enabled=True, calendar_ids=["primary"], birthdays_enabled=False),
        icloud=SimpleNamespace(enabled=False, calendar_name_allowlist=[]),
        travel=SimpleNamespace(enabled=False, origin_address="", back_to_back_window_minutes=30),
    )
    yesterdays_event = _all_day("Yesterday Only", _day(2026, 8, 26), _day(2026, 8, 27))
    todays_event = _all_day("Today Only", _day(2026, 8, 27), _day(2026, 8, 28))

    monkeypatch.setenv("GOOGLE_TOKEN_JSON", "/tmp/token.json")
    monkeypatch.setattr(
        "inkycal.main.fetch_google_events",
        lambda *_a, **_kw: [yesterdays_event, todays_event],
    )

    events = _fetch_events_for_range(cfg, _day(2026, 8, 27), _day(2026, 8, 28), TZ)

    assert [e.title for e in events] == ["All-day: Today Only"]


def test_birthdays_merge_into_their_own_row():
    events = [
        _all_day("Trash Day", _day(2026, 8, 27), _day(2026, 8, 28)),
        _all_day("Jane Doe's birthday", _day(2026, 8, 27), _day(2026, 8, 28), birthday=True),
        _all_day("Al Smith's Birthday", _day(2026, 8, 27), _day(2026, 8, 28), birthday=True),
    ]

    merged = _merge_all_day_events(events)

    assert [e.title for e in merged] == ["All-day: Trash Day", "Birthdays: Al Smith • Jane Doe"]
    assert all(e.all_day for e in merged)


def test_birthday_row_keeps_titles_that_are_not_possessive():
    events = [_all_day("Grandma birthday party", _day(2026, 8, 27), _day(2026, 8, 28), birthday=True)]

    merged = _merge_all_day_events(events)

    assert [e.title for e in merged] == ["Birthdays: Grandma birthday party"]


def test_all_day_row_is_unchanged_when_there_are_no_birthdays():
    events = [
        _all_day("Trash Day", _day(2026, 8, 27), _day(2026, 8, 28)),
        Event(
            source="google",
            title="Standup",
            start=datetime(2026, 8, 27, 9, 0, tzinfo=TZ),
            end=datetime(2026, 8, 27, 9, 30, tzinfo=TZ),
        ),
    ]

    merged = _merge_all_day_events(events)

    assert [e.title for e in merged] == ["All-day: Trash Day", "Standup"]
