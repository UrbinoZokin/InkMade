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

def load_config(path: str) -> AppConfig:
    p = Path(path)
    data: Dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8"))

    sleep = data.get("sleep", {})
    deep_clean = data.get("deep_clean", {})
    display = data.get("display", {})
    calendars = data.get("calendars", {})
    travel = data.get("travel", {})
    weather = data.get("weather", {})

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
    )
