"""Command-line companion: discover the Pi, set up WiFi, deliver the token.

Useful as a headless fallback and for debugging. The GUI is the default
entry point; this is invoked with ``inkycal-companion --cli``.
"""
from __future__ import annotations

import argparse
import sys

from . import workflow
from .discovery import PiDevice, HTTP_PORT

NOT_FOUND_HINT = "Hold down button C on the InkyCal for 3 seconds to turn on setup mode, then try again."


def _log(msg: str) -> None:
    print(msg, flush=True)


def _setup_code(given: str) -> str | None:
    """The setup code from --setup-code, or asked for when run interactively."""
    if given:
        code = workflow.normalize_setup_code(given)
        if code is None:
            _log(f"ERROR: '{given}' is not a setup code. {workflow.NO_CODE_HINT}")
        return code
    if not sys.stdin.isatty():
        _log(f"ERROR: no --setup-code given. {workflow.NO_CODE_HINT}")
        return None
    for _ in range(3):
        code = workflow.normalize_setup_code(input("Setup code shown on the InkyCal's screen: "))
        if code:
            return code
        _log(f"That isn't a setup code. {workflow.NO_CODE_HINT}")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="inkycal-companion",
        description="Set up Google Calendar auth on an InkyCal Raspberry Pi.",
    )
    parser.add_argument("--credentials", required=True,
                        help="Path to Google OAuth client-secrets JSON.")
    parser.add_argument("--ssid", help="WiFi SSID to provision over Bluetooth (if the Pi is offline).")
    parser.add_argument("--psk", default="", help="WiFi passphrase for --ssid.")
    parser.add_argument("--host", help="Skip discovery; use this Pi IP/hostname directly.")
    parser.add_argument("--port", type=int, default=HTTP_PORT)
    parser.add_argument("--setup-code", "--pairing-token", dest="setup_code", default="",
                        help="The setup code on the InkyCal's screen (hold down button C to show it). "
                             "Asked for if not given.")
    parser.add_argument("--wifi-timeout", type=float, default=5.0)
    parser.add_argument("--bt-timeout", type=float, default=8.0)
    args = parser.parse_args(argv)

    device: PiDevice | None = None
    bt_devices = []

    # 1. Explicit host wins.
    if args.host:
        device = PiDevice(name="inkycal", host=args.host, port=args.port)

    # 2. WiFi discovery (priority 1).
    if device is None:
        device = workflow.find_on_wifi(timeout=args.wifi_timeout, log=_log)

    # 3. Bluetooth fallback to set up WiFi (priority 2).
    if device is None:
        bt_devices = workflow.scan_bluetooth(timeout=args.bt_timeout, log=_log)
        if not bt_devices:
            _log(f"ERROR: Could not find an InkyCal on WiFi or Bluetooth. {NOT_FOUND_HINT}")
            return 2
        if not args.ssid:
            _log("ERROR: Pi found over Bluetooth but no --ssid given to set up WiFi.")
            return 2

    code = _setup_code(args.setup_code)
    if code is None:
        return 2

    if device is None:
        try:
            device = workflow.provision_wifi_over_ble(
                bt_devices[0].address, args.ssid, args.psk, code, log=_log,
            )
        except Exception as exc:
            _log(f"ERROR: WiFi provisioning failed: {exc}")
            return 3

    # 4. Google sign-in.
    try:
        token = workflow.run_google_signin(args.credentials, log=_log)
    except Exception as exc:
        _log(f"ERROR: Google sign-in failed: {exc}")
        return 4

    # 5. Upload token.
    try:
        workflow.upload_token(device, token, code, log=_log)
    except Exception as exc:
        _log(f"ERROR: Uploading token failed: {exc}")
        return 5

    _log("\n✓ All set. Your calendar will appear on the InkyCal shortly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
