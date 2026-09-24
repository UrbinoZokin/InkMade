"""Saved frames: what the view button puts straight up, and what a press
notice is drawn over. A frame that can't vouch for itself must read as absent,
never as something to show."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image

from inkycal import frames

TZ = ZoneInfo("America/Phoenix")
SIZE = (120, 200)
NOW = datetime(2026, 9, 24, 10, 30, tzinfo=TZ)


def _save(state_path, view_mode="weekly", rendered_at=NOW, color=(30, 30, 200), size=SIZE, content_hash="abc"):
    return frames.save_frame(state_path, view_mode, Image.new("RGB", size, color), content_hash, rendered_at)


def test_a_frame_round_trips_with_what_it_was_drawn_from(tmp_path):
    state_path = str(tmp_path / "state.json")

    assert _save(state_path, "weekly") is True

    assert frames.frame_path(state_path, "weekly") == str(tmp_path / "frame_weekly.png")
    img, info = frames.load_frame(state_path, "weekly")
    assert img.getpixel((0, 0)) == (30, 30, 200)
    assert info == frames.FrameInfo(view_mode="weekly", content_hash="abc", rendered_at=NOW, size=SIZE)
    assert frames.read_frame_info(state_path, "weekly") == info


def test_each_view_keeps_its_own_frame(tmp_path):
    state_path = str(tmp_path / "state.json")

    _save(state_path, "daily", color=(200, 30, 30))
    _save(state_path, "weekly", color=(30, 30, 200))

    assert frames.load_frame(state_path, "daily")[0].getpixel((0, 0)) == (200, 30, 30)
    assert frames.load_frame(state_path, "weekly")[0].getpixel((0, 0)) == (30, 30, 200)


def test_nothing_saved_reads_as_no_frame(tmp_path):
    state_path = str(tmp_path / "state.json")

    assert frames.read_frame_info(state_path, "daily") is None
    assert frames.load_frame(state_path, "daily") is None


def test_a_frame_saved_as_another_view_is_not_trusted(tmp_path):
    # e.g. copied into place by hand: showing it would put up the wrong view.
    state_path = str(tmp_path / "state.json")
    _save(state_path, "daily")
    (tmp_path / "frame_daily.png").rename(tmp_path / "frame_weekly.png")

    assert frames.read_frame_info(state_path, "weekly") is None
    assert frames.load_frame(state_path, "weekly") is None


def test_a_png_without_the_frame_details_is_not_trusted(tmp_path):
    state_path = str(tmp_path / "state.json")
    Image.new("RGB", SIZE, "white").save(tmp_path / "frame_weekly.png")

    assert frames.load_frame(state_path, "weekly") is None


def test_a_damaged_frame_is_not_loaded(tmp_path):
    state_path = str(tmp_path / "state.json")
    _save(state_path, "weekly")
    path = tmp_path / "frame_weekly.png"
    path.write_bytes(path.read_bytes()[:60])

    assert frames.load_frame(state_path, "weekly") is None


def test_saving_leaves_no_temp_file_behind(tmp_path):
    state_path = str(tmp_path / "state.json")

    _save(state_path, "daily")
    _save(state_path, "daily")

    assert sorted(p.name for p in tmp_path.iterdir()) == ["frame_daily.png"]


def test_a_frame_that_cannot_be_saved_is_reported_not_raised(tmp_path, capsys):
    # The directory it belongs in is a file: the render must go on regardless.
    blocker = tmp_path / "state"
    blocker.write_text("", encoding="utf-8")

    assert _save(str(blocker / "state.json"), "daily") is False
    assert "Could not save the daily frame" in capsys.readouterr().out


def _info(rendered_at):
    return frames.FrameInfo(view_mode="weekly", content_hash="abc", rendered_at=rendered_at, size=SIZE)


def test_a_frame_is_fresh_for_an_hour():
    assert frames.is_fresh(_info(NOW - timedelta(minutes=59)), NOW)
    assert not frames.is_fresh(_info(NOW - timedelta(hours=1)), NOW)


def test_a_frame_from_before_midnight_is_stale_however_recent():
    # Its header and the weekly view's seven days both belong to yesterday.
    just_after_midnight = datetime(2026, 9, 25, 0, 5, tzinfo=TZ)

    assert not frames.is_fresh(_info(datetime(2026, 9, 24, 23, 55, tzinfo=TZ)), just_after_midnight)


def test_a_frame_stamped_in_the_future_is_not_fresh():
    # The clock moved backwards since it was drawn; its age means nothing.
    assert not frames.is_fresh(_info(NOW + timedelta(minutes=5)), NOW)


def test_freshness_compares_local_dates_whatever_zone_the_stamp_is_in():
    evening = datetime(2026, 9, 24, 20, 0, tzinfo=TZ)
    utc_stamp = (evening - timedelta(minutes=10)).astimezone(ZoneInfo("UTC"))
    assert utc_stamp.date() != evening.date()  # already the 25th in UTC

    assert frames.is_fresh(_info(utc_stamp), evening)


def test_a_hidden_frame_is_redrawn_long_before_it_goes_stale():
    # Renders are a quarter hour apart and can each run a few minutes late;
    # a frame due for redrawing must still be fresh when the render that
    # redraws it finally comes round.
    render_interval, drift = timedelta(minutes=15), timedelta(minutes=5)

    assert frames.REDRAW_AFTER + render_interval + drift <= frames.FRESH_FOR
