"""The state setup mode shares with the rest of the program (inkycal.setupmode).

The marker decides whether a render may touch the panel, so both ways of
getting it wrong matter: a marker that sticks freezes the calendar behind a
dead code, and one that lapses early lets a render paint over a live one.
"""
import json
import subprocess
import time

import pytest

from inkycal import setupmode


@pytest.fixture
def marker(tmp_path, monkeypatch):
    path = tmp_path / "run" / "setup-mode.json"
    monkeypatch.setattr(setupmode, "MARKER_PATH", str(path))
    return path


@pytest.fixture
def request_flag(tmp_path, monkeypatch):
    path = tmp_path / "run" / "setup-requested"
    monkeypatch.setattr(setupmode, "REQUEST_PATH", str(path))
    return path


def test_not_active_without_a_marker(marker):
    assert setupmode.is_active() is False


def test_active_while_a_live_agent_holds_the_panel(marker):
    setupmode.mark_active(60)

    assert setupmode.is_active() is True


def test_clear_hands_the_panel_back(marker):
    setupmode.mark_active(60)
    setupmode.clear()

    assert setupmode.is_active() is False
    setupmode.clear()  # and clearing twice is harmless


def test_lapses_at_its_deadline(marker):
    setupmode.mark_active(-1)

    assert setupmode.is_active() is False


def test_a_dead_agent_releases_the_panel_at_once(marker):
    """An agent killed mid-session can't clean up after itself; waiting out
    its deadline would hold the calendar off the panel for no one."""
    finished = subprocess.Popen(["true"])
    finished.wait()
    setupmode.mark_active(600)
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["pid"] = finished.pid
    marker.write_text(json.dumps(data), encoding="utf-8")

    assert setupmode.is_active() is False


def test_a_wall_clock_jump_does_not_end_it(marker, monkeypatch):
    """The Pi has no RTC: at power-on -- when a first-time setup session starts
    -- the wall clock can be hours behind until NTP corrects it. A deadline on
    that clock would expire the moment the correction landed."""
    setupmode.mark_active(600)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 6 * 3600)

    assert setupmode.is_active() is True


@pytest.mark.parametrize(
    "content",
    ["", "{not json", "[]", '{"pid": 1}', '{"until_monotonic": 1e12}', '{"pid": "x", "until_monotonic": 1e12}'],
)
def test_a_damaged_marker_never_blocks_the_calendar(marker, content):
    marker.parent.mkdir(parents=True)
    marker.write_text(content, encoding="utf-8")

    assert setupmode.is_active() is False


def test_the_marker_holds_no_code(marker):
    setupmode.mark_active(60)

    assert set(json.loads(marker.read_text(encoding="utf-8"))) == {"pid", "until_monotonic"}


def test_a_request_is_taken_exactly_once(request_flag):
    assert setupmode.take_request() is False

    setupmode.request()
    assert setupmode.request_pending() is True

    assert setupmode.take_request() is True
    assert setupmode.request_pending() is False
    assert setupmode.take_request() is False
