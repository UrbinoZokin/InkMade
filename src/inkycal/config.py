from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

@dataclass
class SleepConfig:
    enabled: bool
    start: str
    end: str
    banner_text: str

@dataclass
class DeepCleanConfig:
    enabled: bool
    weekday: str
    time: str

@dataclass
class DisplayConfig:
    width: int
    height: int
    rotate_degrees: int
    saturation: float
    border: str

@dataclass
class GoogleConfig:
    enabled: bool
    calendar_ids: List[str]
    tasks_enabled: bool = True
    task_list_allowlist: List[str] = field(default_factory=list)

@dataclass
class ICloudConfig:
    enabled: bool
    calendar_name_allowlist: List[str]

@dataclass
class TravelConfig:
    enabled: bool
    origin_address: str
    back_to_back_window_minutes: int

@dataclass
class WeatherConfig:
    latitude: float
    longitude: float

@dataclass
class AutoUpdateConfig:
    enabled: bool = True
    branch: str = "main"
    # When to actually apply a pending update: "sleep" (only during the
    # overnight sleep window, so it never disrupts daytime viewing) or
    # "anytime" (apply as soon as it is found).
    apply_window: str = "sleep"

@dataclass
class ButtonsConfig:
    enabled: bool = True
    # BCM GPIO pin numbers for the Inky Impression's 4 built-in buttons
    # (labeled A/B/C/D on the board). Defaults match the 13.3" model, where
    # button C is wired to GPIO25 instead of the GPIO16 used on the smaller
    # (4"/5.7"/7.3") Impression sizes.
    pin_view: int = 5      # A: toggle daily/weekly view
    pin_refresh: int = 6   # B: force a display refresh
    pin_unused: int = 25   # C: unused (reserved)
    pin_update: int = 24   # D: force an OTA update check/apply
    bounce_time_ms: int = 300

@dataclass
class AppConfig:
    timezone: str
    poll_interval_minutes: int
    sleep: SleepConfig
    deep_clean: DeepCleanConfig
    display: DisplayConfig
    google: GoogleConfig
    icloud: ICloudConfig
    travel: TravelConfig
    weather: WeatherConfig
    auto_update: AutoUpdateConfig = field(default_factory=AutoUpdateConfig)
    buttons: ButtonsConfig = field(default_factory=ButtonsConfig)

def load_config(path: str) -> AppConfig:
    p = Path(path)
    data: Dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8"))

    sleep = data.get("sleep", {})
    deep_clean = data.get("deep_clean", {})
    display = data.get("display", {})
    calendars = data.get("calendars", {})
    travel = data.get("travel", {})
    weather = data.get("weather", {})
    auto_update = data.get("auto_update", {})
    buttons = data.get("buttons", {})

    google = calendars.get("google", {})
    icloud = calendars.get("icloud", {})

    return AppConfig(
        timezone=data.get("timezone", "America/Arizona"),
        poll_interval_minutes=int(data.get("poll_interval_minutes", 15)),
        sleep=SleepConfig(
            enabled=bool(sleep.get("enabled", True)),
            start=str(sleep.get("start", "22:30")),
            end=str(sleep.get("end", "06:30")),
            banner_text=str(sleep.get("banner_text", "Sleeping")),
        ),
        deep_clean=DeepCleanConfig(
            enabled=bool(deep_clean.get("enabled", True)),
            weekday=str(deep_clean.get("weekday", "Sunday")),
            time=str(deep_clean.get("time", "03:30")),
        ),
        display=DisplayConfig(
            width=int(display.get("width", 1200)),
            height=int(display.get("height", 1600)),
            rotate_degrees=int(display.get("rotate_degrees", 90)),
            saturation=float(display.get("saturation", 0.0)),
            border=str(display.get("border", "white")),
        ),
        google=GoogleConfig(
            enabled=bool(google.get("enabled", True)),
            calendar_ids=list(google.get("calendar_ids", ["primary"])),
            tasks_enabled=bool(google.get("tasks_enabled", True)),
            task_list_allowlist=list(google.get("task_list_allowlist", [])),
        ),
        icloud=ICloudConfig(
            enabled=bool(icloud.get("enabled", True)),
            calendar_name_allowlist=list(icloud.get("calendar_name_allowlist", [])),
        ),
        travel=TravelConfig(
            enabled=bool(travel.get("enabled", False)),
            origin_address=str(travel.get("origin_address", "")).strip(),
            back_to_back_window_minutes=int(travel.get("back_to_back_window_minutes", 30)),
        ),
        weather=WeatherConfig(
            latitude=float(weather.get("latitude", 33.4353)),
            longitude=float(weather.get("longitude", -112.3582)),
        ),
        auto_update=AutoUpdateConfig(
            enabled=bool(auto_update.get("enabled", True)),
            branch=str(auto_update.get("branch", "main")),
            apply_window=str(auto_update.get("apply_window", "sleep")).strip().lower(),
        ),
        buttons=ButtonsConfig(
            enabled=bool(buttons.get("enabled", True)),
            pin_view=int(buttons.get("pin_view", 5)),
            pin_refresh=int(buttons.get("pin_refresh", 6)),
            pin_unused=int(buttons.get("pin_unused", 25)),
            pin_update=int(buttons.get("pin_update", 24)),
            bounce_time_ms=int(buttons.get("bounce_time_ms", 300)),
        ),
    )
