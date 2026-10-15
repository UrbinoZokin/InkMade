"""A pending update shows as a small black badge by the WiFi icon, not as red text.

The status line used to say "Update pending" in red. It was there so whoever
pushed an update could see the device notice it, but the person who sees it
every day can't do anything about it, and red reads as something wrong.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from PIL import ImageChops, ImageDraw

from inkycal.models import Event
from inkycal.render import render_daily_schedule, render_weekly_schedule

TZ = ZoneInfo("America/Phoenix")
W, H, PADDING = 1200, 1600, 40
NOW = datetime(2026, 2, 5, 8, 0, tzinfo=TZ)


def _daily(update_pending):
    event = Event(
        source="google",
        title="Focus",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=TZ),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=TZ),
    )
    return render_daily_schedule(
        canvas_w=W, canvas_h=H, now=NOW, events=[event], tz=TZ,
        show_sleep_banner=False, sleep_banner_text="", update_pending=update_pending,
    )


def _weekly(update_pending):
    return render_weekly_schedule(
        canvas_w=W, canvas_h=H, now=NOW, week_events=[], tz=TZ,
        show_sleep_banner=False, sleep_banner_text="", update_pending=update_pending,
    )


VIEWS = pytest.mark.parametrize("render", [_daily, _weekly], ids=["daily", "weekly"])


@VIEWS
def test_a_pending_update_is_a_badge_just_left_of_the_wifi_icon(render):
    changed = ImageChops.difference(render(False), render(True)).getbbox()

    assert changed is not None, "a pending update must still show"
    left, top, right, bottom = changed
    # In the status bar's bottom-right corner, clear of the WiFi icon (at
    # least 18 px wide, flush with the right-hand padding).
    assert left > W / 2
    assert top >= H - PADDING - 40 and bottom <= H - PADDING + 2
    assert right <= W - PADDING - 18
    # Icon-sized: nothing else on the screen moved to make room for it.
    assert right - left < 40 and bottom - top < 40


@VIEWS
def test_the_badge_is_black_not_red(render):
    img = render(True).convert("RGB")
    reddish = [
        color for _count, color in img.getcolors(maxcolors=1 << 20)
        if color[0] - max(color[1], color[2]) > 60
    ]
    assert reddish == []


@VIEWS
def test_no_update_text_is_written(render, monkeypatch):
    written = []
    original_text = ImageDraw.ImageDraw.text

    def recording_text(self, xy, text, *args, **kwargs):
        written.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)
    render(True)

    assert not any("pending" in t.lower() for t in written)
