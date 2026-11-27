"""Turning an event's address into a place on the map, remembered on disk.

main uses this to give an event the weather where it's happening instead of
at home. The address is whatever was typed into the event's location field,
so most of what's here is about asking as little as possible:

  - Every answer is kept in geocode_cache.json next to state.json, so an
    address is looked up once, not on every render. Addresses don't move, and
    the free geocoder used (OpenStreetMap's Nominatim, as for travel times)
    asks its clients to cache.
  - An address it couldn't place ("Mom's", "Room 4B") is remembered as well,
    and not asked about again for NOT_FOUND_RETRY_AFTER.
  - A meeting link, "Zoom", "Teams" and the like are never sent at all.
  - A failed request (no internet, the service down or turning us away) ends
    the lookups for the rest of the run, instead of every address waiting out
    its own timeout. Nothing is remembered from it, so a later run asks again.
  - Requests are spaced MIN_REQUEST_INTERVAL_S apart (Nominatim allows one a
    second), and a run makes at most MAX_LOOKUPS_PER_RUN of them, so a
    calendar full of new addresses can't hold a button press up for long. The
    rest are looked up on later runs.

An address that isn't placed just gets home's weather, so a missed lookup
costs little. A wrong one costs more: the event shows some other town's
weather. So searches prefer places near home, and "Starbucks" finds the one
down the road rather than one three states away. For the same reason the
cache belongs to one home: moving the display (a new weather latitude and
longitude) starts it afresh, since "Starbucks" then means somewhere else.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple

import requests

CACHE_FILE_NAME = "geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "inkycal/1.0"
REQUEST_TIMEOUT_S = 8

MIN_REQUEST_INTERVAL_S = 1.0
MAX_LOOKUPS_PER_RUN = 5
NOT_FOUND_RETRY_AFTER = timedelta(days=30)

# How far the area searches prefer reaches either side of home, in degrees of
# latitude and longitude: about 70 miles. It's a preference, not a limit; an
# address in another state still finds that state.
PREFERRED_AREA_DEGREES = 1.0

_EARTH_RADIUS_MILES = 3958.8

_LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_NOT_A_PLACE_RE = re.compile(
    r"\b(zoom|google meet|meet\.google|microsoft teams|teams meeting|webex|facetime|skype|phone|online|virtual)\b",
    re.IGNORECASE,
)

LatLon = Tuple[float, float]


def distance_miles(a: LatLon, b: LatLon) -> float:
    """The great-circle distance between two (latitude, longitude) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1.0, h)))


def _query(address: str) -> str:
    # iCloud puts a place's name and its address on separate lines.
    lines = (" ".join(line.split()) for line in address.splitlines())
    return ", ".join(line for line in lines if line).strip(" ,")


def _not_a_place(query: str) -> bool:
    return bool(_LINK_RE.search(query) or _NOT_A_PLACE_RE.search(query))


def _default_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


class Geocoder:
    """Looks addresses up for one run, keeping every answer in `cache_path`.

    `near` is home's (latitude, longitude): searches prefer places near it.
    Call save() once the run's lookups are done; nothing is written before.
    """

    def __init__(
        self,
        cache_path: Optional[str],
        near: LatLon,
        *,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._cache_path = cache_path
        self._near = [round(near[0], 2), round(near[1], 2)]
        self._session = session
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
        # Read from disk at the first lookup: most runs draw nothing, and
        # never need it.
        self._places: Optional[Dict[str, dict]] = None
        self._dirty = False
        self._offline = False
        self._lookups = 0
        self._last_request: Optional[float] = None

    def locate(self, address: str) -> Optional[LatLon]:
        """Where `address` is, or None if it couldn't be placed (or wasn't asked about)."""
        query = _query(address or "")
        if not query or _not_a_place(query):
            return None
        key = query.casefold()
        places = self._load()
        entry = places.get(key)
        if entry is not None and self._still_good(entry):
            return _coords(entry)
        if self._offline or self._lookups >= MAX_LOOKUPS_PER_RUN:
            return None

        self._lookups += 1
        try:
            coords = self._ask(query)
        except Exception as e:
            print(f"Address lookup failed; events without a known place get home weather this run. Error: {e}")
            self._offline = True
            return None
        places[key] = {
            "lat": coords[0] if coords else None,
            "lon": coords[1] if coords else None,
            "checked": self._now().isoformat(),
        }
        self._dirty = True
        return coords

    def save(self) -> None:
        """Write this run's new answers to the cache. A failure only costs lookups later."""
        if not self._dirty or not self._cache_path:
            return
        payload = {"near": self._near, "places": self._places}
        tmp = f"{self._cache_path}.{os.getpid()}.tmp"
        try:
            os.makedirs(os.path.dirname(self._cache_path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, self._cache_path)
            self._dirty = False
        except OSError as e:
            print(f"Could not save address lookups to {self._cache_path}: {e}")
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _still_good(self, entry: dict) -> bool:
        if _coords(entry) is not None:
            return True
        try:
            checked = datetime.fromisoformat(str(entry.get("checked")))
        except ValueError:
            return False
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return self._now() - checked < NOT_FOUND_RETRY_AFTER

    def _load(self) -> Dict[str, dict]:
        """The cached answers. Like state.json, a damaged file is started afresh, never raised."""
        if self._places is not None:
            return self._places
        self._places = {}
        if not self._cache_path or not os.path.exists(self._cache_path):
            return self._places
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f"Could not read address lookups at {self._cache_path} ({e}); starting afresh")
            return self._places
        if not isinstance(data, dict) or not isinstance(data.get("places"), dict):
            return self._places
        if data.get("near") != self._near:
            print("Home's coordinates changed; looking event addresses up afresh")
            self._dirty = True  # so the stale answers are replaced on disk
            return self._places
        self._places = {k: v for k, v in data["places"].items() if isinstance(v, dict)}
        return self._places

    def _ask(self, query: str) -> Optional[LatLon]:
        if self._session is None:
            self._session = _default_session()
        if self._last_request is not None:
            wait = MIN_REQUEST_INTERVAL_S - (self._monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        lat, lon = self._near
        d = PREFERRED_AREA_DEGREES
        try:
            resp = self._session.get(
                NOMINATIM_URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                    # A preferred area, not a filter: Nominatim only
                    # excludes what's outside it when bounded=1.
                    "viewbox": f"{lon - d},{lat + d},{lon + d},{lat - d}",
                },
                timeout=REQUEST_TIMEOUT_S,
            )
        finally:
            self._last_request = self._monotonic()
        resp.raise_for_status()
        results = resp.json()
        if not isinstance(results, list):
            raise ValueError("Nominatim's answer was not a list of places")
        if not results:
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])


def _coords(entry: dict) -> Optional[LatLon]:
    lat, lon = entry.get("lat"), entry.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lat), float(lon)
    return None
