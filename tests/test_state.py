from inkycal.state import State, load_state, save_state


def test_load_state_defaults_to_daily_view_when_missing(tmp_path):
    state = load_state(str(tmp_path / "nonexistent.json"))
    assert state.view_mode == "daily"


def test_view_mode_round_trips_through_save_and_load(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(path, State(view_mode="weekly"))

    state = load_state(path)

    assert state.view_mode == "weekly"


def test_load_state_falls_back_to_daily_for_invalid_view_mode(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"view_mode": "monthly"}', encoding="utf-8")

    state = load_state(str(path))

    assert state.view_mode == "daily"
