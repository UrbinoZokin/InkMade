"""The daily view's "Upcoming birthdays" line: the rest of the week's birthdays,
early enough to post a card, taken from the week the device already fetches."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from inkycal.main import _split_for_views, _view_signature, _Snapshot
from inkycal.models import Event
from inkycal.render import _load_font, _upcoming_birthday_lines, render_daily_schedule

TZ = ZoneInfo("America/Phoenix")
NOW = datetime(2026, 10, 6, 8, 0, tzinfo=TZ)  # a Tuesday
MIDNIGHT = NOW.replace(hour=0)


def _birthday(days_ahead, title, source="google"):
    start = MIDNIGHT + timedelta(days=days_ahead)
    return Event(source=source, title=title, start=start, end=start + timedelta(days=1), all_day=True, birthday=True)


def _upcoming(raw):
    return [(e.title, e.start.strftime("%a")) for e in _split_for_views(raw, NOW, TZ).upcoming_birthdays]


def test_lists_the_birthdays_after_tomorrow_soonest_first():
    raw = [
        _birthday(5, "Tom Hart's birthday"),
        _birthday(0, "Today Person's birthday"),
        _birthday(1, "Uncle Ray's birthday"),
        _birthday(3, "Emma Segal's birthday"),
        _birthday(6, "Grandma Rose's birthday"),
    ]

    # Today's and tomorrow's have their own "Birthdays" rows already.
    assert _upcoming(raw) == [("Emma Segal", "Fri"), ("Tom Hart", "Sun"), ("Grandma Rose", "Mon")]


def test_a_birthday_on_two_calendars_is_listed_once():
    raw = [_birthday(3, "Emma Segal's birthday"), _birthday(3, "Emma Segal", source="icloud")]

    assert _upcoming(raw) == [("Emma Segal", "Fri")]


def test_other_all_day_events_are_not_birthdays():
    trip = Event(
        source="google", title="Beach trip", start=MIDNIGHT + timedelta(days=3),
        end=MIDNIGHT + timedelta(days=4), all_day=True,
    )

    assert _upcoming([trip]) == []


def _daily_signature(raw):
    snap = _Snapshot(
        now=NOW, events=_split_for_views(raw, NOW, TZ), reminders=[], weather_alerts=[],
        header_date="", show_banner=False, wifi_status="connected", ups_status={}, update_pending=False,
    )
    return _view_signature("daily", snap, TZ)


def test_a_new_upcoming_birthday_repaints_the_daily_view():
    assert _daily_signature([]) != _daily_signature([_birthday(4, "Emma Segal's birthday")])


def _written_by_daily_view(monkeypatch, upcoming):
    written = []
    original_text = ImageDraw.ImageDraw.text

    def recording_text(self, xy, text, *args, **kwargs):
        written.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", recording_text)
    render_daily_schedule(
        canvas_w=1200, canvas_h=1600, now=NOW, events=[], tz=TZ,
        show_sleep_banner=False, sleep_banner_text="", upcoming_birthdays=upcoming,
    )
    return written


def test_the_daily_view_shows_the_line(monkeypatch):
    upcoming = _split_for_views([_birthday(3, "Emma Segal's birthday")], NOW, TZ).upcoming_birthdays

    assert "Upcoming birthdays: Emma Segal (Fri)" in _written_by_daily_view(monkeypatch, upcoming)


def test_no_line_without_upcoming_birthdays(monkeypatch):
    assert not any("Upcoming" in t for t in _written_by_daily_view(monkeypatch, []))


def _lines(names, width=1120):
    draw = ImageDraw.Draw(Image.new("RGB", (1200, 100)))
    birthdays = [_birthday(2 + i % 5, name) for i, name in enumerate(names)]
    return _upcoming_birthday_lines(draw, birthdays, TZ, _load_font(34), width)


def test_lines_break_between_people_not_inside_one():
    lines = _lines(["Emma Segal", "Tom Hart", "Grandma Rose"], width=900)

    assert len(lines) == 2
    assert not any(line.endswith("•") for line in lines)
    for entry in ("Emma Segal (Thu)", "Tom Hart (Fri)", "Grandma Rose (Sat)"):
        assert any(entry in line for line in lines)


def test_names_that_do_not_fit_in_two_lines_are_counted():
    names = ["Emma Segal", "Tom Hart", "Grandma Rose", "Cousin Bartholomew", "Aunt Philippa", "Little Timmy"]

    lines = _lines(names)

    assert len(lines) == 2
    assert lines[-1].endswith("more")
    shown = sum(name in " ".join(lines) for name in names)
    assert f"+{len(names) - shown} more" in lines[-1]
