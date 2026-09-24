"""The view button's fast path. Whatever it can't vouch for, it must leave
alone -- the button handler then takes the slow path, whose toggle depends on
state.json still naming the old view."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkycal import frames, viewswap
from inkycal.state import State, load_state, save_state

TZ = ZoneInfo("America/Phoenix")
CANVAS_W, CANVAS_H = 120, 200


@pytest.fixture
def panel(monkeypatch):
    shown = []
    monkeypatch.setattr(viewswap, "show_on_inky", lambda img, **kw: shown.append((img, kw)))
    return shown


def _config(tmp_path) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(
        "timezone: 'America/Phoenix'\n"
        f"display:\n  width: {CANVAS_W}\n  height: {CANVAS_H}\n  rotate_degrees: 90\n  border: black\n",
        encoding="utf-8",
    )
    return str(path)


def _state(tmp_path, view_mode="daily") -> str:
    state_path = str(tmp_path / "state.json")
    save_state(
        state_path,
        State(
            last_hash="daily-hash",
            last_rendered_iso="2026-09-24T09:00:00-07:00",
            last_sleep_banner_date="2026-09-23",
            view_mode=view_mode,
        ),
    )
    return state_path


def _save_weekly(state_path, *, age=timedelta(0), size=(CANVAS_W, CANVAS_H)) -> datetime:
    rendered_at = datetime.now(TZ) - age
    frames.save_frame(state_path, "weekly", Image.new("RGB", size, (30, 30, 200)), "weekly-hash", rendered_at)
    return rendered_at


def test_puts_up_the_saved_frame_and_records_the_switch(tmp_path, panel):
    state_path = _state(tmp_path)
    rendered_at = _save_weekly(state_path)

    assert viewswap.show_other_view(_config(tmp_path), state_path) is True

    img, kw = panel[0]
    assert img.getpixel((0, 0)) == (30, 30, 200)
    assert kw == {"rotate_degrees": 90, "border": "black"}
    state = load_state(state_path)
    assert state.view_mode == "weekly"
    # The next run compares against what's now on the panel, and the hourly
    # repaint is timed from when that frame was drawn, not from the press.
    assert state.last_hash == "weekly-hash"
    assert datetime.fromisoformat(state.last_rendered_iso) == rendered_at
    assert state.last_sleep_banner_date == "2026-09-23"


def test_switches_back_to_daily_the_same_way(tmp_path, panel):
    state_path = _state(tmp_path, view_mode="weekly")
    frames.save_frame(state_path, "daily", Image.new("RGB", (CANVAS_W, CANVAS_H)), "d", datetime.now(TZ))

    assert viewswap.show_other_view(_config(tmp_path), state_path) is True
    assert load_state(state_path).view_mode == "daily"


def test_keeps_what_a_render_saved_while_the_panel_was_busy(tmp_path, monkeypatch):
    state_path = _state(tmp_path)
    _save_weekly(state_path)

    def render_finishing_meanwhile(_img, **_kw):
        state = load_state(state_path)
        state.last_sleep_banner_date = "2026-09-24"
        save_state(state_path, state)

    monkeypatch.setattr(viewswap, "show_on_inky", render_finishing_meanwhile)

    viewswap.show_other_view(_config(tmp_path), state_path)

    state = load_state(state_path)
    assert state.view_mode == "weekly"
    assert state.last_sleep_banner_date == "2026-09-24"


@pytest.mark.parametrize(
    "setup",
    [
        pytest.param(lambda state_path: None, id="nothing-saved"),
        pytest.param(lambda state_path: _save_weekly(state_path, age=timedelta(hours=2)), id="too-old"),
        pytest.param(lambda state_path: _save_weekly(state_path, size=(60, 80)), id="wrong-size"),
    ],
)
def test_leaves_everything_alone_without_a_fresh_frame(tmp_path, panel, setup):
    state_path = _state(tmp_path)
    setup(state_path)
    before = load_state(state_path)

    assert viewswap.show_other_view(_config(tmp_path), state_path) is False

    assert panel == []
    assert load_state(state_path) == before


def test_entrypoint_exits_with_no_fresh_frame_when_it_cannot_switch(tmp_path, panel, monkeypatch):
    state_path = _state(tmp_path)
    monkeypatch.setattr("sys.argv", ["viewswap", "--config", _config(tmp_path), "--state", state_path])

    with pytest.raises(SystemExit) as exc:
        viewswap.main()

    assert exc.value.code == viewswap.NO_FRESH_FRAME


def test_entrypoint_exits_cleanly_after_switching(tmp_path, panel, monkeypatch):
    state_path = _state(tmp_path)
    _save_weekly(state_path)
    monkeypatch.setattr("sys.argv", ["viewswap", "--config", _config(tmp_path), "--state", state_path])

    viewswap.main()  # no SystemExit: status 0

    assert len(panel) == 1
