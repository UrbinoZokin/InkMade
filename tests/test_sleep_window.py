"""The sleep window gate in front of every refresh.

run_once() returns early while the window is open, so a window that reads as
open when it should not is indistinguishable from a display that has stopped
updating: the panel keeps its last image and the journal just says
"In sleep window; skipping poll/refresh" every quarter hour.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from inkycal.main import _is_in_sleep_window, _parse_hhmm

TZ = ZoneInfo("America/Phoenix")


def _asleep_at(hhmm: str, start: str, end: str) -> bool:
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime(2026, 8, 31, hour, minute, tzinfo=TZ)
    return _is_in_sleep_window(now, _parse_hhmm(start), _parse_hhmm(end))


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
