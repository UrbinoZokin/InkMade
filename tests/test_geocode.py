"""inkycal.geocode: event addresses are looked up once, near home, and never
for a meeting link; a failure costs one attempt and leaves nothing behind."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from inkycal import geocode
from inkycal.geocode import Geocoder, distance_miles

HOME = (33.4353, -112.3582)  # Goodyear, AZ
FLAGSTAFF = (35.1983, -111.6513)


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeNominatim:
    """Answers each query from `places`; anything not in it isn't found."""

    def __init__(self, places=None, fail=False):
        self.places = places or {}
        self.fail = fail
        self.queries = []
        self.params = []

    def get(self, url, params=None, timeout=None):
        assert url == geocode.NOMINATIM_URL
        self.queries.append(params["q"])
        self.params.append(params)
        if self.fail:
            raise OSError("Name or service not known")
        coords = self.places.get(params["q"])
        if coords is None:
            return _Response([])
        return _Response([{"lat": str(coords[0]), "lon": str(coords[1])}])


class Clock:
    def __init__(self):
        self.t = 100.0
        self.slept = []

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds


def _geocoder(cache_path, session, now=None, near=HOME, clock=None):
    clock = clock or Clock()
    return Geocoder(
        str(cache_path),
        near=near,
        session=session,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=now or (lambda: datetime(2026, 11, 27, tzinfo=timezone.utc)),
    )


def test_an_address_is_looked_up_once_and_remembered_across_runs(tmp_path):
    cache = tmp_path / "geocode_cache.json"
    nominatim = FakeNominatim({"1 Main St, Flagstaff, AZ": FLAGSTAFF})

    first = _geocoder(cache, nominatim)
    assert first.locate("1 Main St, Flagstaff, AZ") == FLAGSTAFF
    assert first.locate("1  main st,  Flagstaff, AZ") == FLAGSTAFF  # same address, typed differently
    first.save()

    second = _geocoder(cache, nominatim)
    assert second.locate("1 Main St, Flagstaff, AZ") == FLAGSTAFF
    assert nominatim.queries == ["1 Main St, Flagstaff, AZ"]


def test_an_icloud_name_and_address_on_two_lines_is_searched_as_one(tmp_path):
    nominatim = FakeNominatim({"Lowell Observatory, 1400 W Mars Hill Rd, Flagstaff": FLAGSTAFF})

    found = _geocoder(tmp_path / "c.json", nominatim).locate("Lowell Observatory\n1400 W Mars Hill Rd, Flagstaff\n")

    assert found == FLAGSTAFF


def test_an_address_that_cannot_be_placed_is_not_asked_about_again_for_a_month(tmp_path):
    cache = tmp_path / "geocode_cache.json"
    nominatim = FakeNominatim()
    today = datetime(2026, 11, 27, tzinfo=timezone.utc)

    g = _geocoder(cache, nominatim, now=lambda: today)
    assert g.locate("Mom's") is None
    g.save()
    assert _geocoder(cache, nominatim, now=lambda: today + timedelta(days=29)).locate("Mom's") is None
    assert nominatim.queries == ["Mom's"]

    assert _geocoder(cache, nominatim, now=lambda: today + timedelta(days=31)).locate("Mom's") is None
    assert nominatim.queries == ["Mom's", "Mom's"]


@pytest.mark.parametrize(
    "location",
    [
        "https://us02web.zoom.us/j/123456",
        "meet.google.com/abc-defg-hij",
        "www.example.com/meeting",
        "Zoom",
        "Microsoft Teams Meeting",
        "Phone",
        "Online",
        "",
        "   ",
    ],
)
def test_meeting_links_and_calls_are_never_sent(tmp_path, location):
    nominatim = FakeNominatim()

    assert _geocoder(tmp_path / "c.json", nominatim).locate(location) is None
    assert nominatim.queries == []


def test_a_failed_lookup_ends_lookups_for_the_run_and_is_not_remembered(tmp_path, capsys):
    cache = tmp_path / "geocode_cache.json"
    down = FakeNominatim(fail=True)

    g = _geocoder(cache, down)
    assert g.locate("1 Main St, Flagstaff, AZ") is None
    assert g.locate("2 Elm St, Tucson, AZ") is None
    g.save()

    assert down.queries == ["1 Main St, Flagstaff, AZ"]  # one timeout, not one per address
    assert "Address lookup failed" in capsys.readouterr().out
    assert not cache.exists()

    up = FakeNominatim({"1 Main St, Flagstaff, AZ": FLAGSTAFF})
    assert _geocoder(cache, up).locate("1 Main St, Flagstaff, AZ") == FLAGSTAFF


def test_an_error_status_counts_as_a_failed_lookup(tmp_path):
    class Refusing(FakeNominatim):
        def get(self, url, params=None, timeout=None):
            self.queries.append(params["q"])
            return _Response({"error": "rate limited"}, status=429)

    refusing = Refusing()
    g = _geocoder(tmp_path / "c.json", refusing)

    assert g.locate("1 Main St, Flagstaff, AZ") is None
    assert g.locate("2 Elm St, Tucson, AZ") is None
    assert len(refusing.queries) == 1


def test_lookups_are_a_second_apart(tmp_path):
    clock = Clock()
    nominatim = FakeNominatim()
    g = _geocoder(tmp_path / "c.json", nominatim, clock=clock)

    for address in ("A St", "B St", "C St"):
        g.locate(address)

    assert clock.slept == [pytest.approx(1.0), pytest.approx(1.0)]


def test_a_run_makes_only_a_few_lookups_and_leaves_the_rest_for_later(tmp_path):
    cache = tmp_path / "c.json"
    addresses = [f"{n} Main St" for n in range(geocode.MAX_LOOKUPS_PER_RUN + 2)]
    nominatim = FakeNominatim({a: FLAGSTAFF for a in addresses})

    g = _geocoder(cache, nominatim)
    found = [g.locate(a) for a in addresses]
    g.save()

    assert found.count(FLAGSTAFF) == geocode.MAX_LOOKUPS_PER_RUN
    assert found[-2:] == [None, None]

    later = _geocoder(cache, nominatim)
    assert [later.locate(a) for a in addresses] == [FLAGSTAFF] * len(addresses)


def test_searches_prefer_places_near_home_without_excluding_the_rest(tmp_path):
    nominatim = FakeNominatim()

    _geocoder(tmp_path / "c.json", nominatim).locate("Starbucks")

    params = nominatim.params[0]
    west, north, east, south = map(float, params["viewbox"].split(","))
    assert west < HOME[1] < east and south < HOME[0] < north
    assert "bounded" not in params  # bounded=1 would turn the preference into a filter


def test_moving_home_forgets_where_addresses_were(tmp_path):
    cache = tmp_path / "geocode_cache.json"
    nominatim = FakeNominatim({"Starbucks": (33.45, -112.35)})
    g = _geocoder(cache, nominatim)
    g.locate("Starbucks")
    g.save()

    moved = _geocoder(cache, nominatim, near=(47.61, -122.33))
    moved.locate("Starbucks")

    assert nominatim.queries == ["Starbucks", "Starbucks"]


@pytest.mark.parametrize("damage", ["", "{not json", "[]", '{"places": 5}'])
def test_a_damaged_cache_file_is_started_afresh(tmp_path, damage):
    cache = tmp_path / "geocode_cache.json"
    cache.write_text(damage, encoding="utf-8")
    nominatim = FakeNominatim({"1 Main St": FLAGSTAFF})

    g = _geocoder(cache, nominatim)
    assert g.locate("1 Main St") == FLAGSTAFF
    g.save()

    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["places"]["1 main st"]["lat"] == FLAGSTAFF[0]


def test_a_run_with_nothing_new_does_not_write_the_cache(tmp_path):
    cache = tmp_path / "geocode_cache.json"
    g = _geocoder(cache, FakeNominatim())
    g.save()
    assert not cache.exists()


def test_distance_miles():
    assert distance_miles(HOME, HOME) == 0
    # Goodyear to Flagstaff is about 128 miles as the crow flies.
    assert distance_miles(HOME, FLAGSTAFF) == pytest.approx(128, abs=3)
