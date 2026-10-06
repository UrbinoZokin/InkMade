import os
import threading
from types import SimpleNamespace

import pytest

from inkycal import appuser, buttons, setupmode, viewswap


def test_app_owner_ids_matches_directory_stat(tmp_path):
    st = os.stat(tmp_path)

    uid, gid = buttons._app_owner_ids(str(tmp_path))

    assert (uid, gid) == (st.st_uid, st.st_gid)


def test_app_owner_groups_falls_back_to_gid_on_lookup_failure(monkeypatch):
    monkeypatch.setattr(appuser.pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid)))

    groups = buttons._app_owner_groups(uid=999999, gid=42)

    assert groups == [42]


def test_spawn_env_merges_dotenv_without_mutating_os_environ(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('ICLOUD_USERNAME="me@example.com"\n', encoding="utf-8")
    monkeypatch.delenv("ICLOUD_USERNAME", raising=False)

    env = buttons._spawn_env(str(tmp_path))

    assert env["ICLOUD_USERNAME"] == "me@example.com"
    assert "ICLOUD_USERNAME" not in os.environ


def test_spawn_env_drops_bare_keys_dotenv_values_maps_to_none(tmp_path):
    (tmp_path / ".env").write_text("BARE_VAR\nGOOGLE_TOKEN_JSON=/tmp/token.json\n", encoding="utf-8")

    env = buttons._spawn_env(str(tmp_path))

    assert "BARE_VAR" not in env
    assert env["GOOGLE_TOKEN_JSON"] == "/tmp/token.json"
    assert all(v is not None for v in env.values())


def test_run_main_drops_privileges_and_forces_refresh(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {"FAKE": "1"})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid, 999])

    app_dir = str(tmp_path)
    buttons._run_main(app_dir, "/opt/inkycal/config.yaml", "/var/lib/inkycal/state.json", toggle_view=False)

    (cmd,), kwargs = calls[0]
    assert cmd[-1] == "--force"
    assert "--toggle-view" not in cmd
    assert kwargs["cwd"] == app_dir
    assert kwargs["env"] == {"FAKE": "1"}
    assert kwargs["check"] is False
    # extra_groups is required, or setgroups() is never called and the child
    # keeps the daemon's (root's) supplementary groups instead of dropping to
    # the app user's real ones.
    assert kwargs["extra_groups"] == [kwargs["group"], 999]


def test_run_main_appends_toggle_view_flag(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])

    buttons._run_main(str(tmp_path), "config.yaml", "state.json", toggle_view=True)

    (cmd,), _kwargs = calls[0]
    assert cmd[-2:] == ["--force", "--toggle-view"]


def test_run_main_can_run_unforced(tmp_path, monkeypatch):
    # The view button's check after a saved frame goes up: repaint only if
    # something changed, exactly like a timer run.
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])

    buttons._run_main(str(tmp_path), "config.yaml", "state.json", toggle_view=False, force=False)

    (cmd,), _kwargs = calls[0]
    assert cmd[-4:] == ["--config", "config.yaml", "--state", "state.json"]


def test_run_main_reports_nonzero_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(buttons.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])

    buttons._run_main(str(tmp_path), "config.yaml", "state.json", toggle_view=False)

    assert "exited with code 1" in capsys.readouterr().out


def test_trigger_force_update_writes_flag_file_and_waits_for_the_service(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )

    state_path = str(tmp_path / "state.json")
    assert buttons._trigger_force_update(state_path) is True

    (cmd,), kwargs = calls[0]
    # No --setenv=: systemctl start does not support it (only systemd-run does).
    # No --no-block either: the display is showing a "checking for updates"
    # notice, and waiting is what tells us when to take it back off.
    assert cmd == ["systemctl", "start", "inkycal-update.service"]
    assert kwargs["check"] is False
    assert kwargs["timeout"] == buttons.UPDATE_TIMEOUT_S
    assert (tmp_path / buttons.FORCE_UPDATE_FLAG_NAME).exists()


def test_trigger_force_update_reports_not_finished_when_the_service_outlasts_the_wait(tmp_path, monkeypatch):
    def timeout(*a, **kw):
        raise buttons.subprocess.TimeoutExpired(cmd="systemctl", timeout=buttons.UPDATE_TIMEOUT_S)

    monkeypatch.setattr(buttons.subprocess, "run", timeout)

    assert buttons._trigger_force_update(str(tmp_path / "state.json")) is False


def test_show_feedback_runs_the_notice_entrypoint_as_the_app_user(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])

    buttons._show_feedback(str(tmp_path), "config.yaml", "state.json", "Refreshing...", echo=False)

    (cmd,), kwargs = calls[0]
    assert cmd[1:3] == ["-m", "inkycal.feedback"]
    assert cmd[-2:] == ["--message", "Refreshing..."]
    assert kwargs["timeout"] == buttons.FEEDBACK_TIMEOUT_S
    assert kwargs["user"] == os.stat(tmp_path).st_uid


def test_show_feedback_never_blocks_the_work_it_announces(tmp_path, monkeypatch, capsys):
    def timeout(*a, **kw):
        raise buttons.subprocess.TimeoutExpired(cmd="python", timeout=buttons.FEEDBACK_TIMEOUT_S)

    monkeypatch.setattr(buttons.subprocess, "run", timeout)
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])

    # A display that will not take the notice is not a reason to skip the
    # refresh: no exception escapes to the button handler.
    buttons._show_feedback(str(tmp_path), "config.yaml", "state.json", "Refreshing...", echo=False)

    assert "timed out" in capsys.readouterr().out


def test_run_guarded_acts_on_a_press_when_nothing_is_in_flight():
    ran = []

    worker = buttons._run_guarded("Button B (refresh)", lambda: ran.append("work"), echo=False)

    worker.join(timeout=5)
    assert ran == ["work"]


def test_run_guarded_drops_a_press_arriving_while_the_previous_one_is_still_working(capsys):
    ran = []

    # A press landing mid-refresh means the panel hasn't visibly answered the
    # first one yet -- not that a second refresh is wanted behind it.
    with buttons._WORK_LOCK:
        assert buttons._run_guarded("Button B (refresh)", lambda: ran.append("work"), echo=False) is None

    assert ran == []
    assert "already working on the previous press" in capsys.readouterr().out


def test_run_guarded_releases_the_lock_when_the_work_fails(capsys):
    def boom():
        raise RuntimeError("display busy")

    buttons._run_guarded("Button A (view)", boom, echo=False).join(timeout=5)
    assert "Button A (view) failed: display busy" in capsys.readouterr().out

    # A failed press must not wedge every press after it.
    ran = []
    buttons._run_guarded("Button A (view)", lambda: ran.append("work"), echo=False).join(timeout=5)
    assert ran == ["work"]


def test_presses_arriving_during_the_work_are_dropped_not_queued():
    # gpiozero hands every press to its handler from one thread (lgpio's
    # notification thread) and only hands over the next once the handler has
    # returned. A handler that did the work itself held each repeat press back
    # until the work was done, then ran it anyway: three impatient presses,
    # three full refresh cycles, one after another.
    finish = threading.Event()
    ran = []

    def slow_work():
        ran.append("work")
        finish.wait(timeout=5)

    workers = []

    def deliver_three_presses():
        for _ in range(3):
            workers.append(buttons._run_guarded("Button A (view)", slow_work, echo=False))

    delivery = threading.Thread(target=deliver_three_presses)
    delivery.start()
    try:
        delivery.join(timeout=2)
        handed_over_while_working = not delivery.is_alive()
    finally:
        finish.set()
        delivery.join(timeout=15)
        for worker in workers:
            if isinstance(worker, threading.Thread):
                worker.join(timeout=5)

    assert handed_over_while_working, "each press must be handed over while the first is still working"
    assert ran == ["work"]
    assert [worker is None for worker in workers] == [False, True, True]


def test_a_press_whose_work_cannot_start_does_not_lock_out_the_next(monkeypatch, capsys):
    class NoThreads:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(buttons, "threading", SimpleNamespace(Thread=NoThreads))

    assert buttons._run_guarded("Button B (refresh)", lambda: None, echo=False) is None
    assert "Button B (refresh) failed: can't start new thread" in capsys.readouterr().out

    monkeypatch.undo()
    ran = []
    buttons._run_guarded("Button B (refresh)", lambda: ran.append("work"), echo=False).join(timeout=5)
    assert ran == ["work"]


def test_logged_in_terminals_parses_who_output(monkeypatch):
    who_output = (
        "pi       pts/0        2026-08-28 09:14 (192.168.1.20)\n"
        "pi       pts/1        2026-08-28 09:20 (192.168.1.31)\n"
        "root     tty1         2026-08-28 08:02\n"
    )
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=who_output)
    )

    assert buttons._logged_in_terminals() == ["/dev/pts/0", "/dev/pts/1", "/dev/tty1"]


def test_logged_in_terminals_dedupes_repeated_devices(monkeypatch):
    who_output = "pi  pts/0  2026-08-28 09:14\npi  pts/0  2026-08-28 09:14\n\n"
    monkeypatch.setattr(
        buttons.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=who_output)
    )

    assert buttons._logged_in_terminals() == ["/dev/pts/0"]


def test_logged_in_terminals_falls_back_to_open_ptys_when_who_unavailable(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("who")

    monkeypatch.setattr(buttons.subprocess, "run", boom)
    monkeypatch.setattr(buttons.glob, "glob", lambda pattern: ["/dev/pts/3", "/dev/pts/ptmx", "/dev/pts/1"])

    # ptmx is the multiplexer, not somebody's terminal.
    assert buttons._logged_in_terminals() == ["/dev/pts/1", "/dev/pts/3"]


def test_broadcast_writes_message_to_every_logged_in_terminal(tmp_path, monkeypatch):
    first = tmp_path / "pts0"
    second = tmp_path / "pts1"
    first.touch()
    second.touch()
    monkeypatch.setattr(buttons, "_logged_in_terminals", lambda: [str(first), str(second)])

    buttons._broadcast("Button A (view) pressed")

    for device in (first, second):
        # Bytes, not read_text(): \r\n keeps the line flush left even on a
        # terminal in raw mode, and universal newlines would hide the \r.
        assert device.read_bytes() == b"\r\n[InkyCal] Button A (view) pressed\r\n"


def test_broadcast_skips_terminals_that_cannot_be_written(tmp_path, monkeypatch):
    reachable = tmp_path / "pts0"
    reachable.touch()
    monkeypatch.setattr(
        buttons, "_logged_in_terminals", lambda: [str(tmp_path / "logged-out"), str(reachable)]
    )

    buttons._broadcast("Button D (update) pressed")

    assert b"Button D (update) pressed" in reachable.read_bytes()


def test_announce_logs_and_echoes_when_enabled(monkeypatch, capsys):
    broadcast = []
    monkeypatch.setattr(buttons, "_broadcast", broadcast.append)

    buttons._announce("Button B (refresh) pressed", echo=True)

    assert "Button B (refresh) pressed" in capsys.readouterr().out
    assert broadcast == ["Button B (refresh) pressed"]


def test_announce_stays_in_the_journal_when_echo_disabled(monkeypatch, capsys):
    broadcast = []
    monkeypatch.setattr(buttons, "_broadcast", broadcast.append)

    buttons._announce("Button C pressed: no function assigned", echo=False)

    assert "Button C pressed" in capsys.readouterr().out
    assert broadcast == []


def _fake_viewswap(monkeypatch, outcome):
    calls = []

    def run(*a, **kw):
        calls.append((a, kw))
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(returncode=outcome)

    monkeypatch.setattr(buttons.subprocess, "run", run)
    monkeypatch.setattr(buttons, "_spawn_env", lambda app_dir: {})
    monkeypatch.setattr(buttons, "_app_owner_groups", lambda uid, gid: [gid])
    return calls


def test_show_saved_view_runs_the_viewswap_entrypoint_as_the_app_user(tmp_path, monkeypatch):
    calls = _fake_viewswap(monkeypatch, 0)

    assert buttons._show_saved_view(str(tmp_path), "config.yaml", "state.json", echo=False) is True

    (cmd,), kwargs = calls[0]
    assert cmd[1:3] == ["-m", "inkycal.viewswap"]
    assert cmd[3:] == ["--config", "config.yaml", "--state", "state.json"]
    assert kwargs["timeout"] == buttons.FEEDBACK_TIMEOUT_S
    assert kwargs["user"] == os.stat(tmp_path).st_uid


@pytest.mark.parametrize("returncode", [viewswap.NO_FRESH_FRAME, 1])
def test_show_saved_view_sends_the_press_down_the_slow_path_when_it_cannot_switch(tmp_path, monkeypatch, returncode):
    _fake_viewswap(monkeypatch, returncode)

    assert buttons._show_saved_view(str(tmp_path), "config.yaml", "state.json", echo=False) is False


def test_show_saved_view_gives_up_on_a_panel_that_will_not_answer(tmp_path, monkeypatch, capsys):
    _fake_viewswap(
        monkeypatch, buttons.subprocess.TimeoutExpired(cmd="python", timeout=buttons.FEEDBACK_TIMEOUT_S)
    )

    assert buttons._show_saved_view(str(tmp_path), "config.yaml", "state.json", echo=False) is False
    assert "timed out" in capsys.readouterr().out


def _record_switch(monkeypatch, *, saved_view_shown: bool):
    runs, acks = [], []
    monkeypatch.setattr(buttons, "_show_saved_view", lambda *a, **kw: saved_view_shown)
    monkeypatch.setattr(buttons, "_run_main", lambda *a, **kw: runs.append(kw))
    buttons._switch_view("/opt/inkycal", "config.yaml", "state.json", acks.append, echo=False)
    return runs, acks


def test_switch_view_puts_the_saved_frame_up_then_checks_it_unforced(monkeypatch):
    runs, acks = _record_switch(monkeypatch, saved_view_shown=True)

    # No "please wait" notice: the new view itself is the acknowledgement.
    assert acks == []
    assert runs == [{"toggle_view": False, "force": False}]


def test_switch_view_falls_back_to_a_notice_and_a_forced_toggle(monkeypatch):
    runs, acks = _record_switch(monkeypatch, saved_view_shown=False)

    assert acks == ["Switching view... please wait"]
    assert runs == [{"toggle_view": True}]


# --- button C: setup mode -------------------------------------------------


@pytest.fixture
def setup_files(tmp_path, monkeypatch):
    monkeypatch.setattr(setupmode, "MARKER_PATH", str(tmp_path / "run" / "setup-mode.json"))
    monkeypatch.setattr(setupmode, "REQUEST_PATH", str(tmp_path / "run" / "setup-requested"))
    monkeypatch.setattr(buttons, "SETUP_REQUEST_WAIT_S", 0.3)
    monkeypatch.setattr(buttons, "_SETUP_POLL_S", 0.01)


def test_button_c_asks_the_agent_for_a_session(setup_files, monkeypatch):
    calls = []

    def systemctl(cmd, **_kw):
        calls.append(cmd)
        setupmode.take_request()  # the agent starting up takes it
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(buttons.subprocess, "run", systemctl)

    assert buttons._start_setup_mode(echo=False) is True
    assert calls == [["systemctl", "start", "inkycal-provisioning.service"]]


def test_button_c_tries_once_more_when_the_agent_was_on_its_way_out(setup_files, monkeypatch):
    """`systemctl start` is a no-op on an agent that's still running -- and one
    whose session just ended never reads the request. Starting it again after
    it has gone gets a fresh agent that does."""
    calls = []

    def systemctl(cmd, **_kw):
        calls.append(cmd)
        if len(calls) == 2:
            setupmode.take_request()
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(buttons.subprocess, "run", systemctl)

    assert buttons._start_setup_mode(echo=False) is True
    assert len(calls) == 2


def test_button_c_without_the_agent_installed_says_so_and_leaves_nothing_behind(setup_files, monkeypatch, capsys):
    monkeypatch.setattr(
        buttons.subprocess,
        "run",
        lambda cmd, **_kw: SimpleNamespace(returncode=5, stderr="Unit inkycal-provisioning.service not found."),
    )

    assert buttons._start_setup_mode(echo=False) is False
    assert "install_provisioning.sh" in capsys.readouterr().out
    assert setupmode.request_pending() is False, "a stale request would start setup mode at some later boot"


def test_button_c_gives_up_cleanly_when_no_agent_takes_the_request(setup_files, monkeypatch, capsys):
    monkeypatch.setattr(buttons.subprocess, "run", lambda cmd, **_kw: SimpleNamespace(returncode=0, stderr=""))

    assert buttons._start_setup_mode(echo=False) is False
    assert setupmode.request_pending() is False
    assert "journalctl" in capsys.readouterr().out


def test_leaving_setup_mode_stops_the_agent_and_frees_the_panel(setup_files, monkeypatch):
    calls = []
    monkeypatch.setattr(buttons.subprocess, "run", lambda cmd, **_kw: calls.append(cmd) or SimpleNamespace(returncode=0))
    setupmode.mark_active(600)

    buttons._leave_setup_mode(echo=False)

    assert calls == [["systemctl", "stop", "inkycal-provisioning.service"]]
    assert setupmode.is_active() is False


# --- buttons C and D: act only once held ------------------------------------


def _hold_to_act(acted, **kwargs):
    return buttons._HoldToAct(
        "Button C (setup)", "turn on setup mode", lambda: acted.append("acted"), echo=False, **kwargs
    )


def test_a_hold_button_ignores_a_tap_and_says_how_to_use_it(capsys):
    acted = []
    hold = _hold_to_act(acted)

    hold.pressed()
    hold.released()

    assert acted == []
    out = capsys.readouterr().out
    assert "Button C (setup) let go too soon" in out
    assert f"hold it for {setupmode.HOLD_SECONDS} seconds to turn on setup mode" in out


def test_a_hold_button_acts_once_held_and_not_again_on_release(capsys):
    acted = []
    hold = _hold_to_act(acted)

    hold.pressed()
    hold.held()
    hold.released()

    assert acted == ["acted"]
    assert "let go too soon" not in capsys.readouterr().out


def test_a_hold_button_starts_over_on_every_press(capsys):
    acted = []
    hold = _hold_to_act(acted)

    hold.pressed()
    hold.held()
    hold.released()
    hold.pressed()
    hold.released()

    assert acted == ["acted"]
    assert "let go too soon" in capsys.readouterr().out


def test_a_press_claimed_as_it_goes_down_is_not_acted_on_again_when_held(capsys):
    acted = []
    hold = _hold_to_act(acted, on_press=lambda: True)

    hold.pressed()
    hold.held()
    hold.released()

    assert acted == []
    assert "let go too soon" not in capsys.readouterr().out


class _FakeButton:
    """Stands in for gpiozero.Button: records how it was made, and can be tapped or held."""

    def __init__(self, pin, **kwargs):
        self.pin = pin
        self.kwargs = kwargs
        self.when_pressed = None
        self.when_held = None
        self.when_released = None

    def _fire(self, *handlers):
        for handler in handlers:
            if handler is not None:
                handler()

    def tap(self):
        self._fire(self.when_pressed, self.when_released)

    def hold(self):
        self._fire(self.when_pressed, self.when_held, self.when_released)


@pytest.fixture
def wired_buttons(tmp_path, monkeypatch, setup_files):
    """Run buttons.main() against fake buttons; return them by board label, and what they did."""
    import signal
    import sys

    made = {}

    def make(pin, **kwargs):
        made[pin] = _FakeButton(pin, **kwargs)
        return made[pin]

    config_path = tmp_path / "config.yaml"
    config_path.write_text("timezone: 'America/Phoenix'\nbuttons:\n  echo_to_terminals: false\n", encoding="utf-8")
    monkeypatch.setenv("INKYCAL_CONFIG", str(config_path))
    monkeypatch.setenv("INKYCAL_STATE", str(tmp_path / "state.json"))
    monkeypatch.setitem(sys.modules, "gpiozero", SimpleNamespace(Button=make))
    monkeypatch.setattr(signal, "pause", lambda: None)

    did = []
    monkeypatch.setattr(buttons, "_run_guarded", lambda label, action, *, echo: action())
    monkeypatch.setattr(buttons, "_show_feedback", lambda *a, **kw: None)
    monkeypatch.setattr(buttons, "_switch_view", lambda *a, **kw: did.append("switch view"))
    monkeypatch.setattr(buttons, "_run_main", lambda *a, **kw: did.append("render"))
    monkeypatch.setattr(buttons, "_start_setup_mode", lambda *, echo: did.append("setup mode"))
    monkeypatch.setattr(buttons, "_leave_setup_mode", lambda *, echo: did.append("leave setup mode"))
    monkeypatch.setattr(buttons, "_trigger_force_update", lambda state_path: did.append("update") or False)

    buttons.main()

    by_label = {label: made[pin] for label, pin in zip("ABCD", (5, 6, 25, 24))}
    return by_label, did


def test_c_and_d_are_made_to_wait_for_a_hold_and_a_and_b_are_not(wired_buttons):
    by_label, _did = wired_buttons

    assert by_label["C"].kwargs["hold_time"] == setupmode.HOLD_SECONDS
    assert by_label["D"].kwargs["hold_time"] == setupmode.HOLD_SECONDS
    assert "hold_time" not in by_label["A"].kwargs
    assert "hold_time" not in by_label["B"].kwargs


def test_a_tap_on_c_or_d_does_nothing(wired_buttons):
    by_label, did = wired_buttons

    by_label["C"].tap()
    by_label["D"].tap()

    assert did == []


def test_holding_c_turns_on_setup_mode_and_holding_d_checks_for_updates(wired_buttons):
    by_label, did = wired_buttons

    by_label["C"].hold()
    by_label["D"].hold()

    assert did == ["setup mode", "update"]


def test_a_and_b_still_act_on_a_tap(wired_buttons):
    by_label, did = wired_buttons

    by_label["A"].tap()
    by_label["B"].tap()

    assert did == ["switch view", "render"]


def test_a_tap_on_d_still_leaves_setup_mode_and_holding_it_does_not_also_update(wired_buttons):
    """Getting back to the calendar is a tap on A, B or D, as it always was.
    Someone who holds D down to do that must not get an update check as well."""
    by_label, did = wired_buttons
    setupmode.mark_active(600)

    by_label["D"].tap()
    by_label["D"].hold()

    assert did == ["leave setup mode", "leave setup mode"]
