"""Setup mode: the few minutes in which the InkyCal can be reconfigured.

The provisioning agent (inkycal.provisioning) takes a new Google token or WiFi
network from the companion app. It used to listen all the time -- an HTTP API
on every network interface and a Bluetooth advertisement, run as root, open to
anyone who could reach them. Now it only runs while setup mode is on: after
button C, or while the device has no Google token or WiFi network yet. Every
change it accepts has to carry a one-time code that only the panel shows, and
it stops listening after a few minutes.

This module is the little state the rest of the program shares with that
window. It lives in /run, which is RAM: a reboot always ends setup mode.

  - The marker exists for as long as a session runs. While it is there the
    panel belongs to setup mode, and every other paint is turned away (see
    display_inky.show_on_inky), so the code stays readable until it's used.
  - The request flag is how button C asks the agent for a session, or for
    more time on the one already running.

Neither file holds the code. It only ever lives in the agent's memory and on
the panel.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

# How long a session lasts, and how much more time each hold of C gives it.
SESSION_MINUTES = 10

# How long C has to be held down before it does anything (D too; see
# inkycal.buttons). Setup mode replaces the calendar with a code for someone
# who isn't there to read it, so a passing tap must not start it.
HOLD_SECONDS = 3

# /run is a tmpfs: nothing here outlives a reboot, so a session cut short by a
# power cut can never leave the panel held for one that no longer exists.
MARKER_PATH = os.environ.get("INKYCAL_SETUP_MARKER", "/run/inkycal/setup-mode.json")
REQUEST_PATH = os.environ.get("INKYCAL_SETUP_REQUEST", "/run/inkycal/setup-requested")


class SetupModeActive(RuntimeError):
    """The panel is showing the setup code, so this paint has to wait."""


def mark_active(seconds_left: float, path: Optional[str] = None) -> None:
    """Record that a session holds the panel for up to `seconds_left` more seconds.

    The deadline is kept on the monotonic clock, not the wall clock. The Pi has
    no battery-backed RTC, so at power-on -- exactly when a first-time setup
    session starts -- the wall clock can be hours behind until NTP corrects it,
    and a deadline written before that jump would expire the moment it landed,
    letting the boot refresh paint straight over the code. The monotonic clock
    is shared by every process and only resets at reboot, along with /run.
    """
    path = path if path is not None else MARKER_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    body = json.dumps({"pid": os.getpid(), "until_monotonic": time.monotonic() + seconds_left})
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)


def clear(path: Optional[str] = None) -> None:
    try:
        os.unlink(path if path is not None else MARKER_PATH)
    except FileNotFoundError:
        pass


def is_active(path: Optional[str] = None) -> bool:
    """Whether a setup session holds the panel right now.

    Never raises: this is asked under the display lock before every paint, and
    a marker that can't be read must not cost the calendar its refresh. Only a
    marker from a live agent whose deadline hasn't passed counts, so an agent
    that died without cleaning up releases the panel at once rather than at its
    deadline.
    """
    try:
        with open(path if path is not None else MARKER_PATH, encoding="utf-8") as f:
            data = json.load(f)
        pid = int(data["pid"])
        until = float(data["until_monotonic"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return time.monotonic() < until and _alive(pid)


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists; it just isn't ours to signal. The agent runs as root and
        # the render that asks runs as the app user, so this is the usual case.
        return True
    except OSError:
        return False
    return True


def request(path: Optional[str] = None) -> None:
    """Ask the agent for a setup session, or for more time on the running one."""
    path = path if path is not None else REQUEST_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8"):
        pass


def take_request(path: Optional[str] = None) -> bool:
    """Consume a pending request. True if there was one."""
    try:
        os.unlink(path if path is not None else REQUEST_PATH)
    except FileNotFoundError:
        return False
    return True


def request_pending(path: Optional[str] = None) -> bool:
    return os.path.exists(path if path is not None else REQUEST_PATH)
