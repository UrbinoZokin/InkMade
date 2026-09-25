"""The sleep window gate in front of every refresh.

run_once() returns early while the window is open, so a window that reads as
open when it should not is indistinguishable from a display that has stopped
updating: the panel keeps its last image and the journal just says
"In sleep window; skipping poll/refresh" every quarter hour.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from inkycal.main import _is_in_sleep_window, _parse_hhmm, _sleep_window_start_date

TZ = ZoneInfo("America/Phoenix")

MONDAY = date(2026, 8, 31)
SUNDAY = date(2026, 8, 30)


def _monday_at(hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime(MONDAY.year, MONDAY.month, MONDAY.day, hour, minute, tzinfo=TZ)


def _asleep_at(hhmm: str, start: str, end: str) -> bool:
    return _is_in_sleep_window(_monday_at(hhmm), _parse_hhmm(start), _parse_hhmm(end))


def _night_of(hhmm: str, start: str, end: str) -> date:
    return _sleep_window_start_date(_monday_at(hhmm), _parse_hhmm(start), _parse_hhmm(end))


@pytest.mark.parametrize("at,expected", [
    ("22:29", False),
    ("22:30", True),   # inclusive start
    ("03:00", True),   # across midnight
    ("06:29", True),
    ("06:30", False),  # exclusive end
    ("12:00", False),
])
def test_overnight_window(at, expected):
    assert _asleep_at(at, "22:30", "06:30") is expected


@pytest.mark.parametrize("at,expected", [
    ("00:30", False),
    ("01:00", True),
    ("02:59", True),
    ("03:00", False),
])
def test_same_day_window(at, expected):
    assert _asleep_at(at, "01:00", "03:00") is expected


@pytest.mark.parametrize("at", ["00:00", "06:00", "12:00", "18:00", "23:59"])
def test_an_empty_window_never_sleeps(at):
    """start == end means no sleep window, not a permanent one.

    The overnight branch is "at or after start, or before end", which with
    equal times is true at every instant of the day. A config written to turn
    sleep off by collapsing the window would otherwise skip every refresh
    around the clock, and the display would never update again.
    """
    assert _asleep_at(at, "00:00", "00:00") is False
    assert _asleep_at(at, "21:45", "21:45") is False


# The once-a-night sleep banner is keyed on the date the window started.

@pytest.mark.parametrize("at,expected", [
    ("22:30", MONDAY),  # the window opening tonight
    ("23:59", MONDAY),
    ("00:00", SUNDAY),  # past midnight: still the night that began yesterday
    ("03:00", SUNDAY),
    ("06:29", SUNDAY),
])
def test_an_overnight_window_is_one_night_across_midnight(at, expected):
    """Keyed on the calendar date instead, midnight read as a new night (so a
    second banner paint) and the next evening as a night that already had its
    banner (so none until midnight came round again)."""
    assert _night_of(at, "22:30", "06:30") == expected


@pytest.mark.parametrize("start,end,at", [
    ("01:00", "03:00", "01:00"),
    ("01:00", "03:00", "02:59"),
    ("00:00", "06:30", "00:00"),  # starting on the stroke of midnight
    ("00:00", "06:30", "06:29"),
])
def test_a_window_within_one_day_starts_on_that_day(start, end, at):
    assert _night_of(at, start, end) == MONDAY


def test_new_years_eve_night_belongs_to_the_old_year():
    small_hours = datetime(2027, 1, 1, 3, 0, tzinfo=TZ)

    night = _sleep_window_start_date(small_hours, _parse_hhmm("22:30"), _parse_hhmm("06:30"))

    assert night == date(2026, 12, 31)
