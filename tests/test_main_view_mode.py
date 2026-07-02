from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from inkycal.main import (
    _events_signature,
    _fetch_events_for_week,
    _toggle_view_mode,
    _week_range,
)
from inkycal.models import Event


def test_toggle_view_mode_flips_between_daily_and_weekly():
    assert _toggle_view_mode("daily") == "weekly"
    assert _toggle_view_mode("weekly") == "daily"
    # Any unrecognized value is treated as non-weekly, so it flips to weekly.
    assert _toggle_view_mode("") == "weekly"


def test_week_range_spans_seven_days_from_local_midnight():
    tz = ZoneInfo("America/Phoenix")
    now = datetime(2026, 2, 5, 14, 30, tzinfo=tz)

    start, end = _week_range(now, tz)

    assert start == datetime(2026, 2, 5, 0, 0, tzinfo=tz)
    assert end == start + timedelta(days=7)


def test_events_signature_differs_by_view_mode():
    tz = ZoneInfo("America/Phoenix")
    kwargs = dict(
        tz=tz,
        events=[],
        tomorrow_events=[],
        weather_alerts=[],
        header_date="Thursday, February 5, 2026",
        sleep_banner=False,
        wifi_status="connected",
        ups_status={},
    )

    daily_sig = _events_signature(**kwargs, view_mode="daily")
    weekly_sig = _events_signature(**kwargs, view_mode="weekly")

    assert daily_sig != weekly_sig


def test_events_signature_reflects_week_events_changes():
    tz = ZoneInfo("America/Phoenix")
    event = Event(
        source="google",
        title="Standup",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 9, 30, tzinfo=tz),
    )
    kwargs = dict(
        tz=tz,
        events=[],
        tomorrow_events=[],
        weather_alerts=[],
        header_date="Thursday, February 5, 2026",
        sleep_banner=False,
        wifi_status="connected",
        ups_status={},
        view_mode="weekly",
    )

    empty_sig = _events_signature(**kwargs, week_events=[])
    with_event_sig = _events_signature(**kwargs, week_events=[event])

    assert empty_sig != with_event_sig


def test_fetch_events_for_week_dedupes_but_does_not_merge_all_day_events(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    cfg = SimpleNamespace(
        google=SimpleNamespace(enabled=True, calendar_ids=["primary"]),
        icloud=SimpleNamespace(enabled=False, calendar_name_allowlist=[]),
    )
    monday = Event(
        source="google",
        title="Company Holiday",
        start=datetime(2026, 2, 2, 0, 0, tzinfo=tz),
        end=datetime(2026, 2, 3, 0, 0, tzinfo=tz),
        all_day=True,
    )
    friday = Event(
        source="google",
        title="Offsite",
        start=datetime(2026, 2, 6, 0, 0, tzinfo=tz),
        end=datetime(2026, 2, 7, 0, 0, tzinfo=tz),
        all_day=True,
    )
    duplicate = Event(
        source="google",
        title=" company   holiday ",
        start=datetime(2026, 2, 2, 0, 0, tzinfo=tz),
        end=datetime(2026, 2, 3, 0, 0, tzinfo=tz),
        all_day=True,
    )

    monkeypatch.setenv("GOOGLE_TOKEN_JSON", "/tmp/token.json")
    monkeypatch.setattr(
        "inkycal.main.fetch_google_events",
        lambda *_args, **_kwargs: [monday, friday, duplicate],
    )

    events = _fetch_events_for_week(
        cfg,
        datetime(2026, 2, 2, 0, 0, tzinfo=tz),
        datetime(2026, 2, 9, 0, 0, tzinfo=tz),
        tz,
    )

    # The Monday duplicate is deduped away, but distinct-day all-day events
    # stay separate (unlike the daily view's merge-into-one-row behavior).
    assert len(events) == 2
    assert {e.start.date() for e in events} == {monday.start.date(), friday.start.date()}
    assert "Offsite" in {e.title for e in events}
