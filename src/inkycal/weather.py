from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class WeatherAtTime:
    temperature_f: int
    icon: str


@dataclass(frozen=True)
class WeatherAlert:
    headline: str


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
        # Filled in by the first lookup; see _hourly_forecast.
        self._by_hour: Optional[Dict[str, tuple[float, int]]] = None
        self._fetch_error: Optional[Exception] = None

    def _hourly_forecast(self) -> Dict[str, tuple[float, int]]:
        """The hourly forecast keyed by local hour ("YYYY-MM-DDTHH:00").

        Fetched once per resolver. Every event on the screen looks its weather
        up in the same three-day forecast, and asking Open-Meteo again for each
        one used to cost a request per event (two for events over an hour).
        A failed fetch is remembered as well: otherwise an unreachable API would
        make every event wait out its own timeout, one after another.
        """
        if self._fetch_error is not None:
            raise self._fetch_error
        if self._by_hour is None:
            try:
                self._by_hour = self._fetch_hourly_forecast()
            except Exception as e:
                self._fetch_error = e
                raise
        return self._by_hour

    def _fetch_hourly_forecast(self) -> Dict[str, tuple[float, int]]:
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
            return {}

        by_hour: Dict[str, tuple[float, int]] = {}
        for t, temp, code in zip(times, temps, codes):
            by_hour[t] = (float(temp), int(code))
        return by_hour

    def forecast_for_datetime(self, forecast_time: datetime) -> Optional[WeatherAtTime]:
        if forecast_time.tzinfo is None:
            return None

        hour_key = forecast_time.strftime("%Y-%m-%dT%H:00")
        values = self._hourly_forecast().get(hour_key)
        if values is None:
            return None

        temp, code = values
        return WeatherAtTime(temperature_f=int(round(temp)), icon=_weather_icon(code))

    def forecast_for_event_start(self, event_start: datetime) -> Optional[WeatherAtTime]:
        return self.forecast_for_datetime(event_start)

    def active_alerts(self, limit: int = 2) -> List[WeatherAlert]:
        params = urlencode({"point": f"{self.latitude},{self.longitude}"})
        req = Request(
            f"https://api.weather.gov/alerts/active?{params}",
            headers={"User-Agent": "inkycal/1.0 (contact: local)"},
        )
        with urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        features = payload.get("features", [])
        alerts: List[WeatherAlert] = []
        seen_headlines = set()
        for feature in features:
            properties = feature.get("properties", {})
            headline = str(properties.get("headline") or "").strip()
            if not headline:
                event = str(properties.get("event") or "").strip()
                severity = str(properties.get("severity") or "").strip()
                if event and severity:
                    headline = f"{severity}: {event}"
                else:
                    headline = event
            if not headline or headline in seen_headlines:
                continue
            alerts.append(WeatherAlert(headline=headline))
            seen_headlines.add(headline)
            if len(alerts) >= limit:
                break
        return alerts
