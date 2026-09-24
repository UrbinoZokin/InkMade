"""run_once() serves both views from one fetch, and keeps the one that isn't
on screen drawn and saved for the view button (see inkycal.frames).

The panel-side contract is unchanged -- repaint only on a change, a force or
the hourly refresh -- so every test here also checks the panel wasn't
repainted when it shouldn't have been.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkycal import frames, main
from inkycal.models import Event
from inkycal.state import load_state

TZ = ZoneInfo("America/Phoenix")

CONFIG = """
timezone: "America/Phoenix"
sleep:
  enabled: false
display:
  width: 60
  height: 80
  rotate_degrees: 0
  border: white
calendars:
  google:
    enabled: false
  icloud:
    enabled: false
travel:
  enabled: {travel_enabled}
  origin_address: "1 Main St"
auto_update:
  enabled: false
"""


class _NoWeather:
    def __init__(self, **_kwargs):
        pass

    def active_alerts(self):
        return []

    def forecast_for_datetime(self, _when):
        return None

    def forecast_for_event_start(self, _start):
        return None


@pytest.fixture
def paths(tmp_path):
    def make(travel_enabled: str = "false") -> tuple[str, str]:
        config = tmp_path / "config.yaml"
        config.write_text(CONFIG.format(travel_enabled=travel_enabled), encoding="utf-8")
        return str(config), str(tmp_path / "state.json")

    return make


@pytest.fixture
def calendar(monkeypatch):
    """What the calendar backends hold; run_once sees it through one fetch."""
    events: list[Event] = []
    monkeypatch.setattr(main, "_fetch_raw_events", lambda *_a, **_kw: list(events))
    return events


@pytest.fixture
def panel(monkeypatch):
    shown = []
    monkeypatch.setattr(main, "WeatherForecastResolver", _NoWeather)
    monkeypatch.setattr(main, "render_daily_schedule", lambda **_kw: Image.new("RGB", (60, 80), "white"))
    monkeypatch.setattr(main, "show_on_inky", lambda img, **_kw: shown.append(img))
    return shown


def _event(title: str, hour: int, day_offset: int = 0, location: str | None = None) -> Event:
    midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(days=day_offset, hours=hour)
    return Event(source="google", title=title, start=start, end=start + timedelta(hours=1), location=location)


def test_one_calendar_fetch_serves_both_views(paths, panel, monkeypatch):
    # The daily view used to fetch today and tomorrow separately, and the
    # weekly view the whole week again; today and tomorrow are inside it.
    fetches = []
    monkeypatch.setattr(
        main, "_fetch_raw_events", lambda _cfg, start, end, _tz: fetches.append((start, end)) or []
    )
    config_path, state_path = paths()

    main.run_once(config_path=config_path, state_path=state_path)

    assert len(fetches) == 1
    start, end = fetches[0]
    assert start == datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    assert end - start == timedelta(days=7)


def test_both_views_are_left_saved(paths, calendar, panel):
    config_path, state_path = paths()
    calendar.append(_event("Standup", hour=9))

    main.run_once(config_path=config_path, state_path=state_path)

    assert len(panel) == 1
    daily = frames.read_frame_info(state_path, "daily")
    weekly = frames.read_frame_info(state_path, "weekly")
    assert daily.content_hash == load_state(state_path).last_hash  # the one on the panel
    assert weekly is not None and weekly.content_hash != daily.content_hash


def test_a_change_only_the_hidden_view_shows_redraws_it_but_leaves_the_panel(paths, calendar, panel):
    config_path, state_path = paths()
    main.run_once(config_path=config_path, state_path=state_path)
    before = frames.read_frame_info(state_path, "weekly")

    # Three days out: on the weekly view, not on today's or tomorrow's.
    calendar.append(_event("Dentist", hour=9, day_offset=3))
    main.run_once(config_path=config_path, state_path=state_path)

    assert len(panel) == 1
    assert frames.read_frame_info(state_path, "weekly").content_hash != before.content_hash


def test_an_unchanged_hidden_view_is_left_alone(paths, calendar, panel):
    config_path, state_path = paths()
    main.run_once(config_path=config_path, state_path=state_path)
    before = frames.read_frame_info(state_path, "weekly")

    main.run_once(config_path=config_path, state_path=state_path)

    assert frames.read_frame_info(state_path, "weekly") == before


def test_the_hidden_view_is_redrawn_before_it_is_too_old_to_switch_to(paths, calendar, panel):
    config_path, state_path = paths()
    main.run_once(config_path=config_path, state_path=state_path)
    img, info = frames.load_frame(state_path, "weekly")
    aging = datetime.now(TZ) - frames.REDRAW_AFTER - timedelta(minutes=1)
    frames.save_frame(state_path, "weekly", img, info.content_hash, aging)

    main.run_once(config_path=config_path, state_path=state_path)

    assert frames.is_fresh(frames.read_frame_info(state_path, "weekly"), datetime.now(TZ), frames.REDRAW_AFTER)
    assert len(panel) == 1


def test_after_a_switch_the_old_view_becomes_the_one_kept_ready(paths, calendar, panel):
    config_path, state_path = paths()
    main.run_once(config_path=config_path, state_path=state_path)

    main.run_once(config_path=config_path, state_path=state_path, toggle_view=True)

    assert load_state(state_path).view_mode == "weekly"
    assert len(panel) == 2
    assert frames.read_frame_info(state_path, "weekly").content_hash == load_state(state_path).last_hash
    assert frames.read_frame_info(state_path, "daily") is not None


def test_the_view_on_the_panel_gets_a_saved_frame_even_without_a_repaint(paths, calendar, panel):
    # The first run after the update that introduced saved frames usually has
    # nothing to repaint, but a press notice still needs a frame to draw over.
    config_path, state_path = paths()
    main.run_once(config_path=config_path, state_path=state_path)
    os.remove(frames.frame_path(state_path, "daily"))

    main.run_once(config_path=config_path, state_path=state_path)

    assert len(panel) == 1
    assert frames.read_frame_info(state_path, "daily").content_hash == load_state(state_path).last_hash


def test_a_hidden_view_that_fails_to_draw_does_not_fail_the_run(paths, calendar, panel, monkeypatch, capsys):
    def broken(**_kwargs):
        raise RuntimeError("font missing")

    monkeypatch.setattr(main, "render_weekly_schedule", broken)
    config_path, state_path = paths()

    main.run_once(config_path=config_path, state_path=state_path)

    assert len(panel) == 1
    assert load_state(state_path).last_hash
    assert frames.read_frame_info(state_path, "weekly") is None
    assert "Could not draw the weekly view ahead of time" in capsys.readouterr().out


def test_one_weather_resolver_serves_the_whole_run(paths, calendar, panel, monkeypatch):
    # It downloads the forecast once, so one resolver means one download.
    created = []

    class CountingWeather(_NoWeather):
        def __init__(self, **kwargs):
            created.append(self)

    monkeypatch.setattr(main, "WeatherForecastResolver", CountingWeather)
    calendar.extend([_event("Standup", hour=9), _event("Review", hour=10, day_offset=1)])
    config_path, state_path = paths()

    main.run_once(config_path=config_path, state_path=state_path)

    assert len(created) == 1


def test_weather_and_travel_are_looked_up_only_for_a_frame_being_drawn(paths, calendar, panel, monkeypatch):
    # Neither is in the content hash, so a run that finds nothing changed has
    # no use for them -- and that's most runs.
    lookups = []

    class CountingWeather(_NoWeather):
        def forecast_for_event_start(self, _start):
            lookups.append("weather")

    class CountingTravel:
        def estimate(self, _origin, _destination):
            lookups.append("travel")
            return None

    monkeypatch.setattr(main, "WeatherForecastResolver", CountingWeather)
    monkeypatch.setattr(main, "TravelTimeResolver", CountingTravel)
    calendar.append(_event("Dentist", hour=9, location="1 Clinic Way"))
    config_path, state_path = paths(travel_enabled="true")

    main.run_once(config_path=config_path, state_path=state_path)
    assert sorted(set(lookups)) == ["travel", "weather"]

    lookups.clear()
    main.run_once(config_path=config_path, state_path=state_path)
    assert lookups == []
    assert len(panel) == 1
