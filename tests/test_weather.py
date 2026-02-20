from datetime import datetime
from zoneinfo import ZoneInfo

from inkycal.main import _apply_weather_forecast, _events_signature
from inkycal.models import Event
from inkycal.weather import _weather_icon


class StubWeatherResolver:
    def __init__(self, timezone: str, latitude: float, longitude: float):
        self.timezone = timezone
        self.latitude = latitude
        self.longitude = longitude

    def forecast_for_event_start(self, event_start: datetime):
        class Forecast:
            temperature_f = 72
            icon = "☔"

        return Forecast()


def test_apply_weather_forecast_adds_icon_and_temperature(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    event = Event(
        source="google",
        title="Drive to office",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=tz),
    )

    monkeypatch.setattr("inkycal.main.WeatherForecastResolver", StubWeatherResolver)

    processed = _apply_weather_forecast([event], "America/Phoenix", 33.4353, -112.3582)

    assert processed[0].weather_icon == "☔"
    assert processed[0].weather_text == "72°F"


def test_events_signature_ignores_weather_fields():
    tz = ZoneInfo("America/Phoenix")
    event_base = Event(
        source="google",
        title="Drive to office",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=tz),
    )
    event_with_weather = Event(
        source="google",
        title="Drive to office",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 0, tzinfo=tz),
        weather_icon="☀",
        weather_text="70°F",
    )

    hash_without_weather = _events_signature(
        tz,
        [event_base],
        [],
        "Thursday, February 5, 2026",
        False,
        "connected",
        {},
    )
    hash_with_weather = _events_signature(
        tz,
        [event_with_weather],
        [],
        "Thursday, February 5, 2026",
        False,
        "connected",
        {},
    )

    assert hash_without_weather == hash_with_weather


def test_weather_icons_use_dejavu_safe_symbols_for_partial_cloud_and_fog():
    assert _weather_icon(1) == "☁"
    assert _weather_icon(2) == "☁"
    assert _weather_icon(45) == "☁"
    assert _weather_icon(48) == "☁"
