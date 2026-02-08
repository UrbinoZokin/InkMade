from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any

SYS_POWER_PATH = Path("/sys/class/power_supply")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _power_source_from_status(status: str) -> Optional[str]:
    normalized = status.strip().lower()
    if not normalized:
        return None
    if normalized == "discharging":
        return "battery"
    if normalized in {"charging", "full", "not charging"}:
        return "external"
    return None


def probe_ups(sys_power_path: Path = SYS_POWER_PATH) -> Dict[str, Any]:
    """Probe sysfs power_supply entries for UPS/battery information.

    Returns a normalized dict with keys:
    - present: bool
    - percent: Optional[int]
    - power_source: Optional[str] ("battery" or "external")
    """
    try:
        supplies = sorted([path for path in sys_power_path.iterdir() if path.is_dir()])
    except OSError:
        return {"present": False, "percent": None, "power_source": None}

    if not supplies:
        return {"present": False, "percent": None, "power_source": None}

    def sort_key(path: Path) -> tuple[int, str]:
        supply_type = _read_text(path / "type").lower()
        is_battery = 0 if supply_type == "battery" else 1
        return (is_battery, path.name)

    for supply in sorted(supplies, key=sort_key):
        capacity = _parse_int(_read_text(supply / "capacity"))
        status = _read_text(supply / "status")
        power_source = _power_source_from_status(status)

        if capacity is None and power_source is None:
            continue

        return {
            "present": True,
            "percent": capacity,
            "power_source": power_source,
        }

    return {"present": False, "percent": None, "power_source": None}
