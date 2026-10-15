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


# --- every day of the week, with its weather ---------------------------------

from datetime import date, timedelta  # noqa: E402

from inkycal.weather import DayForecast  # noqa: E402

TZ = ZoneInfo("America/Phoenix")
NOW = datetime(2026, 10, 15, 8, 0, tzinfo=TZ)  # a Thursday
DAY_NAMES = ["Thursday", "Friday", "Saturday", "Sunday", "Monday", "Tuesday", "Wednesday"]


def _busy_week(per_day):
    return [
        Event(
            source="google",
            title=f"Appointment number {n} on day {offset}",
            start=datetime(2026, 10, 15, 8 + n, 0, tzinfo=TZ) + timedelta(days=offset),
            end=datetime(2026, 10, 15, 9 + n, 0, tzinfo=TZ) + timedelta(days=offset),
        )
        for offset in range(7)
        for n in range(per_day)
    ]


def _weekly_texts(monkeypatch, events, **kwargs):
    observed = _capture_text(monkeypatch)
    render_weekly_schedule(
        canvas_w=1200, canvas_h=1600, now=NOW, week_events=events, tz=TZ,
        show_sleep_banner=False, sleep_banner_text="", **kwargs,
    )
    return [t for _, t in observed]


def test_a_busy_week_still_shows_all_seven_days(monkeypatch):
    texts = _weekly_texts(monkeypatch, _busy_week(per_day=8))

    for name in DAY_NAMES:
        assert any(t.startswith(name) for t in texts), f"{name} dropped off the week"
    assert not any("more day" in t for t in texts)
    # What doesn't fit is counted under its own day, not lost without a word.
    assert any(t.startswith("+") and t.endswith("more") for t in texts)


def test_a_moderate_week_shows_every_event_in_smaller_type_rather_than_dropping_any(monkeypatch):
    texts = _weekly_texts(monkeypatch, _busy_week(per_day=3))

    assert sum(t.startswith("Appointment number") for t in texts) == 21
    assert not any(t.endswith("more") for t in texts)


def test_each_day_shows_its_high_and_low_and_any_rain_or_snow(monkeypatch):
    forecasts = {
        date(2026, 10, 15): DayForecast(high_f=92, low_f=68, icon="☀"),
        date(2026, 10, 16): DayForecast(high_f=61, low_f=45, icon="☔", precipitation="Rain", precipitation_chance=60),
        date(2026, 10, 17): DayForecast(high_f=30, low_f=18, icon="❄", precipitation="Snow"),
    }

    texts = _weekly_texts(monkeypatch, [], day_forecasts=forecasts)

    for expected in ("92°", "68°", "61°", "45°", "Rain 60%   ", "30°", "18°", "Snow   "):
        assert expected in texts
    # Only the days with a forecast get one.
    assert sum(t.endswith("°") for t in texts) == 6


def test_a_long_day_name_shortens_its_month_to_keep_its_weather(monkeypatch):
    now = datetime(2026, 9, 30, 8, 0, tzinfo=TZ)  # Wednesday, September 30
    forecast = {date(2026, 9, 30): DayForecast(high_f=104, low_f=100, icon="☔", precipitation="Rain", precipitation_chance=100)}
    observed = _capture_text(monkeypatch)

    render_weekly_schedule(
        canvas_w=1200, canvas_h=1600, now=now, week_events=[], tz=TZ,
        show_sleep_banner=False, sleep_banner_text="", day_forecasts=forecast,
    )

    texts = [t for _, t in observed]
    assert "Wednesday, Sep 30 (Today)" in texts
    assert "Thursday, October 1" in texts, "a day without that problem keeps its full month"
