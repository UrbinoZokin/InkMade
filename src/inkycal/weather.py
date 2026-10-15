from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class WeatherAtTime:
    temperature_f: int
    icon: str


@dataclass(frozen=True)
class WeatherAlert:
    headline: str


@dataclass(frozen=True)
class DayForecast:
    """One day of the weekly view's weather."""

    high_f: int
    low_f: int
    icon: str
    precipitation: Optional[str] = None  # "Rain" or "Snow", when it's expected
    precipitation_chance: Optional[int] = None  # percent, when the forecast gives one


# How many days one forecast download covers: the weekly view's seven.
FORECAST_DAYS = 7

# WMO weather codes (Open-Meteo) that mean rain -- drizzle, freezing rain,
# showers and thunderstorms with it -- and snow.
_RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_SNOW_CODES = {71, 73, 75, 77, 85, 86}

# A day whose forecast has rain or snow in it at a lower chance than this
# isn't marked as a rain or snow day: a stray shower the model gives a 10%
# chance is noise, not something to plan around.
PRECIPITATION_MIN_CHANCE = 30


def _precipitation(code: Optional[int], chance: Optional[int]) -> Optional[str]:
    """The day's expected precipitation, "Rain" or "Snow"; None if it should stay dry."""
    if chance is not None and chance < PRECIPITATION_MIN_CHANCE:
        return None
    if code in _SNOW_CODES:
        return "Snow"
    if code in _RAIN_CODES:
        return "Rain"
    return None


def _item(values: Sequence, index: int):
    """values[index], or None past its end (Open-Meteo also sends null)."""
    return values[index] if index < len(values) else None


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


def _parse_hourly(hourly: dict) -> Dict[str, tuple[float, int]]:
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    codes = hourly.get("weather_code", [])

    if not times or len(times) != len(temps) or len(times) != len(codes):
        return {}

    by_hour: Dict[str, tuple[float, int]] = {}
    for t, temp, code in zip(times, temps, codes):
        if temp is None or code is None:
            continue
        by_hour[t] = (float(temp), int(code))
    return by_hour


def _parse_daily(daily: dict) -> Dict[date, DayForecast]:
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    codes = daily.get("weather_code", [])
    chances = daily.get("precipitation_probability_max", [])

    by_day: Dict[date, DayForecast] = {}
    for i, day in enumerate(daily.get("time", [])):
        high, low = _item(highs, i), _item(lows, i)
        if high is None or low is None:
            continue
        code = _item(codes, i)
        code = int(code) if code is not None else None
        chance = _item(chances, i)
        chance = int(round(chance)) if chance is not None else None
        precipitation = _precipitation(code, chance)
        by_day[date.fromisoformat(day)] = DayForecast(
            high_f=int(round(high)),
            low_f=int(round(low)),
            icon=_weather_icon(code) if code is not None else "",
            precipitation=precipitation,
            precipitation_chance=chance if precipitation else None,
        )
    return by_day


class WeatherForecastResolver:
    def __init__(self, timezone: str, latitude: float, longitude: float):
        self.timezone = timezone
        self.latitude = latitude
        self.longitude = longitude
        # Filled in by the first lookup; see _forecast.
        self._forecast_data: Optional[Tuple[Dict[str, tuple[float, int]], Dict[date, DayForecast]]] = None
        self._fetch_error: Optional[Exception] = None

    def _forecast(self) -> Tuple[Dict[str, tuple[float, int]], Dict[date, DayForecast]]:
        """The hourly forecast keyed by local hour ("YYYY-MM-DDTHH:00"), and the daily one by date.

        Fetched once per resolver, both in one request. Every event on the
        screen looks its weather up in the same forecast, and so does every day
        of the weekly view; asking Open-Meteo again for each one used to cost a
        request per event (two for events over an hour). A failed fetch is
        remembered as well: otherwise an unreachable API would make every event
        wait out its own timeout, one after another.
        """
        if self._fetch_error is not None:
            raise self._fetch_error
        if self._forecast_data is None:
            try:
                self._forecast_data = self._fetch_forecast()
            except Exception as e:
                self._fetch_error = e
                raise
        return self._forecast_data

    def _hourly_forecast(self) -> Dict[str, tuple[float, int]]:
        return self._forecast()[0]

    def daily_forecasts(self) -> Dict[date, DayForecast]:
        """High, low and any rain or snow for each of the next FORECAST_DAYS days."""
        return self._forecast()[1]

    def _fetch_forecast(self) -> Tuple[Dict[str, tuple[float, int]], Dict[date, DayForecast]]:
        params = urlencode(
            {
                "latitude": self.latitude,
                "longitude": self.longitude,
                "hourly": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
                "temperature_unit": "fahrenheit",
                "timezone": self.timezone,
                "forecast_days": FORECAST_DAYS,
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{params}"

        with urlopen(url, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        return _parse_hourly(payload.get("hourly", {})), _parse_daily(payload.get("daily", {}))

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
