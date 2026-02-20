from datetime import datetime
from zoneinfo import ZoneInfo

from inkycal.models import Event
from inkycal.render import render_daily_schedule


def test_renders_each_event_time_once(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    start = datetime(2026, 2, 5, 1, 7, tzinfo=tz)
    end = datetime(2026, 2, 5, 2, 8, tzinfo=tz)
    event = Event(source="google", title="Focus", start=start, end=end)

    observed_text = []

    from PIL import ImageDraw

    original_text = ImageDraw.ImageDraw.text

    def recording_text(self, xy, text, *args, **kwargs):
        observed_text.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)

    render_daily_schedule(
        canvas_w=800,
        canvas_h=480,
        now=datetime(2026, 2, 5, 0, 0, tzinfo=tz),
        events=[event],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    assert observed_text.count("1:07 am–2:08 am") == 1


def test_all_day_summary_uses_full_width_and_ignores_time_column(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    all_day = Event(
        source="merged",
        title="All-day: Offsite",
        start=datetime(2026, 2, 5, 0, 0, tzinfo=tz),
        end=datetime(2026, 2, 6, 0, 0, tzinfo=tz),
        all_day=True,
    )
    timed = Event(
        source="google",
        title="Standup",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 9, 30, tzinfo=tz),
    )

    observed_positions = {}

    from PIL import ImageDraw

    original_text = ImageDraw.ImageDraw.text

    def recording_text(self, xy, text, *args, **kwargs):
        observed_positions.setdefault(text, []).append(xy)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)

    render_daily_schedule(
        canvas_w=800,
        canvas_h=480,
        now=datetime(2026, 2, 5, 0, 0, tzinfo=tz),
        events=[all_day, timed],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    assert observed_positions["All-day: Offsite"][0][0] == 40


def test_weather_is_drawn_in_time_weather_column_for_today(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    early = Event(
        source="google",
        title="Morning Run",
        start=datetime(2026, 2, 5, 6, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 7, 0, tzinfo=tz),
        weather_icon="☀",
        weather_text="68°F",
    )
    later = Event(
        source="google",
        title="Commute",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=tz),
        weather_icon="🌧",
        weather_text="102°F",
    )

    observed_calls = []

    from PIL import ImageDraw

    original_text = ImageDraw.ImageDraw.text
    def fixed_textlength(self, text, font=None, *args, **kwargs):
        return float(len(text) * 10)

    def recording_text(self, xy, text, *args, **kwargs):
        observed_calls.append((xy, text, kwargs.get("font")))
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "textlength", fixed_textlength)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)

    render_daily_schedule(
        canvas_w=800,
        canvas_h=480,
        now=datetime(2026, 2, 5, 0, 0, tzinfo=tz),
        events=[early, later],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    weather_icon_call = next(call for call in observed_calls if call[1] == "☀")
    weather_temp_call = next(call for call in observed_calls if call[1] == "68°F")
    assert weather_icon_call[2].size == 38
    assert weather_temp_call[2].size == 38

    # with mocked text lengths, first event weather width is 6 chars = 60 px,
    # and time/weather column width is 160 px from the longest time range text.
    centered_weather_x = 40 + ((160 - 60) / 2)
    assert weather_icon_call[0][0] == centered_weather_x


def test_draws_dividers_for_today_and_tomorrow_timed_events(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    event = Event(
        source="google",
        title="Morning Run",
        start=datetime(2026, 2, 5, 6, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 7, 0, tzinfo=tz),
        weather_icon="☀",
        weather_text="68°F",
    )
    tomorrow_event = Event(
        source="google",
        title="Coffee",
        start=datetime(2026, 2, 6, 8, 0, tzinfo=tz),
        end=datetime(2026, 2, 6, 9, 0, tzinfo=tz),
        weather_icon="☁",
        weather_text="60°F",
    )

    observed_lines = []

    from PIL import ImageDraw

    original_line = ImageDraw.ImageDraw.line

    def recording_line(self, xy, *args, **kwargs):
        observed_lines.append(xy)
        return original_line(self, xy, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "line", recording_line)

    render_daily_schedule(
        canvas_w=800,
        canvas_h=800,
        now=datetime(2026, 2, 5, 0, 0, tzinfo=tz),
        events=[event],
        tomorrow_events=[tomorrow_event],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
    )

    vertical_lines = [line for line in observed_lines if line[0] == line[2] and line[1] != line[3]]
    assert len(vertical_lines) >= 3
