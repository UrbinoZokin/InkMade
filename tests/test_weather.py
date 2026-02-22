from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from inkycal.main import _apply_weather_forecast, _events_signature, print_long_events_weather_report
from inkycal.models import Event
from inkycal.weather import WeatherForecastResolver, _weather_icon


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


def test_apply_weather_forecast_adds_start_and_end_weather_for_long_events(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    event = Event(
        source="google",
        title="Long Planning Session",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 12, 0, tzinfo=tz),
    )

    class LongEventResolver(StubWeatherResolver):
        def forecast_for_datetime(self, when):
            if when.hour == 12:
                return SimpleNamespace(temperature_f=68, icon="☁")
            return SimpleNamespace(temperature_f=72, icon="☀")

    monkeypatch.setattr("inkycal.main.WeatherForecastResolver", LongEventResolver)

    processed = _apply_weather_forecast([event], "America/Phoenix", 33.4353, -112.3582)

    assert processed[0].weather_icon == "☔"
    assert processed[0].weather_text == "72°F"
    assert processed[0].weather_end_icon == "☁"
    assert processed[0].weather_end_text == "68°F"


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


def test_forecast_for_event_start_delegates_to_datetime(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    resolver = WeatherForecastResolver("America/Phoenix", 1.0, 2.0)
    expected = SimpleNamespace(temperature_f=71, icon="☀")

    def fake_forecast(self, when):
        assert when == datetime(2026, 2, 5, 9, 30, tzinfo=tz)
        return expected

    monkeypatch.setattr(WeatherForecastResolver, "forecast_for_datetime", fake_forecast)

    result = resolver.forecast_for_event_start(datetime(2026, 2, 5, 9, 30, tzinfo=tz))
    assert result is expected


def test_long_events_weather_report_filters_and_prints(monkeypatch, capsys):
    tz = ZoneInfo("America/Phoenix")
    long_event = Event(
        source="google",
        title="Long Planning Session",
        start=datetime(2026, 2, 5, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 10, 30, tzinfo=tz),
    )
    short_event = Event(
        source="google",
        title="Standup",
        start=datetime(2026, 2, 5, 11, 0, tzinfo=tz),
        end=datetime(2026, 2, 5, 11, 30, tzinfo=tz),
    )

    cfg = SimpleNamespace(
        timezone="America/Phoenix",
        weather=SimpleNamespace(latitude=33.4, longitude=-112.3),
    )

    class StubResolver:
        def __init__(self, timezone, latitude, longitude):
            pass

        def forecast_for_datetime(self, when):
            if when.hour == 9:
                return SimpleNamespace(temperature_f=70, icon="☀")
            return SimpleNamespace(temperature_f=68, icon="☁")

    monkeypatch.setattr("inkycal.main.load_dotenv", lambda: None)
    monkeypatch.setattr("inkycal.main.load_config", lambda _path: cfg)
    monkeypatch.setattr("inkycal.main._fetch_events_for_range", lambda *_args, **_kwargs: [long_event, short_event])
    monkeypatch.setattr("inkycal.main.WeatherForecastResolver", StubResolver)

    print_long_events_weather_report("unused")
    out = capsys.readouterr().out

    assert "Long Planning Session" in out
    assert "Standup" not in out
    assert "start weather: 70°F ☀" in out
    assert "end weather:   68°F ☁" in out


def test_apply_weather_forecast_skips_end_weather_when_disabled(monkeypatch):
    tz = ZoneInfo("America/Phoenix")
    event = Event(
        source="google",
        title="Tomorrow Deep Work",
        start=datetime(2026, 2, 6, 9, 0, tzinfo=tz),
        end=datetime(2026, 2, 6, 12, 0, tzinfo=tz),
    )

    class LongEventResolver(StubWeatherResolver):
        def forecast_for_datetime(self, when):
            return SimpleNamespace(temperature_f=65, icon="☁")

    monkeypatch.setattr("inkycal.main.WeatherForecastResolver", LongEventResolver)

    processed = _apply_weather_forecast(
        [event],
        "America/Phoenix",
        33.4353,
        -112.3582,
        include_end_weather_for_long_events=False,
    )

    assert processed[0].weather_icon == "☔"
    assert processed[0].weather_text == "72°F"
    assert processed[0].weather_end_icon is None
    assert processed[0].weather_end_text is None


def test_active_alerts_uses_headline_and_dedupes(monkeypatch):
    resolver = WeatherForecastResolver("America/Phoenix", 33.4, -112.3)

    class DummyResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'{"features": ['
                b'{"properties": {"headline": "Flood Warning"}},'
                b'{"properties": {"headline": "Flood Warning"}},'
                b'{"properties": {"event": "Heat Advisory", "severity": "Moderate"}}'
                b']}'
            )

    monkeypatch.setattr("inkycal.weather.urlopen", lambda *_args, **_kwargs: DummyResp())

    alerts = resolver.active_alerts(limit=3)

    assert [alert.headline for alert in alerts] == ["Flood Warning", "Moderate: Heat Advisory"]
