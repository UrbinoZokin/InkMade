"""run_once() must reach the panel even when its inputs are damaged.

Everything here guards the same failure: the display quietly stops updating.
E-ink holds its last image, so a run that dies (or returns early) before
show_on_inky leaves yesterday on the wall, and a cause that repeats every
quarter hour leaves it there for good.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkycal import main
from inkycal.models import Event
from inkycal.state import load_state
from inkycal.updates import UpdateStatus

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
  enabled: {auto_update}
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


def _render_daily(**kw) -> Image.Image:
    img = Image.new("RGB", (60, 80), "white")
    img.info["sleep_banner"] = kw["show_sleep_banner"]
    img.info["update_pending"] = kw["update_pending"]
    return img


@pytest.fixture
def panel(tmp_path, monkeypatch):
    """A stubbed render + panel. Returns the list of frames pushed to it; each
    frame's info records whether it was drawn with the sleep banner and with
    "Update pending"."""
    shown = []
    monkeypatch.setattr(main, "WeatherForecastResolver", _NoWeather)
    monkeypatch.setattr(main, "render_daily_schedule", _render_daily)
    monkeypatch.setattr(main, "show_on_inky", lambda img, **_kw: shown.append(img))
    return shown


TZ = ZoneInfo("America/Phoenix")


@pytest.fixture
def clock(monkeypatch):
    """The time run_once reads. Starts Monday 2026-09-21 at noon; set .now to move it."""
    wall = SimpleNamespace(now=datetime(2026, 9, 21, 12, 0, tzinfo=TZ))

    class _WallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall.now.astimezone(tz)

    monkeypatch.setattr(main, "datetime", _WallClock)
    return wall


def _event_today(title: str, hour: int, day_offset: int = 0) -> Event:
    midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = midnight + timedelta(days=day_offset, hours=hour)
    return Event(source="google", title=title, start=start, end=start + timedelta(hours=1))


def _config(
    tmp_path, *, sleep_enabled="false", sleep_start="22:30", sleep_end="06:30", auto_update="false"
) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(
        BASE_CONFIG.format(
            sleep_enabled=sleep_enabled,
            sleep_start=sleep_start,
            sleep_end=sleep_end,
            auto_update=auto_update,
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

    calendar: list[Event] = []
    monkeypatch.setattr(main, "_fetch_raw_events", lambda *_a, **_kw: list(calendar))

    main.run_once(config_path=config_path, state_path=state_path)
    # A new event on the calendar: the display has to show it.
    calendar.append(_event_today("Dentist", hour=9))
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


def test_sleep_banner_goes_up_once_a_night_as_the_window_opens(tmp_path, panel, clock, monkeypatch):
    """The default window, 22:30 to 06:30, spans two calendar dates. Keyed on
    the date, the banner was painted again at midnight, and the next evening's
    window then read as already having its banner: run_once returned early and
    the panel sat on the last daytime frame until midnight came round again."""
    config_path = _config(tmp_path, sleep_enabled="true", sleep_start="22:30", sleep_end="06:30")
    state_path = str(tmp_path / "state.json")
    monkeypatch.setattr(main, "_fetch_raw_events", lambda *_a, **_kw: [])

    banner_paints = []
    # Every quarter hour, as inkycal.timer runs it, Monday noon to Wednesday noon.
    until = clock.now + timedelta(days=2)
    while clock.now <= until:
        already_shown = len(panel)
        main.run_once(config_path=config_path, state_path=state_path)
        banner_paints += [clock.now for img in panel[already_shown:] if img.info["sleep_banner"]]
        clock.now += timedelta(minutes=15)

    assert banner_paints == [
        datetime(2026, 9, 21, 22, 30, tzinfo=TZ),  # Monday night
        datetime(2026, 9, 22, 22, 30, tzinfo=TZ),  # Tuesday night, and nothing at either midnight
    ]


def test_a_forced_render_takes_update_pending_off_the_sleeping_panel(tmp_path, panel, clock, monkeypatch):
    """ota_update.sh applies updates inside the sleep window and then forces a
    render (through inkycal-boot.service). Unforced, that render returns early
    once the night's banner is up, and the panel keeps saying "Update pending"
    until the 06:30 wake-up."""
    config_path = _config(tmp_path, sleep_enabled="true", auto_update="true")
    state_path = str(tmp_path / "state.json")
    monkeypatch.setattr(main, "_fetch_raw_events", lambda *_a, **_kw: [])
    origin = SimpleNamespace(ahead=True)
    monkeypatch.setattr(main.updates, "check_for_update", lambda **_kw: UpdateStatus(available=origin.ahead))

    clock.now = datetime(2026, 9, 21, 22, 30, tzinfo=TZ)
    main.run_once(config_path=config_path, state_path=state_path)  # the night's banner
    clock.now += timedelta(minutes=10)
    origin.ahead = False  # the updater has applied it
    main.run_once(config_path=config_path, state_path=state_path)  # a plain render: skipped
    main.run_once(config_path=config_path, state_path=state_path, force=True)  # what the updater starts

    assert [(img.info["sleep_banner"], img.info["update_pending"]) for img in panel] == [
        (True, True),
        (True, False),
    ]
