"""GPIO handler for the Inky Impression's 4 physical buttons.

Runs as a long-lived daemon (see systemd/inkycal-buttons.service, which runs
it as root for unprivileged GPIO access and permission to start other
systemd units). Button presses are cheap triggers only: this process never
touches the display, calendar credentials, or state file directly.

  A (pin_view)    - toggle daily/weekly view, then force a refresh
  B (pin_refresh) - force a refresh
  C (pin_unused)  - reserved, no handler
  D (pin_update)  - force an OTA update check/apply (bypasses apply_window)

For the view-toggle and refresh buttons, this drops privileges to the app
directory's owner and re-runs the normal `inkycal.main` entrypoint, exactly
like the periodic timer does, so the acting user, file ownership, and code
path all match a regular scheduled run. For the update button, it just asks
systemd to start the existing update service, which already runs as root and
knows how to apply an update safely.
"""
from __future__ import annotations

import os
import pwd
import subprocess

from dotenv import dotenv_values

from .config import load_config
from .main import CONFIG_PATH_DEFAULT, STATE_PATH_DEFAULT
from .updates import DEFAULT_APP_DIR

# scripts/ota_update.sh looks for this file next to state.json: its presence
# means "apply a pending update now, regardless of apply_window." Using a
# flag file (instead of an env var) means ota_update.sh only needs plain
# `systemctl start`, which is all that's actually supported.
FORCE_UPDATE_FLAG_NAME = "force_update"


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


def _run_main(app_dir: str, config_path: str, state_path: str, *, toggle_view: bool) -> None:
    uid, gid = _app_owner_ids(app_dir)
    groups = _app_owner_groups(uid, gid)
    venv_python = os.path.join(app_dir, "venv", "bin", "python")
    cmd = [venv_python, "-m", "inkycal.main", "--config", config_path, "--state", state_path, "--force"]
    if toggle_view:
        cmd.append("--toggle-view")
    result = subprocess.run(
        cmd, cwd=app_dir, user=uid, group=gid, extra_groups=groups, env=_spawn_env(app_dir), check=False
    )
    if result.returncode != 0:
        print(f"inkycal.main exited with code {result.returncode}")


def _trigger_force_update(state_path: str) -> None:
    flag_path = os.path.join(os.path.dirname(state_path) or ".", FORCE_UPDATE_FLAG_NAME)
    try:
        open(flag_path, "w").close()
    except OSError as e:
        print(f"Could not write force-update flag at {flag_path}: {e}")

    result = subprocess.run(
        ["systemctl", "start", "--no-block", "inkycal-update.service"],
        check=False,
    )
    if result.returncode != 0:
        print(f"systemctl start inkycal-update.service exited with code {result.returncode}")


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

    btn_view = Button(buttons_cfg.pin_view, pull_up=True, bounce_time=bounce_time)
    btn_refresh = Button(buttons_cfg.pin_refresh, pull_up=True, bounce_time=bounce_time)
    btn_unused = Button(buttons_cfg.pin_unused, pull_up=True, bounce_time=bounce_time)
    btn_update = Button(buttons_cfg.pin_update, pull_up=True, bounce_time=bounce_time)

    def on_view_pressed() -> None:
        print("Button A (view) pressed: toggling daily/weekly view")
        try:
            _run_main(app_dir, config_path, state_path, toggle_view=True)
        except Exception as e:
            print(f"View toggle failed: {e}")

    def on_refresh_pressed() -> None:
        print("Button B (refresh) pressed: forcing a display refresh")
        try:
            _run_main(app_dir, config_path, state_path, toggle_view=False)
        except Exception as e:
            print(f"Forced refresh failed: {e}")

    def on_unused_pressed() -> None:
        print("Button C pressed: unused")

    def on_update_pressed() -> None:
        print("Button D (update) pressed: forcing an update check/apply")
        try:
            _trigger_force_update(state_path)
        except Exception as e:
            print(f"Forced update trigger failed: {e}")

    btn_view.when_pressed = on_view_pressed
    btn_refresh.when_pressed = on_refresh_pressed
    btn_unused.when_pressed = on_unused_pressed
    btn_update.when_pressed = on_update_pressed

    print(
        "InkyCal buttons ready: "
        f"A=GPIO{buttons_cfg.pin_view} (view) "
        f"B=GPIO{buttons_cfg.pin_refresh} (refresh) "
        f"C=GPIO{buttons_cfg.pin_unused} (unused) "
        f"D=GPIO{buttons_cfg.pin_update} (update)"
    )
    pause()


if __name__ == "__main__":
    main()
