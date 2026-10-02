"""High-level provisioning workflow shared by the GUI and the CLI.

Connection priority, per the product requirement, is **WiFi first, then
Bluetooth**: we try to find an already-online Pi over mDNS, and only fall
back to BLE (to set up WiFi) when nothing answers on the network.

The InkyCal only listens while setup mode is on (button C, or by itself
before it has WiFi or a Google token), and every change has to carry the
one-time setup code its screen shows.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Optional

from . import ble_client, discovery, google_oauth, pi_client
from .discovery import PiDevice
from .protocol import CODE_DIGITS

Logger = Callable[[str], None]

NO_CODE_HINT = (
    f"Enter the {CODE_DIGITS}-digit setup code shown on the InkyCal's screen. "
    "If the screen isn't showing one, press button C on the InkyCal."
)


def _noop(_msg: str) -> None:
    pass


def normalize_setup_code(raw: str) -> Optional[str]:
    """The setup code as the Pi expects it, or None if `raw` isn't one.

    The screen shows it as "482 913", so a space -- or a dash -- is fine.
    """
    cleaned = (raw or "").replace(" ", "").replace("-", "")
    if len(cleaned) == CODE_DIGITS and cleaned.isascii() and cleaned.isdigit():
        return cleaned
    return None


def find_on_wifi(timeout: float = 5.0, log: Logger = _noop) -> Optional[PiDevice]:
    log("Searching for InkyCal on WiFi (mDNS)…")
    devices = discovery.discover(timeout=timeout)
    for dev in devices:
        if pi_client.reachable(dev):
            log(f"Found {dev.name} at {dev.host}.")
            return dev
    log("No InkyCal found on WiFi.")
    return None


def scan_bluetooth(timeout: float = 8.0, log: Logger = _noop) -> List[ble_client.BleDevice]:
    log("Scanning for InkyCal over Bluetooth…")
    devices = asyncio.run(ble_client.scan(timeout=timeout))
    if devices:
        log(f"Found {len(devices)} InkyCal device(s) over Bluetooth.")
    else:
        log("No InkyCal found over Bluetooth.")
    return devices


def provision_wifi_over_ble(
    ble_address: str,
    ssid: str,
    psk: str,
    setup_code: str,
    log: Logger = _noop,
) -> PiDevice:
    """Push WiFi creds over BLE, then locate the Pi on WiFi. Returns the device."""
    log(f"Sending WiFi credentials for '{ssid}' over Bluetooth…")
    status = asyncio.run(ble_client.provision_wifi(ble_address, ssid, psk, setup_code))
    ip = status.get("ip")
    log(f"Pi reports it joined WiFi (IP {ip}).")

    # Prefer the IP the Pi just told us; verify it answers the HTTP API.
    if ip:
        candidate = PiDevice(name="inkycal", host=ip, port=discovery.HTTP_PORT)
        if _wait_reachable(candidate, log=log):
            return candidate

    # Otherwise fall back to mDNS discovery (DHCP may hand a different IP).
    log("Re-discovering the Pi on WiFi…")
    for _ in range(6):
        dev = find_on_wifi(timeout=4.0, log=log)
        if dev:
            return dev
        time.sleep(2)
    raise RuntimeError(
        "WiFi credentials were sent, but the Pi did not reappear on the network. "
        "Confirm the SSID/password and that this computer is on the same WiFi."
    )


def _wait_reachable(device: PiDevice, attempts: int = 8, log: Logger = _noop) -> bool:
    log(f"Waiting for {device.host} to come online…")
    for _ in range(attempts):
        if pi_client.reachable(device):
            log(f"{device.host} is reachable.")
            return True
        time.sleep(2)
    return False


def run_google_signin(credentials_path: str, log: Logger = _noop) -> str:
    log("Opening Google sign-in in your browser…")
    err = google_oauth.validate_credentials_file(credentials_path)
    if err:
        raise google_oauth.OAuthError(f"Client secrets problem: {err}")
    token = google_oauth.run_oauth(credentials_path)
    log("Google authorization complete.")
    return token


def upload_token(
    device: PiDevice,
    token_json: str,
    setup_code: str,
    log: Logger = _noop,
) -> dict:
    log(f"Uploading token to {device.host}…")
    client = pi_client.PiClient(device, setup_code=setup_code)
    result = client.upload_token(token_json)
    log("Token delivered. Setup mode ends and the InkyCal display will refresh shortly.")
    return result
