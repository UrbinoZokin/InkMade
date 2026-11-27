"""An event with an address away from home gets the weather there, marked "*".

Anything that goes wrong on the way (an address that can't be placed, a
failed download, an hour missing from the forecast) leaves the event with
home's weather and no mark, exactly as before this existed.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from inkycal import main
from inkycal.main import _apply_weather_forecast, _event_place_forecasts
from inkycal.models import Event
from inkycal.weather import WeatherForecastResolver, forecasts_for_places

TZ = ZoneInfo("America/Phoenix")
HOME = (33.4353, -112.3582)  # Goodyear, AZ
FLAGSTAFF = (35.1983, -111.6513)  # ~128 miles away
AVONDALE = (33.4356, -112.3496)  # under a mile away
TUCSON = (32.2226, -110.9747)


def _cfg(event_locations=True, min_miles=10.0):
    return SimpleNamespace(
        timezone="America/Phoenix",
        weather=SimpleNamespace(
            latitude=HOME[0],
            longitude=HOME[1],
            event_locations=event_locations,
            event_location_min_miles=min_miles,
        ),
    )


def _event(title, location=None, hour=9, hours=1):
    start = datetime(2026, 11, 27, hour, 0, tzinfo=TZ)
    return Event(source="google", title=title, start=start, end=start + timedelta(hours=hours), location=location)


class StubGeocoder:
    def __init__(self, places):
        self.places = places
        self.asked = []
        self.saved = False

    def locate(self, address):
        self.asked.append(address)
        return self.places.get(address)

    def save(self):
        self.saved = True


class Fixed:
    """A resolver that gives every hour the same temperature."""

    def __init__(self, temperature_f, icon="☀"):
        self.weather = SimpleNamespace(temperature_f=temperature_f, icon=icon)

    def forecast_for_event_start(self, _when):
        return self.weather

    def forecast_for_datetime(self, _when):
        return self.weather


class _JsonResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _hourly(temp):
    hours = range(48)
    return {
        "hourly": {
            "time": [(datetime(2026, 11, 27) + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00") for h in hours],
            "temperature_2m": [float(temp)] * 48,
            "weather_code": [71] * 48,
        }
    }


@pytest.fixture
def open_meteo(monkeypatch):
    """Answers each place in the request with the temperature `temps` gives its latitude."""
    temps = {}
    requests = []

    def urlopen(url, **_kw):
        requests.append(url)
        query = parse_qs(urlparse(url).query)
        lats = [float(x) for x in query["latitude"][0].split(",")]
        answers = [_hourly(temps[lat]) for lat in lats]
        return _JsonResponse(answers if len(answers) > 1 else answers[0])

    monkeypatch.setattr("inkycal.weather.urlopen", urlopen)
    return SimpleNamespace(temps=temps, requests=requests)


# --- weather.forecasts_for_places -------------------------------------------------


def test_several_places_are_forecast_in_one_download(open_meteo):
    open_meteo.temps.update({35.2: 41, 32.22: 77})

    flagstaff, tucson = forecasts_for_places("America/Phoenix", [(35.2, -111.65), (32.22, -110.97)])
    when = datetime(2026, 11, 27, 9, 0, tzinfo=TZ)

    assert flagstaff.forecast_for_datetime(when).temperature_f == 41
    assert tucson.forecast_for_datetime(when).temperature_f == 77
    assert len(open_meteo.requests) == 1
    query = parse_qs(urlparse(open_meteo.requests[0]).query)
    assert query["forecast_days"] == ["2"]
    assert "daily" not in query  # the weekly view's highs and lows stay home's


def test_one_place_is_answered_with_an_object_not_a_list(open_meteo):
    open_meteo.temps[35.2] = 41

    (flagstaff,) = forecasts_for_places("America/Phoenix", [(35.2, -111.65)])

    assert flagstaff.forecast_for_datetime(datetime(2026, 11, 27, 9, 0, tzinfo=TZ)).temperature_f == 41


def test_a_place_with_no_forecast_in_its_answer_fails_alone(monkeypatch):
    answers = [_hourly(41), {"hourly": {}}]
    monkeypatch.setattr("inkycal.weather.urlopen", lambda url, **_kw: _JsonResponse(answers))

    flagstaff, nowhere = forecasts_for_places("America/Phoenix", [(35.2, -111.65), (0.0, 0.0)])

    assert flagstaff.forecast_for_datetime(datetime(2026, 11, 27, 9, 0, tzinfo=TZ)).temperature_f == 41
    with pytest.raises(ValueError):
        nowhere.forecast_for_datetime(datetime(2026, 11, 27, 9, 0, tzinfo=TZ))


def test_an_answer_for_the_wrong_number_of_places_is_refused(monkeypatch):
    monkeypatch.setattr("inkycal.weather.urlopen", lambda url, **_kw: _JsonResponse([_hourly(41)]))

    with pytest.raises(ValueError):
        forecasts_for_places("America/Phoenix", [(35.2, -111.65), (32.22, -110.97)])


def test_home_forecast_still_asks_for_a_week_with_daily_highs_and_lows(open_meteo, monkeypatch):
    payload = _hourly(70)
    payload["daily"] = {"time": ["2026-11-27"], "temperature_2m_max": [75.0], "temperature_2m_min": [50.0]}
    requests = []
    monkeypatch.setattr("inkycal.weather.urlopen", lambda url, **_kw: requests.append(url) or _JsonResponse(payload))

    WeatherForecastResolver("America/Phoenix", *HOME).load()

    query = parse_qs(urlparse(requests[0]).query)
    assert query["forecast_days"] == ["7"] and "daily" in query
    assert query["latitude"] == [str(HOME[0])]


# --- main: choosing each event's forecast ----------------------------------------------


def _apply(events, place_resolvers, home=None, **kw):
    return _apply_weather_forecast(
        events, "America/Phoenix", *HOME, resolver=home or Fixed(95), place_resolvers=place_resolvers, **kw
    )


def test_an_event_out_of_town_gets_the_weather_there_marked_with_an_asterisk(open_meteo):
    open_meteo.temps[35.2] = 41
    hike = _event("Hike", location="Buffalo Park, Flagstaff, AZ")
    errand = _event("Groceries", hour=11)
    geocoder = StubGeocoder({"Buffalo Park, Flagstaff, AZ": FLAGSTAFF})

    places = _event_place_forecasts([hike, errand], _cfg(), geocoder)
    hike_out, errand_out = _apply([hike, errand], places)

    assert hike_out.weather_text == "41°F*"
    assert hike_out.weather_temperature_f == 41
    assert hike_out.weather_icon == "❄"
    assert errand_out.weather_text == "95°F"
    assert geocoder.saved


def test_a_long_event_out_of_town_has_both_temperatures_marked(open_meteo):
    open_meteo.temps[35.2] = 41
    hike = _event("Hike", location="Flagstaff, AZ", hours=3)

    places = _event_place_forecasts([hike], _cfg(), StubGeocoder({"Flagstaff, AZ": FLAGSTAFF}))
    (out,) = _apply([hike], places)

    assert (out.weather_text, out.weather_end_text) == ("41°F*", "41°F*")


def test_an_address_near_home_keeps_home_weather_and_downloads_nothing(open_meteo):
    dentist = _event("Dentist", location="1 Clinic Way, Avondale, AZ")

    places = _event_place_forecasts([dentist], _cfg(), StubGeocoder({"1 Clinic Way, Avondale, AZ": AVONDALE}))
    (out,) = _apply([dentist], places)

    assert places == {}
    assert out.weather_text == "95°F"
    assert open_meteo.requests == []


def test_the_distance_that_counts_as_away_is_configurable(open_meteo):
    open_meteo.temps[33.44] = 90
    dentist = _event("Dentist", location="Avondale")

    places = _event_place_forecasts([dentist], _cfg(min_miles=0.1), StubGeocoder({"Avondale": AVONDALE}))

    assert _apply([dentist], places)[0].weather_text == "90°F*"


def test_an_address_that_cannot_be_placed_keeps_home_weather(open_meteo):
    visit = _event("Visit", location="Mom's")

    places = _event_place_forecasts([visit], _cfg(), StubGeocoder({}))
    (out,) = _apply([visit], places)

    assert out.weather_text == "95°F"
    assert open_meteo.requests == []


def test_a_failed_download_for_away_events_keeps_home_weather(monkeypatch, capsys):
    def down(url, **_kw):
        raise OSError("timed out")

    monkeypatch.setattr("inkycal.weather.urlopen", down)
    hike = _event("Hike", location="Flagstaff, AZ")

    places = _event_place_forecasts([hike], _cfg(), StubGeocoder({"Flagstaff, AZ": FLAGSTAFF}))
    (out,) = _apply([hike], places)

    assert places == {}
    assert out.weather_text == "95°F"
    assert "giving them home weather" in capsys.readouterr().out


def test_an_hour_missing_from_the_places_forecast_falls_back_to_home():
    class Gaps(Fixed):
        def forecast_for_event_start(self, _when):
            return None

    hike = _event("Hike", location="Flagstaff, AZ", hours=3)
    (out,) = _apply([hike], {"Flagstaff, AZ": Gaps(41)})

    # The start hour wasn't in Flagstaff's forecast; the end hour was.
    assert (out.weather_text, out.weather_end_text) == ("95°F", "41°F*")


def test_a_place_lookup_that_raises_falls_back_to_home():
    class Broken(Fixed):
        def forecast_for_event_start(self, _when):
            raise ValueError("no forecast")

    (out,) = _apply([_event("Hike", location="Flagstaff, AZ")], {"Flagstaff, AZ": Broken(41)})

    assert out.weather_text == "95°F"


def test_turned_off_no_address_is_looked_up(open_meteo):
    geocoder = StubGeocoder({"Flagstaff, AZ": FLAGSTAFF})

    places = _event_place_forecasts([_event("Hike", location="Flagstaff, AZ")], _cfg(event_locations=False), geocoder)

    assert places == {} and geocoder.asked == []


def test_each_address_is_looked_up_once_and_nearby_ones_share_a_forecast(open_meteo):
    open_meteo.temps.update({35.2: 41, 32.22: 77})
    events = [
        _event("Breakfast", location="Flagstaff, AZ", hour=8),
        _event("Hike", location="Flagstaff, AZ", hour=10),
        _event("Lunch", location="Downtown Flagstaff", hour=12),
        _event("Dinner", location="Tucson, AZ", hour=18),
        Event(
            source="google", title="Party", start=datetime(2026, 11, 27, tzinfo=TZ),
            end=datetime(2026, 11, 28, tzinfo=TZ), all_day=True, location="Somewhere",
        ),
    ]
    geocoder = StubGeocoder(
        {"Flagstaff, AZ": FLAGSTAFF, "Downtown Flagstaff": (35.1984, -111.6512), "Tucson, AZ": TUCSON}
    )

    places = _event_place_forecasts(events, _cfg(), geocoder)

    assert geocoder.asked == ["Flagstaff, AZ", "Downtown Flagstaff", "Tucson, AZ"]  # not the all-day event's
    assert len(open_meteo.requests) == 1
    lats = parse_qs(urlparse(open_meteo.requests[0]).query)["latitude"][0].split(",")
    assert sorted(lats) == ["32.22", "35.2"]  # the two Flagstaff addresses are one place
    assert [e.weather_text for e in _apply(events, places)[:4]] == ["41°F*", "41°F*", "41°F*", "77°F*"]


def test_event_fields_other_than_weather_are_kept():
    event = replace(_event("Hike", location="Flagstaff, AZ"), travel_time_text="Travel: 2 hr", birthday=True)

    (out,) = _apply([event], {})

    assert (out.location, out.travel_time_text, out.birthday) == ("Flagstaff, AZ", "Travel: 2 hr", True)


# --- run_once: the whole path -------------------------------------------------------------

CONFIG = """
timezone: "America/Phoenix"
sleep:
  enabled: false
display:
  width: 60
  height: 80
  rotate_degrees: 0
  border: white
calendars:
  google:
    enabled: false
  icloud:
    enabled: false
auto_update:
  enabled: false
weather:
  latitude: 33.4353
  longitude: -112.3582
  event_locations: {event_locations}
"""


class _HomeWeather:
    def __init__(self, **_kwargs):
        pass

    def load(self):
        pass

    def active_alerts(self):
        return []

    def forecast_for_event_start(self, _start):
        return SimpleNamespace(temperature_f=95, icon="☀")

    def forecast_for_datetime(self, _when):
        return SimpleNamespace(temperature_f=95, icon="☀")

    def daily_forecasts(self):
        return {}


@pytest.fixture
def run(tmp_path, monkeypatch):
    drawn = []
    calendar = []

    def daily(**kwargs):
        drawn.append(kwargs["events"])
        return Image.new("RGB", (kwargs["canvas_w"], kwargs["canvas_h"]), "white")

    monkeypatch.setattr(main, "WeatherForecastResolver", _HomeWeather)
    monkeypatch.setattr(main, "render_daily_schedule", daily)
    monkeypatch.setattr(main, "show_on_inky", lambda img, **_kw: None)
    monkeypatch.setattr(main, "_fetch_raw_events", lambda *_a, **_kw: list(calendar))
    monkeypatch.setattr(main, "forecasts_for_places", lambda tz, places: [Fixed(41) for _ in places])

    def go(event_locations="true"):
        config = tmp_path / "config.yaml"
        config.write_text(CONFIG.format(event_locations=event_locations), encoding="utf-8")
        main.run_once(config_path=str(config), state_path=str(tmp_path / "state.json"), force=True)
        return drawn[-1]

    return SimpleNamespace(go=go, calendar=calendar, tmp_path=tmp_path)


def _today_event(title, location):
    start = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    return Event(source="google", title=title, start=start, end=start + timedelta(hours=1), location=location)


def test_run_once_draws_an_away_events_weather_and_remembers_the_address(run, monkeypatch):
    lookups = []

    class Nominatim:
        def get(self, url, params=None, timeout=None):
            lookups.append(params["q"])
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: [{"lat": str(FLAGSTAFF[0]), "lon": str(FLAGSTAFF[1])}],
            )

    monkeypatch.setattr("inkycal.geocode._default_session", Nominatim)
    run.calendar.append(_today_event("Hike", "Buffalo Park, Flagstaff, AZ"))
    run.calendar.append(_today_event("Errand", None))

    first = run.go()
    second = run.go()

    assert {e.title: e.weather_text for e in first} == {"Hike": "41°F*", "Errand": "95°F"}
    assert {e.title: e.weather_text for e in second} == {"Hike": "41°F*", "Errand": "95°F"}
    assert lookups == ["Buffalo Park, Flagstaff, AZ"]  # the second run used the saved answer
    assert (run.tmp_path / "geocode_cache.json").exists()


def test_run_once_with_the_lookup_offline_draws_home_weather(run):
    # conftest's default: the geocoder can't reach anything.
    run.calendar.append(_today_event("Hike", "Buffalo Park, Flagstaff, AZ"))

    (hike,) = run.go()

    assert hike.weather_text == "95°F"


def test_run_once_turned_off_never_builds_a_geocoder(run, monkeypatch):
    def no_geocoder(*_a, **_kw):
        raise AssertionError("event_locations is off")

    monkeypatch.setattr(main, "Geocoder", no_geocoder)
    run.calendar.append(_today_event("Hike", "Buffalo Park, Flagstaff, AZ"))

    (hike,) = run.go(event_locations="false")

    assert hike.weather_text == "95°F"
