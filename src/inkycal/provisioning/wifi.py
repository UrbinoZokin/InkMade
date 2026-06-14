"""WiFi configuration and status helpers for the provisioning agent.

Raspberry Pi OS Bookworm manages WiFi through NetworkManager, so we drive
``nmcli``. All functions are defensive: they never raise on a missing tool
or a failed command, they return structured results the caller can act on.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
from typing import Optional, TypedDict


class WifiStatus(TypedDict):
    connected: bool
    ssid: Optional[str]
    ip: Optional[str]
    hostname: str


def _nmcli_available() -> bool:
    return shutil.which("nmcli") is not None


def _run(cmd: list[str], timeout: int = 45) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def current_ssid() -> Optional[str]:
    if not _nmcli_available():
        return None
    try:
        proc = _run(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"], timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in proc.stdout.splitlines():
        # Format: "yes:MyNetwork" or "no:OtherNetwork"
        active, _, ssid = line.partition(":")
        if active == "yes" and ssid:
            return ssid
    return None


def primary_ip() -> Optional[str]:
    """Best-effort LAN IP of this host (the route used to reach the internet)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # No packets are actually sent for a UDP connect.
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def status() -> WifiStatus:
    ssid = current_ssid()
    ip = primary_ip()
    return WifiStatus(
        connected=bool(ip) and not str(ip).startswith("127."),
        ssid=ssid,
        ip=ip,
        hostname=socket.gethostname(),
    )


def configure_wifi(ssid: str, psk: str, timeout: int = 60) -> tuple[bool, str]:
    """Join ``ssid`` using ``psk``. Returns ``(ok, message)``.

    Uses ``nmcli device wifi connect`` which creates/updates a saved
    connection profile so the Pi reconnects automatically on reboot.
    """
    ssid = (ssid or "").strip()
    if not ssid:
        return False, "Empty SSID"
    if not _nmcli_available():
        return False, "nmcli not available on this device"

    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if psk:
        cmd += ["password", psk]
    try:
        proc = _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Timed out joining network"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"nmcli error: {exc}"

    if proc.returncode == 0:
        return True, proc.stdout.strip() or "Connected"

    message = (proc.stderr or proc.stdout).strip() or "Unknown nmcli failure"
    return False, message
