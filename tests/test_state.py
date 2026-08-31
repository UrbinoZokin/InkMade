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


# A state file that cannot be parsed must never take the refresh down with it:
# run_once() loads it before anything else, e-ink holds its last image, and
# every later run would die in the same place -- so one bad file freezes the
# panel permanently. Falling back to a blank state also repairs it, because an
# empty last_hash makes the next run repaint and rewrite the file.

def test_load_state_recovers_from_a_truncated_file(tmp_path):
    path = tmp_path / "state.json"
    # What a power cut mid-write leaves behind.
    path.write_text('{"last_hash": "abc123", "last_rend', encoding="utf-8")

    state = load_state(str(path))

    assert state == State()


def test_load_state_recovers_from_an_empty_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("", encoding="utf-8")

    assert load_state(str(path)) == State()


def test_load_state_recovers_from_valid_json_that_is_not_an_object(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("null", encoding="utf-8")

    assert load_state(str(path)) == State()

    path.write_text("[]", encoding="utf-8")

    assert load_state(str(path)) == State()


def test_load_state_recovers_when_the_file_cannot_be_read(tmp_path):
    # A directory where the state file should be: read_text raises OSError,
    # which is just as fatal to the refresh as bad JSON.
    path = tmp_path / "state.json"
    path.mkdir()

    assert load_state(str(path)) == State()


def test_a_recovered_state_file_is_repaired_by_the_next_save(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{oops", encoding="utf-8")

    state = load_state(str(path))
    assert state.last_hash == ""  # so the next run repaints unconditionally
    save_state(str(path), State(last_hash="fresh", view_mode="weekly"))

    reloaded = load_state(str(path))
    assert reloaded.last_hash == "fresh"
    assert reloaded.view_mode == "weekly"
