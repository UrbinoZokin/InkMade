from types import SimpleNamespace

import pytest
from PIL import Image

from inkycal import feedback
from inkycal.state import State, load_state, save_state


CANVAS_W, CANVAS_H = 120, 200


def _config(tmp_path, press_feedback: str | None = None) -> str:
    body = [
        "timezone: 'America/Phoenix'",
        "display:",
        f"  width: {CANVAS_W}",
        f"  height: {CANVAS_H}",
    ]
    if press_feedback is not None:
        body += ["buttons:", f"  press_feedback: {press_feedback}"]
    path = tmp_path / "config.yaml"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return str(path)


def _frame(color=(200, 30, 30), size=(CANVAS_W, CANVAS_H)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_last_frame_is_cached_next_to_the_state_file(tmp_path):
    state_path = str(tmp_path / "state.json")

    feedback.save_last_frame(state_path, _frame())

    assert feedback.last_frame_path(state_path) == str(tmp_path / feedback.LAST_FRAME_NAME)
    cached = feedback.load_last_frame(state_path, CANVAS_W, CANVAS_H)
    assert cached is not None
    assert cached.size == (CANVAS_W, CANVAS_H)
    assert cached.getpixel((0, 0)) == (200, 30, 30)


def test_load_last_frame_returns_none_when_there_is_nothing_cached(tmp_path):
    assert feedback.load_last_frame(str(tmp_path / "state.json"), CANVAS_W, CANVAS_H) is None


def test_load_last_frame_rejects_a_frame_from_a_different_canvas_size(tmp_path):
    # e.g. the display size changed in config.yaml since that frame was drawn;
    # pasting a banner onto it would leave the panel part stale, part blank.
    state_path = str(tmp_path / "state.json")
    feedback.save_last_frame(state_path, _frame(size=(CANVAS_W // 2, CANVAS_H)))

    assert feedback.load_last_frame(state_path, CANVAS_W, CANVAS_H) is None


def test_save_last_frame_leaves_no_temp_file_behind(tmp_path):
    state_path = str(tmp_path / "state.json")

    feedback.save_last_frame(state_path, _frame())

    assert sorted(p.name for p in tmp_path.iterdir()) == [feedback.LAST_FRAME_NAME]


def test_render_notice_over_a_base_frame_keeps_the_schedule_and_adds_a_bar(tmp_path):
    base = _frame()

    img = feedback.render_notice("Refreshing...", CANVAS_W, CANVAS_H, base=base)

    assert img.getpixel((2, 2)) == (0, 0, 0)  # notice bar across the top
    assert img.getpixel((2, CANVAS_H - 2)) == (200, 30, 30)  # previous frame below it
    assert base.getpixel((2, 2)) == (200, 30, 30)  # base itself untouched


def test_render_notice_without_a_base_frame_wipes_the_panel(tmp_path):
    img = feedback.render_notice("Refreshing...", CANVAS_W, CANVAS_H)

    assert img.getpixel((0, 0)) == (255, 255, 255)
    assert img.getcolors() is None or any(color == (0, 0, 0) for _count, color in img.getcolors())


@pytest.mark.parametrize(
    "configured,requested,expected",
    [
        ("banner", None, "banner"),
        ("wipe", None, "wipe"),
        ("none", None, "none"),
        ("  WIPE  ", None, "wipe"),
        ("banner", "none", "none"),
        ("nonsense", None, "banner"),
        ("", None, "banner"),
    ],
)
def test_resolve_style(configured, requested, expected):
    assert feedback.resolve_style(configured, requested) == expected


def test_show_notice_draws_over_the_cached_frame(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(feedback, "show_on_inky", lambda img, **kw: shown.append((img, kw)))
    state_path = str(tmp_path / "state.json")
    feedback.save_last_frame(state_path, _frame())

    assert feedback.show_notice("Refreshing...", _config(tmp_path), state_path) is True

    img, _kw = shown[0]
    assert img.size == (CANVAS_W, CANVAS_H)
    assert img.getpixel((2, CANVAS_H - 2)) == (200, 30, 30)


def test_show_notice_falls_back_to_a_wipe_when_no_frame_is_cached(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(feedback, "show_on_inky", lambda img, **kw: shown.append((img, kw)))

    assert feedback.show_notice("Refreshing...", _config(tmp_path), str(tmp_path / "state.json")) is True

    img, _kw = shown[0]
    assert img.getpixel((0, 0)) == (255, 255, 255)


def test_show_notice_does_nothing_when_press_feedback_is_off(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(feedback, "show_on_inky", lambda img, **kw: shown.append(img))

    assert feedback.show_notice("Refreshing...", _config(tmp_path, "none"), str(tmp_path / "state.json")) is False
    assert shown == []


def test_show_notice_clears_the_render_hash_so_the_panel_gets_repainted(tmp_path, monkeypatch):
    # The notice is now what's on screen, so run_once's "content unchanged,
    # skip the refresh" shortcut would otherwise leave it up indefinitely.
    monkeypatch.setattr(feedback, "show_on_inky", lambda img, **kw: None)
    state_path = str(tmp_path / "state.json")
    save_state(state_path, State(last_hash="abc123", view_mode="weekly"))

    feedback.show_notice("Checking for updates...", _config(tmp_path), state_path)

    state = load_state(state_path)
    assert state.last_hash == ""
    assert state.view_mode == "weekly"  # the rest of the state is left alone


def test_show_notice_passes_the_display_settings_through(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(feedback, "show_on_inky", lambda img, **kw: shown.append(kw))
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "timezone: 'America/Phoenix'\n"
        "display:\n  width: 120\n  height: 200\n  rotate_degrees: 90\n  border: black\n",
        encoding="utf-8",
    )

    feedback.show_notice("Refreshing...", str(cfg_path), str(tmp_path / "state.json"))

    assert shown[0] == {"rotate_degrees": 90, "border": "black"}
