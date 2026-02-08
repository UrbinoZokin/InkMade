from __future__ import annotations

from pathlib import Path

SYS_NET_PATH = Path("/sys/class/net")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def get_wifi_status(sys_net_path: Path = SYS_NET_PATH) -> str:
    """Return wifi status as connected/disconnected/empty if no wifi interface."""
    try:
        interfaces = sorted(sys_net_path.iterdir())
    except OSError:
        return ""

    for iface in interfaces:
        if not iface.is_dir():
            continue
        if not (iface / "wireless").is_dir():
            continue

        carrier = _read_text(iface / "carrier")
        if carrier == "1":
            return "connected"
        if carrier == "0":
            return "disconnected"

        operstate = _read_text(iface / "operstate").lower()
        if operstate in {"up", "unknown"}:
            return "connected"
        if operstate:
            return "disconnected"
        return ""

    return ""
