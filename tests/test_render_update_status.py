from datetime import datetime
from zoneinfo import ZoneInfo

from inkycal.models import Event
from inkycal.render import render_daily_schedule, _format_update_status


def _render_and_capture(monkeypatch, **kwargs):
    tz = ZoneInfo("America/Phoenix")
    event = Event(
        source="google",
        title="Focus",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=tz),
    )

    observed = []
    from PIL import ImageDraw

    original_text = ImageDraw.ImageDraw.text

    def recording_text(self, xy, text, *args, **kwargs):
        observed.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)

    render_daily_schedule(
        canvas_w=800,
        canvas_h=480,
        now=datetime(2026, 2, 5, 8, 0, tzinfo=tz),
        events=[event],
        tz=tz,
        show_sleep_banner=False,
        sleep_banner_text="",
        **kwargs,
    )
    return observed


def test_format_update_status_combines_pending_and_date():
    tz = ZoneInfo("America/Phoenix")
    updated = datetime(2026, 6, 28, 3, 30, tzinfo=tz)
    text = _format_update_status(True, updated, tz)
    assert "Update pending" in text
    assert "Software updated Jun 28" in text


def test_format_update_status_none_when_nothing_to_show():
    tz = ZoneInfo("America/Phoenix")
    assert _format_update_status(False, None, tz) is None


def test_pending_update_is_drawn(monkeypatch):
    observed = _render_and_capture(monkeypatch, update_pending=True)
    assert any("Update pending" in t for t in observed)


def test_no_ota_line_when_not_pending_and_unknown_date(monkeypatch):
    observed = _render_and_capture(monkeypatch, update_pending=False, last_updated=None)
    assert not any("Update pending" in t for t in observed)
    assert not any("Software updated" in t for t in observed)
