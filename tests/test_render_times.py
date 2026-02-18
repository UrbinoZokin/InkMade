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
