"""run_once() must reach the panel even when its inputs are damaged.

Everything here guards the same failure: the display quietly stops updating.
E-ink holds its last image, so a run that dies (or returns early) before
show_on_inky leaves yesterday on the wall, and a cause that repeats every
quarter hour leaves it there for good.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkycal import main
from inkycal.models import Event
from inkycal.state import load_state

BASE_CONFIG = """
timezone: "America/Phoenix"
sleep:
  enabled: {sleep_enabled}
  start: "{sleep_start}"
  end: "{sleep_end}"
  banner_text: "Sleeping"
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
  enabled: false
auto_update:
  enabled: false
"""


class _NoWeather:
    """Stands in for WeatherForecastResolver; run_once builds one eagerly."""

    def __init__(self, **_kwargs):
        pass

    def active_alerts(self):
        return []

    def forecast_for_datetime(self, _when):
        return None

    def forecast_for_event_start(self, _start):
        return None


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """A stubbed render + panel. Returns the list of frames pushed to it."""
    shown = []
    monkeypatch.setattr(main, "WeatherForecastResolver", _NoWeather)
    monkeypatch.setattr(main, "render_daily_schedule", lambda **_kw: Image.new("RGB", (60, 80), "white"))
    monkeypatch.setattr(main, "show_on_inky", lambda img, **_kw: shown.append(img))
    return shown


def _config(tmp_path, *, sleep_enabled="false", sleep_start="22:30", sleep_end="06:30") -> str:
    path = tmp_path / "config.yaml"
    path.write_text(
        BASE_CONFIG.format(
            sleep_enabled=sleep_enabled, sleep_start=sleep_start, sleep_end=sleep_end
        ),
        encoding="utf-8",
    )
    return str(path)


def test_repaints_and_repairs_a_corrupt_state_file(tmp_path, panel):
    """A torn state.json used to raise out of load_state before anything was
    drawn, and did so again on every following run."""
    state_path = tmp_path / "state.json"
    state_path.write_text('{"last_hash": "abc123", "last_rend', encoding="utf-8")

    main.run_once(config_path=_config(tmp_path), state_path=str(state_path))

    assert len(panel) == 1, "a damaged state file must not cost us the refresh"
    assert load_state(str(state_path)).last_hash, "and the file should be readable again"


def test_repaints_when_the_sleep_window_is_empty(tmp_path, panel, monkeypatch):
    """start == end is an empty window. It used to read as always-asleep, so
    once the one-per-day sleep banner had been placed, run_once returned early
    around the clock and the schedule never reached the panel again."""
    config_path = _config(tmp_path, sleep_enabled="true", sleep_start="00:00", sleep_end="00:00")
    state_path = str(tmp_path / "state.json")

    tz = ZoneInfo("America/Phoenix")
    fetched: list[list[Event]] = [
        [],
        [Event(
            source="google",
            title="Dentist",
            start=datetime(2026, 8, 31, 9, 0, tzinfo=tz),
            end=datetime(2026, 8, 31, 10, 0, tzinfo=tz),
        )],
    ]
    monkeypatch.setattr(
        main, "_fetch_events_for_range", lambda *_a, **_kw: fetched.pop(0) if fetched else []
    )

    main.run_once(config_path=config_path, state_path=state_path)
    # A new event on the calendar: the display has to show it.
    main.run_once(config_path=config_path, state_path=state_path)

    assert len(panel) == 2


def test_skips_the_panel_when_nothing_changed(tmp_path, panel):
    """The other half of the contract: unchanged content still must not cost a
    full repaint, which is what keeps a panel this size from ghosting."""
    config_path = _config(tmp_path)
    state_path = str(tmp_path / "state.json")

    main.run_once(config_path=config_path, state_path=state_path)
    main.run_once(config_path=config_path, state_path=state_path)

    assert len(panel) == 1


def test_force_repaints_even_when_nothing_changed(tmp_path, panel):
    config_path = _config(tmp_path)
    state_path = str(tmp_path / "state.json")

    main.run_once(config_path=config_path, state_path=state_path)
    main.run_once(config_path=config_path, state_path=state_path, force=True)

    assert len(panel) == 2
