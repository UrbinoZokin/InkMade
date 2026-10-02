"""The panel while setup mode is on (inkycal.setupscreen)."""
import io
import sys

import pytest

from inkycal import setupscreen
from inkycal.state import State, load_state, save_state

CANVAS_W, CANVAS_H = 300, 400


def _config(tmp_path) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(
        "timezone: 'America/Phoenix'\n"
        f"display:\n  width: {CANVAS_W}\n  height: {CANVAS_H}\n  rotate_degrees: 90\n  border: black\n",
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def panel(monkeypatch):
    shown = []
    monkeypatch.setattr(setupscreen, "show_on_inky", lambda img, **kw: shown.append((img, kw)))
    return shown


def test_the_code_is_split_for_reading_off_a_wall():
    assert setupscreen.format_code("482913") == "482 913"


@pytest.mark.parametrize("size", [(1200, 1600), (CANVAS_W, CANVAS_H)])
def test_draws_the_screen_at_the_panel_size(size):
    img = setupscreen.render_setup_screen("482913", *size, minutes=10, address="192.168.1.50")

    assert img.size == size
    assert img.convert("L").getextrema()[0] < 64, "nothing dark drawn: no code on the screen"


def test_paints_through_setup_mode_with_the_display_settings(tmp_path, panel):
    setupscreen.show_setup_screen("482913", _config(tmp_path), str(tmp_path / "state.json"), minutes=10)

    img, kw = panel[0]
    assert img.size == (CANVAS_W, CANVAS_H)
    assert kw == {"rotate_degrees": 90, "border": "black", "setup_screen": True}


def test_clears_the_render_hash_so_the_calendar_comes_back(tmp_path, panel):
    """However setup mode ends -- even with the agent killed and nothing asking
    for a repaint -- the next scheduled render must not find the panel already
    'showing' the calendar it last drew."""
    state_path = str(tmp_path / "state.json")
    save_state(state_path, State(last_hash="calendar-hash", view_mode="weekly"))

    setupscreen.show_setup_screen("482913", _config(tmp_path), state_path, minutes=10)

    state = load_state(state_path)
    assert state.last_hash == ""
    assert state.view_mode == "weekly"


def test_takes_the_code_on_stdin(tmp_path, panel, monkeypatch):
    """Not on the command line, where every user on the Pi could read it."""
    shown_codes = []
    monkeypatch.setattr(
        setupscreen, "show_setup_screen", lambda code, *a, **kw: shown_codes.append(code)
    )
    monkeypatch.setattr(sys, "argv", ["setupscreen", "--config", _config(tmp_path), "--minutes", "10"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("482913\n"))

    setupscreen.main()

    assert shown_codes == ["482913"]


def test_refuses_to_run_without_a_code(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["setupscreen", "--config", _config(tmp_path), "--minutes", "10"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    with pytest.raises(SystemExit):
        setupscreen.main()
