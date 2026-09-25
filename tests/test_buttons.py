import os
import threading
from types import SimpleNamespace

import pytest

from inkycal import buttons, viewswap


def test_app_owner_ids_matches_directory_stat(tmp_path):
    st = os.stat(tmp_path)

    uid, gid = buttons._app_owner_ids(str(tmp_path))

    assert (uid, gid) == (st.st_uid, st.st_gid)


def test_app_owner_groups_falls_back_to_gid_on_lookup_failure(monkeypatch):
    monkeypatch.setattr(buttons.pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError(uid)))

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
