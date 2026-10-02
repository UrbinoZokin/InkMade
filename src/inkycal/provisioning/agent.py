"""InkyCal provisioning agent: setup mode.

Runs on the Pi only while setup mode is on, and exits when it ends. Setup mode
starts when button C asks for it (see inkycal.buttons), or by itself while the
device has no Google token or WiFi network to use yet. While it runs, the
agent exposes two transports so the companion app can configure the device:

  * Bluetooth LE  -- used to set up WiFi the first time.
  * WiFi / HTTP   -- available once the Pi is on the network; faster, and
                     used to deliver the Google OAuth token.

Each session gets a fresh one-time code, shown only on the panel
(inkycal.setupscreen), and both transports refuse any change that doesn't
carry it. That is what takes the place of a permanently open, root-run API:
outside a session nothing is listening at all, and inside one, changing the
device means being able to see its screen.

A session ends when its SESSION_MINUTES are up (each press of C restarts the
clock), when the Google token arrives, after MAX_WRONG_CODES wrong codes, or
when the agent is stopped -- which is how buttons A, B and D end it. However
it ends, the calendar is repainted over the code.

The agent re-checks WiFi periodically and (re)starts the mDNS advertisement
when the Pi comes online -- e.g. right after the app provisions WiFi over
Bluetooth -- so the app can seamlessly switch to the WiFi path.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Optional

from .. import appuser, setupmode
from ..config import CONFIG_PATH_DEFAULT, load_config
from ..state import STATE_PATH_DEFAULT
from ..updates import DEFAULT_APP_DIR
from . import tokenstore, wifi
from .ble import BleProvisioner
from .httpserver import info_payload, serve
from .mdns import MdnsAdvertiser
from .protocol import HTTP_PORT
from .session import SESSION_MINUTES, SetupSession

APP_DIR = os.environ.get("INKYCAL_APP_DIR", DEFAULT_APP_DIR)
CONFIG_PATH = os.environ.get("INKYCAL_CONFIG", CONFIG_PATH_DEFAULT)
STATE_PATH = os.environ.get("INKYCAL_STATE", STATE_PATH_DEFAULT)

# How often the session loop looks for button C and for its own end, and how
# often it re-checks WiFi for the mDNS advertisement.
POLL_S = 1.0
WIFI_CHECK_S = 15.0

# One full-panel refresh, with room to wait out a render holding the panel.
SCREEN_TIMEOUT_S = 240

# Tried in order to put the calendar back when a session ends.
# inkycal-boot.service is the "repaint now, whatever is on screen" unit: it
# forces the refresh even inside the overnight sleep window, where an ordinary
# run would leave the code up until morning.
RESTORE_UNITS = ("inkycal-boot.service", "inkycal.service")


def _device_id() -> str:
    return info_payload().get("id", "pi")


def _google_enabled() -> bool:
    try:
        return bool(load_config(CONFIG_PATH).google.enabled)
    except Exception:  # missing or unreadable config: the default is enabled
        return True


def setup_needed() -> Optional[str]:
    """Why this device has to be set up before it can show anything, or None."""
    if _google_enabled() and not tokenstore.token_present():
        return "no Google token yet"
    if not wifi.status()["connected"] and not wifi.has_saved_wifi_connection():
        return "no WiFi network set up yet"
    return None


def _screen_env() -> dict:
    # Only what drawing needs. The agent's own environment carries .env --
    # calendar passwords included -- and none of that belongs in a child that
    # only paints the panel.
    keep = ("PATH", "LANG", "LC_ALL", "TZ")
    return {k: v for k, v in os.environ.items() if k in keep or k.startswith("INKYCAL_")}


def _show_code(session: SetupSession, address: Optional[str]) -> None:
    """Paint the session's code on the panel, as the app user. Never raises."""
    try:
        result = appuser.run_module(
            APP_DIR,
            "inkycal.setupscreen",
            [
                "--config", CONFIG_PATH,
                "--state", STATE_PATH,
                "--minutes", str(SESSION_MINUTES),
                "--address", address or "",
            ],
            env=_screen_env(),
            input=session.code + "\n",
            timeout=SCREEN_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        print(f"[agent] the setup screen took longer than {SCREEN_TIMEOUT_S}s to draw")
        return
    except Exception as exc:
        print(f"[agent] could not draw the setup screen: {exc}")
        return
    if result.returncode != 0:
        print(f"[agent] inkycal.setupscreen exited with code {result.returncode}")


def _restore_calendar() -> bool:
    """Repaint the calendar over the setup code. Best effort; never raises.

    --no-block, so a slow repaint doesn't hold the agent open. If no unit will
    start, the setup screen cleared the render hash, so the next scheduled
    render repaints regardless.
    """
    for unit in RESTORE_UNITS:
        try:
            proc = subprocess.run(
                ["systemctl", "start", "--no-block", unit],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return True
    print("[agent] could not start a repaint; the next scheduled render will put the calendar back")
    return False


def _hold_panel(session: SetupSession) -> None:
    """Keep every other paint off the panel for the rest of the session.

    The slack only matters if this process hangs: the marker stops counting on
    its own soon after the session would have ended.
    """
    try:
        setupmode.mark_active(session.seconds_left() + 60)
    except OSError as exc:
        print(f"[agent] could not mark setup mode as on ({exc}); a render may paint over the code")


def serve_session(session: SetupSession, reason: str, stop: threading.Event) -> None:
    """Run one setup session until it ends or `stop` is set, then tear it down."""
    print(f"[agent] setup mode on ({reason}); it switches off after {SESSION_MINUTES} minutes")
    # Before anything else, so no render starting from here on paints over the code.
    _hold_panel(session)

    httpd = None
    mdns: Optional[MdnsAdvertiser] = None
    try:
        try:
            httpd = serve(session, HTTP_PORT)
        except OSError as exc:
            # Bluetooth can still carry the session; don't crash-loop over a port.
            print(f"[http] could not listen on :{HTTP_PORT}: {exc}")
        BleProvisioner(info_provider=info_payload, session=session).start()
        mdns = MdnsAdvertiser(port=HTTP_PORT, device_id=_device_id())
        advertised_ip: Optional[str] = None

        st = wifi.status()
        threading.Thread(
            target=_show_code,
            args=(session, st["ip"] if st["connected"] else None),
            name="inkycal-setup-screen",
            daemon=True,
        ).start()

        next_wifi_check = 0.0
        while not stop.is_set() and not session.ended:
            if setupmode.take_request():
                if session.extend():
                    _hold_panel(session)
                    print(f"[agent] button C: setup mode switches off {SESSION_MINUTES} minutes from now")
                else:
                    # It ended as the press landed. Leave the request for the
                    # button handler, which starts a fresh agent once this one
                    # has gone.
                    setupmode.request()
            now = time.monotonic()
            if now >= next_wifi_check:
                st = wifi.status()
                ip = st["ip"] if st["connected"] else None
                if ip != advertised_ip:
                    mdns.stop()
                    if ip:
                        mdns.start(ip)
                    advertised_ip = ip
                next_wifi_check = now + WIFI_CHECK_S
            stop.wait(POLL_S)
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if mdns is not None:
            mdns.stop()
        setupmode.clear()
        print(f"[agent] setup mode off ({session.end_reason or 'stopped'})")
        _restore_calendar()


def run(stop: Optional[threading.Event] = None) -> int:
    print("== InkyCal provisioning agent ==")
    if stop is None:
        stop = threading.Event()

        def _shutdown(*_args) -> None:
            print("\n[agent] shutting down")
            stop.set()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

    # Only one agent runs at a time, so a marker already here was left by one
    # that died mid-session. Its code is dead, and may still be on the panel.
    abandoned = os.path.exists(setupmode.MARKER_PATH)
    setupmode.clear()

    reason = "button C" if setupmode.take_request() else setup_needed()
    if not reason:
        if abandoned:
            _restore_calendar()
        print("[agent] this InkyCal is set up; setup mode stays off until button C is pressed")
        return 0

    serve_session(SetupSession(), reason, stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
