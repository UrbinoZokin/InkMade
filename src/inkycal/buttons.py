"""GPIO handler for the Inky Impression's 4 physical buttons.

Runs as a long-lived daemon (see systemd/inkycal-buttons.service, which runs
it as root for unprivileged GPIO access and permission to start other
systemd units). Button presses are cheap triggers only: this process never
touches the display, calendar credentials, or state file directly.

  A (pin_view)    - toggle daily/weekly view, then force a refresh
  B (pin_refresh) - force a refresh
  C (pin_unused)  - reserved, no handler
  D (pin_update)  - force an OTA update check/apply (bypasses apply_window)

Because the display cannot say anything until the fetch behind a press has
finished -- 10-60 s of a completely still panel -- every press that does work
first paints a short "working on it" notice via inkycal.feedback, so you can
see the press landed. See `buttons.press_feedback` in config.yaml to change
its style or turn it off.

Every press is also echoed to the terminals of anyone currently logged in
(SSH sessions and the local console), so you can watch which button someone
pressed without tailing the journal. Set `buttons.echo_to_terminals: false`
in config.yaml to keep presses in the journal only.

For the view-toggle and refresh buttons, this drops privileges to the app
directory's owner and re-runs the normal `inkycal.main` entrypoint, exactly
like the periodic timer does, so the acting user, file ownership, and code
path all match a regular scheduled run. For the update button, it asks systemd
to start the existing update service -- which already runs as root and knows
how to apply an update safely -- waits for it to finish, and then re-renders so
the notice comes back off the panel.
"""
from __future__ import annotations

import glob
import os
import pwd
import subprocess

from dotenv import dotenv_values

from .config import load_config
from .feedback import STYLE_NONE, resolve_style
from .main import CONFIG_PATH_DEFAULT, STATE_PATH_DEFAULT
from .updates import DEFAULT_APP_DIR

# scripts/ota_update.sh looks for this file next to state.json: its presence
# means "apply a pending update now, regardless of apply_window." Using a
# flag file (instead of an env var) means ota_update.sh only needs plain
# `systemctl start`, which is all that's actually supported.
FORCE_UPDATE_FLAG_NAME = "force_update"

# A press-acknowledgement is one full-panel refresh; on the 13.3" Impression
# that is well under a minute. Cap it so a wedged SPI transfer can't hold the
# handler thread (and therefore the actual work) forever.
FEEDBACK_TIMEOUT_S = 180

# The OTA service pulls, reinstalls dependencies and restarts units, so it can
# legitimately run for several minutes. Past this we stop waiting to put the
# display back and leave that to the periodic timer.
UPDATE_TIMEOUT_S = 900


def _app_owner_ids(app_dir: str) -> tuple[int, int]:
    st = os.stat(app_dir)
    return st.st_uid, st.st_gid


def _app_owner_groups(uid: int, gid: int) -> list[int]:
    # subprocess.run(user=, group=) alone does not call setgroups(); without
    # this, the child keeps the daemon's (root's) supplementary groups
    # instead of the app user's real ones (gpio/spi/i2c/video), unlike
    # systemd's own User=/Group= handling used by the periodic timer.
    try:
        username = pwd.getpwuid(uid).pw_name
        return os.getgrouplist(username, gid)
    except (KeyError, OSError):
        return [gid]


def _spawn_env(app_dir: str) -> dict:
    env = dict(os.environ)
    dotenv_path = os.path.join(app_dir, ".env")
    # dotenv_values() maps a bare `KEY` line (no '=') to None; subprocess.run
    # rejects a None env value, so drop anything that isn't a real string.
    env.update({k: v for k, v in dotenv_values(dotenv_path).items() if v is not None})
    return env


def _logged_in_terminals() -> list[str]:
    """Terminal devices of everyone currently logged in.

    Read from utmp via `who`, which covers SSH sessions (/dev/pts/N) and
    anyone on the local console (/dev/ttyN). If `who` is missing or fails,
    fall back to every open pseudo-terminal so a press still shows up.
    """
    devices: list[str] = []
    try:
        result = subprocess.run(["who"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        result = None

    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 2:
                continue
            device = "/dev/" + fields[1]
            if device not in devices:
                devices.append(device)

    if not devices:
        devices = sorted(p for p in glob.glob("/dev/pts/*") if os.path.basename(p).isdigit())
    return devices


def _write_to_terminal(device: str, text: str) -> None:
    # O_NONBLOCK because gpiozero runs every handler on one background
    # thread: a wedged or half-closed terminal must not stall the next
    # press. O_NOCTTY so opening a console never makes it our controlling
    # terminal. The daemon runs as root, so this works regardless of the
    # tty's `mesg` setting (which is what makes `wall` unreliable here).
    fd = os.open(device, os.O_WRONLY | os.O_NONBLOCK | os.O_NOCTTY)
    try:
        os.write(fd, text.encode("utf-8", "replace"))
    finally:
        os.close(fd)


def _broadcast(message: str) -> None:
    # \r\n rather than \n: a terminal in raw mode (an editor, a pager) does
    # not translate a bare newline into a carriage return, which would leave
    # the message stair-stepping across the screen.
    text = f"\r\n[InkyCal] {message}\r\n"
    for device in _logged_in_terminals():
        try:
            _write_to_terminal(device, text)
        except OSError:
            # Logged out between `who` and the write, or not a device we may
            # write to. Nothing to do but skip it.
            continue


def _announce(message: str, *, echo: bool) -> None:
    """Log to the journal, and echo to logged-in terminals when enabled."""
    print(message, flush=True)
    if echo:
        _broadcast(message)


def _run_as_app_user(app_dir: str, module: str, args: list[str], timeout: float | None = None):
    """Run `python -m <module>` from the app's venv as the app directory's owner.

    Matches how the periodic timer runs the same code, so the acting user, file
    ownership and code path are identical to a regular scheduled run.
    """
    uid, gid = _app_owner_ids(app_dir)
    groups = _app_owner_groups(uid, gid)
    venv_python = os.path.join(app_dir, "venv", "bin", "python")
    return subprocess.run(
        [venv_python, "-m", module, *args],
        cwd=app_dir,
        user=uid,
        group=gid,
        extra_groups=groups,
        env=_spawn_env(app_dir),
        check=False,
        timeout=timeout,
    )


def _show_feedback(app_dir: str, config_path: str, state_path: str, message: str, *, echo: bool) -> None:
    """Acknowledge a press on the panel itself, before the slow work starts.

    Never fatal: this is only an acknowledgement, so a display that refuses it
    must not stop the refresh (or update) the user actually asked for.
    """
    try:
        result = _run_as_app_user(
            app_dir,
            "inkycal.feedback",
            ["--config", config_path, "--state", state_path, "--message", message],
            timeout=FEEDBACK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        _announce(f"Press feedback timed out after {FEEDBACK_TIMEOUT_S}s; continuing", echo=echo)
        return
    except Exception as e:
        _announce(f"Press feedback failed: {e}; continuing", echo=echo)
        return
    if result.returncode != 0:
        print(f"inkycal.feedback exited with code {result.returncode}")


def _run_main(app_dir: str, config_path: str, state_path: str, *, toggle_view: bool) -> None:
    args = ["--config", config_path, "--state", state_path, "--force"]
    if toggle_view:
        args.append("--toggle-view")
    result = _run_as_app_user(app_dir, "inkycal.main", args)
    if result.returncode != 0:
        print(f"inkycal.main exited with code {result.returncode}")


def _trigger_force_update(state_path: str) -> bool:
    """Run the update service to completion. True if it finished within the wait.

    Unlike the periodic check this blocks (no --no-block): the display is
    currently showing a "checking for updates" notice, and knowing when the
    check is done is what lets us take that notice back off. Two ways we may
    not see the end of it: the run takes longer than UPDATE_TIMEOUT_S, or it
    applied an update that changed systemd/ and restarted this very daemon
    from under us. Both are covered -- ota_update.sh triggers its own render
    after applying, and the notice clears the stored render hash so the next
    scheduled run repaints regardless.
    """
    flag_path = os.path.join(os.path.dirname(state_path) or ".", FORCE_UPDATE_FLAG_NAME)
    try:
        open(flag_path, "w").close()
    except OSError as e:
        print(f"Could not write force-update flag at {flag_path}: {e}")

    try:
        result = subprocess.run(
            ["systemctl", "start", "inkycal-update.service"],
            check=False,
            timeout=UPDATE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        print(f"inkycal-update.service still running after {UPDATE_TIMEOUT_S}s; not waiting any longer")
        return False
    if result.returncode != 0:
        print(f"systemctl start inkycal-update.service exited with code {result.returncode}")
    return True


def main() -> None:
    from gpiozero import Button
    from signal import pause

    app_dir = os.environ.get("INKYCAL_APP_DIR", DEFAULT_APP_DIR)
    config_path = os.environ.get("INKYCAL_CONFIG", CONFIG_PATH_DEFAULT)
    state_path = os.environ.get("INKYCAL_STATE", STATE_PATH_DEFAULT)

    cfg = load_config(config_path)
    buttons_cfg = cfg.buttons
    if not buttons_cfg.enabled:
        print("Buttons disabled in config.yaml (buttons.enabled: false); exiting.")
        return

    bounce_time = buttons_cfg.bounce_time_ms / 1000
    echo = buttons_cfg.echo_to_terminals
    # Resolved once here so a press with feedback turned off doesn't pay for a
    # process spawn just to have it decide there is nothing to draw.
    feedback_style = resolve_style(buttons_cfg.press_feedback)
    feedback_on = feedback_style != STYLE_NONE

    def acknowledge(message: str) -> None:
        if feedback_on:
            _show_feedback(app_dir, config_path, state_path, message, echo=echo)

    btn_view = Button(buttons_cfg.pin_view, pull_up=True, bounce_time=bounce_time)
    btn_refresh = Button(buttons_cfg.pin_refresh, pull_up=True, bounce_time=bounce_time)
    btn_unused = Button(buttons_cfg.pin_unused, pull_up=True, bounce_time=bounce_time)
    btn_update = Button(buttons_cfg.pin_update, pull_up=True, bounce_time=bounce_time)

    def on_view_pressed() -> None:
        _announce("Button A (view) pressed: toggling daily/weekly view", echo=echo)
        try:
            acknowledge("Switching view...")
            _run_main(app_dir, config_path, state_path, toggle_view=True)
        except Exception as e:
            _announce(f"View toggle failed: {e}", echo=echo)

    def on_refresh_pressed() -> None:
        _announce("Button B (refresh) pressed: forcing a display refresh", echo=echo)
        try:
            acknowledge("Refreshing...")
            _run_main(app_dir, config_path, state_path, toggle_view=False)
        except Exception as e:
            _announce(f"Forced refresh failed: {e}", echo=echo)

    def on_unused_pressed() -> None:
        # No work follows, so nothing to acknowledge on the panel: a notice
        # here would spend a full refresh saying "nothing happened".
        _announce("Button C pressed: no function assigned", echo=echo)

    def on_update_pressed() -> None:
        _announce("Button D (update) pressed: forcing an update check/apply", echo=echo)
        try:
            acknowledge("Checking for updates...")
            finished = _trigger_force_update(state_path)
            # The update itself changes nothing on screen unless it applied one
            # (ota_update.sh renders after that). Either way, re-render so the
            # notice is replaced -- by the schedule, now including whether an
            # update is still pending.
            if finished:
                _run_main(app_dir, config_path, state_path, toggle_view=False)
        except Exception as e:
            _announce(f"Forced update trigger failed: {e}", echo=echo)

    btn_view.when_pressed = on_view_pressed
    btn_refresh.when_pressed = on_refresh_pressed
    btn_unused.when_pressed = on_unused_pressed
    btn_update.when_pressed = on_update_pressed

    print(
        "InkyCal buttons ready: "
        f"A=GPIO{buttons_cfg.pin_view} (view) "
        f"B=GPIO{buttons_cfg.pin_refresh} (refresh) "
        f"C=GPIO{buttons_cfg.pin_unused} (unused) "
        f"D=GPIO{buttons_cfg.pin_update} (update); "
        f"echo to logged-in terminals {'on' if echo else 'off'}; "
        f"press feedback {feedback_style}"
    )
    pause()


if __name__ == "__main__":
    main()
