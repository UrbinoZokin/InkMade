from datetime import datetime
from zoneinfo import ZoneInfo

from inkycal.models import Event
from inkycal.render import _weekday_header_label, render_weekly_schedule


def _capture_text(monkeypatch):
    from PIL import ImageDraw

    observed = []
    original_text = ImageDraw.ImageDraw.text

    def recording_text(self, xy, text, *args, **kwargs):
        observed.append((xy, text))
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)
    return observed


def test_event_names_shown_without_times(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    event = Event(
        source="google",
        title="Team Sync",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=tz),
    )
    observed = _capture_text(monkeypatch)

    render_weekly_schedule(
        canvas_w=1200,
        canvas_h=1600,
        now=datetime(2026, 2, 5, 8, 0, tzinfo=tz),
        week_events=[event],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    texts = [t for _, t in observed]
    assert "Team Sync" in texts
    assert not any("9:00" in t or "10:00" in t for t in texts)


def test_events_are_grouped_under_their_own_day_in_chronological_order(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    today = datetime(2026, 2, 5, 8, 0, tzinfo=tz)
    today_event = Event(
        source="google",
        title="Today Meeting",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=tz),
    )
    later_event = Event(
        source="google",
        title="Later Meeting",
        start=datetime(2026, 2, 7, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 7, 10, 0, tzinfo=tz),
    )
    observed = _capture_text(monkeypatch)

    render_weekly_schedule(
        canvas_w=1200,
        canvas_h=1600,
        now=today,
        # Passed out of order; the renderer must sort by day itself.
        week_events=[later_event, today_event],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    positions = {}
    for xy, text in observed:
        positions.setdefault(text, xy)

    today_header = _weekday_header_label(today.date(), today.date())
    later_header = _weekday_header_label(datetime(2026, 2, 7).date(), today.date())

    assert positions[today_header][1] < positions["Today Meeting"][1]
    assert positions["Today Meeting"][1] < positions[later_header][1]
    assert positions[later_header][1] < positions["Later Meeting"][1]


def test_day_with_no_events_shows_placeholder(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    observed = _capture_text(monkeypatch)

    render_weekly_schedule(
        canvas_w=1200,
        canvas_h=1600,
        now=datetime(2026, 2, 5, 8, 0, tzinfo=tz),
        week_events=[],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    texts = [t for _, t in observed]
    assert texts.count("No events") == 7


def test_overflow_shows_more_days_notice_when_canvas_is_short(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    events = [
        Event(
            source="google",
            title=f"Day {offset} Event",
            start=datetime(2026, 2, 5 + offset, 9, 0, tzinfo=tz),
            end=datetime(2026, 2, 5 + offset, 10, 0, tzinfo=tz),
        )
        for offset in range(7)
    ]
    observed = _capture_text(monkeypatch)

    render_weekly_schedule(
        canvas_w=1200,
        canvas_h=460,
        now=datetime(2026, 2, 5, 8, 0, tzinfo=tz),
        week_events=events,
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    texts = [t for _, t in observed]
    assert any(t.startswith("Plus ") and "more day" in t for t in texts)


def test_multiday_all_day_event_appears_on_every_day_it_spans(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    today = datetime(2026, 2, 5, 8, 0, tzinfo=tz)
    # Monday 2/5 through Thursday 2/8 (end is exclusive, per Event convention).
    trip = Event(
        source="google",
        title="Family Trip",
        start=datetime(2026, 2, 5, 0, 0, tzinfo=tz),
        end=datetime(2026, 2, 8, 0, 0, tzinfo=tz),
        all_day=True,
    )
    observed = _capture_text(monkeypatch)

    render_weekly_schedule(
        canvas_w=1200,
        canvas_h=1600,
        now=today,
        week_events=[trip],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    texts = [t for _, t in observed]
    assert texts.count("Family Trip") == 3
    assert texts.count("No events") == 4


def test_update_pending_line_is_drawn(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    observed = _capture_text(monkeypatch)

    render_weekly_schedule(
        canvas_w=1200,
        canvas_h=1600,
        now=datetime(2026, 2, 5, 8, 0, tzinfo=tz),
        week_events=[],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
        update_pending=True,
    )

    assert any("Update pending" in t for _, t in observed)
