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
