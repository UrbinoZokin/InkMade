from datetime import datetime
from zoneinfo import ZoneInfo

from inkycal.main import _dedupe_events
from inkycal.models import Event


def _event(title: str, location: str | None = None) -> Event:
    tz = ZoneInfo("America/Phoenix")
    return Event(
        source="google",
        title=title,
        start=datetime(2026, 1, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 1, 5, 10, 0, tzinfo=tz),
        location=location,
    )


def test_dedupe_uses_title_fingerprint_and_keeps_richer_event():
    sparse = _event(" Team   Sync ", None)
    richer = _event("team-sync", "HQ East")

    deduped = _dedupe_events([sparse, richer])

    assert len(deduped) == 1
    assert deduped[0].location == "HQ East"


def test_dedupe_keeps_same_title_time_events_when_locations_conflict():
    first = _event("Planning", "HQ West")
    second = _event("planning", "HQ East")

    deduped = _dedupe_events([first, second])

    assert len(deduped) == 2


def test_dedupe_handles_whitespace_and_case_only_title_differences():
    first = _event("PROJECT UPDATE")
    second = _event(" project\tupdate ")

    deduped = _dedupe_events([first, second])

    assert len(deduped) == 1
