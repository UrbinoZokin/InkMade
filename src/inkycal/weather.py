from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class WeatherAtTime:
    temperature_f: int
    icon: str


def _weather_icon(weather_code: int) -> str:
    # WMO weather codes from Open-Meteo.
    # Keep glyphs in a subset that's reliably present in DejaVuSans so
    # weather icons render on the e-ink display instead of tofu boxes.
    if weather_code == 0:
        return "☀"
    if weather_code in {1, 2}:
        return "☁"
    if weather_code == 3:
        return "☁"
    if weather_code in {45, 48}:
        return "☁"
    if weather_code in {51, 53, 55, 56, 57}:
        return "☂"
    if weather_code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "☔"
    if weather_code in {71, 73, 75, 77, 85, 86}:
        return "❄"
    if weather_code in {95, 96, 99}:
        return "⚡"
    return "☁"


class WeatherForecastResolver:
    def __init__(self, timezone: str, latitude: float, longitude: float):
        self.timezone = timezone
        self.latitude = latitude
        self.longitude = longitude

    def forecast_for_datetime(self, forecast_time: datetime) -> Optional[WeatherAtTime]:
        if forecast_time.tzinfo is None:
            return None

        params = urlencode(
            {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "hourly": "temperature_2m,weather_code",
                "temperature_unit": "fahrenheit",
                "timezone": self.timezone,
                "forecast_days": 3,
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{params}"

        with urlopen(url, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        codes = hourly.get("weather_code", [])

        if not times or len(times) != len(temps) or len(times) != len(codes):
            return None

        by_hour: Dict[str, tuple[float, int]] = {}
        for t, temp, code in zip(times, temps, codes):
            by_hour[t] = (float(temp), int(code))

        hour_key = forecast_time.strftime("%Y-%m-%dT%H:00")
        values = by_hour.get(hour_key)
        if values is None:
            return None

        temp, code = values
        return WeatherAtTime(temperature_f=int(round(temp)), icon=_weather_icon(code))

    def forecast_for_event_start(self, event_start: datetime) -> Optional[WeatherAtTime]:
        return self.forecast_for_datetime(event_start)
