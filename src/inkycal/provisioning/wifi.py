"""WiFi configuration and status helpers for the provisioning agent.

Raspberry Pi OS Bookworm manages WiFi through NetworkManager, so we drive
``nmcli``. All functions are defensive: they never raise on a missing tool
or a failed command, they return structured results the caller can act on.
"""
from __future__ import annotations

import re
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


def has_saved_wifi_connection() -> bool:
    """Whether NetworkManager has a WiFi network saved to join, connected or not.

    Errs towards True: when nmcli can't answer, this device's WiFi isn't
    managed by NetworkManager at all, and the Bluetooth path -- which drives
    nmcli -- couldn't set it up anyway.
    """
    if not _nmcli_available():
        return True
    try:
        proc = _run(["nmcli", "-t", "-f", "TYPE", "connection", "show"], timeout=10)
    except (OSError, subprocess.SubprocessError):
        return True
    if proc.returncode != 0:
        return True
    # Terse output names the type by its setting ("802-11-wireless"); accept
    # the short alias too, which some nmcli versions print instead.
    return any(line.strip() in ("802-11-wireless", "wifi") for line in proc.stdout.splitlines())


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

    message = _output(proc)
    if psk and "key-mgmt" in message:
        # `device wifi connect` takes the network's security type from the
        # Pi's last scan. When the scan doesn't describe it, the profile gets
        # the password but no security type, and NetworkManager refuses it
        # ("802-11-wireless-security.key-mgmt: property is missing"). Name the
        # type ourselves: "wpa-psk" covers WPA2 and mixed WPA2/WPA3 networks.
        return _join_wpa_psk(ssid, psk, timeout)
    return False, _explain(ssid, psk, message)


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _join_wpa_psk(ssid: str, psk: str, timeout: int) -> tuple[bool, str]:
    """Save a WPA2 profile for ``ssid`` without consulting the scan, then join it."""
    add = ["nmcli", "connection", "add", "type", "wifi", "con-name", ssid, "ssid", ssid]
    add += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", psk]
    try:
        added = _run(add, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"nmcli error: {exc}"
    found = _UUID.search(added.stdout or "")
    if added.returncode != 0 or not found:
        return False, _explain(ssid, psk, _output(added))
    uuid = found.group(0)

    try:
        up = _run(["nmcli", "--wait", str(timeout), "connection", "up", "uuid", uuid], timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        _forget(uuid)
        return False, "Timed out joining network"
    except (OSError, subprocess.SubprocessError) as exc:
        _forget(uuid)
        return False, f"nmcli error: {exc}"
    if up.returncode == 0:
        return True, up.stdout.strip() or "Connected"
    _forget(uuid)
    return False, _explain(ssid, psk, _output(up))


def _forget(uuid: str) -> None:
    """Delete a profile that never joined. Left saved, it would count as WiFi
    being set up, and the next boot would skip setup mode."""
    try:
        _run(["nmcli", "connection", "delete", "uuid", uuid], timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def _output(proc: subprocess.CompletedProcess) -> str:
    return ((proc.stderr or proc.stdout) or "").strip()


def _explain(ssid: str, psk: str, message: str) -> str:
    """Turn an nmcli failure into something the person setting up can act on.

    The status this ends up in can be read by anything in Bluetooth range, so
    the password is scrubbed should nmcli ever echo it back. The log keeps
    nmcli's own words but, like the Bluetooth log, not the network's name.
    """
    if psk:
        message = message.replace(psk, "(password)")
    print(f"[wifi] joining failed: {message.replace(ssid, '(network)')}")
    if "Secrets were required" in message:
        return f"Couldn't join {ssid}. Check the WiFi password."
    if "No network with SSID" in message:
        return f"Can't see a network called {ssid}. Check the name (capitals count) and that the Pi is in range."
    return message or "Unknown nmcli failure"
