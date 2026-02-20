from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(frozen=True)
class Event:
    source: str                 # "google" / "icloud"
    title: str
    start: datetime             # timezone-aware
    end: datetime               # timezone-aware
    all_day: bool = False
    location: Optional[str] = None
    travel_time_text: Optional[str] = None
    weather_icon: Optional[str] = None
    weather_text: Optional[str] = None
    weather_temperature_f: Optional[int] = None
    weather_end_icon: Optional[str] = None
    weather_end_text: Optional[str] = None
    weather_end_temperature_f: Optional[int] = None
