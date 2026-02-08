from __future__ import annotations

from pathlib import Path
from typing import Optional

SYS_NET_PATH = Path("/sys/class/net")
POWER_SUPPLY_PATH = Path("/sys/class/power_supply")


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


def _read_optional_int(value: str) -> Optional[int]:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _read_optional_bool(value: str) -> Optional[bool]:
    value = value.strip()
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def get_ups_status(power_supply_path: Path = POWER_SUPPLY_PATH) -> dict:
    """Return UPS status info from /sys/class/power_supply, or present=False."""
    try:
        supplies = sorted(power_supply_path.iterdir())
    except OSError:
        return {"present": False, "status": "", "capacity": None, "online": None}

    for supply in supplies:
        if not supply.is_dir():
            continue
        if _read_text(supply / "type").upper() != "UPS":
            continue

        present = _read_optional_bool(_read_text(supply / "present"))
        status = _read_text(supply / "status").lower()
        capacity = _read_optional_int(_read_text(supply / "capacity"))
        online = _read_optional_bool(_read_text(supply / "online"))
        return {
            "present": True if present is None else present,
            "status": status,
            "capacity": capacity,
            "online": online,
        }

    return {"present": False, "status": "", "capacity": None, "online": None}
