from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import requests


@dataclass
class TravelEstimate:
    minutes: int
    text: str


class TravelTimeResolver:
    """Resolves travel time between two address strings with simple in-memory caching."""

    def __init__(self, user_agent: str = "inkycal/1.0") -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._geocode_cache: Dict[str, Optional[Tuple[float, float]]] = {}
        self._duration_cache: Dict[Tuple[str, str], Optional[TravelEstimate]] = {}

    def estimate(self, origin: str, destination: str) -> Optional[TravelEstimate]:
        origin_norm = _normalize(origin)
        destination_norm = _normalize(destination)
        if not origin_norm or not destination_norm:
            return None

        cache_key = (origin_norm, destination_norm)
        if cache_key in self._duration_cache:
            return self._duration_cache[cache_key]

        if origin_norm == destination_norm:
            estimate = TravelEstimate(minutes=0, text="0 min")
            self._duration_cache[cache_key] = estimate
            return estimate

        origin_latlon = self._geocode(origin_norm)
        destination_latlon = self._geocode(destination_norm)
        if not origin_latlon or not destination_latlon:
            self._duration_cache[cache_key] = None
            return None

        try:
            (origin_lat, origin_lon) = origin_latlon
            (dest_lat, dest_lon) = destination_latlon
            resp = self._session.get(
                (
                    "https://router.project-osrm.org/route/v1/driving/"
                    f"{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
                ),
                params={"overview": "false"},
                timeout=8,
            )
            resp.raise_for_status()
            payload = resp.json()
            routes = payload.get("routes") or []
            if not routes:
                self._duration_cache[cache_key] = None
                return None
            seconds = float(routes[0].get("duration", 0))
            minutes = max(1, round(seconds / 60))
            estimate = TravelEstimate(minutes=minutes, text=f"{minutes} min")
            self._duration_cache[cache_key] = estimate
            return estimate
        except Exception:
            self._duration_cache[cache_key] = None
            return None

    def _geocode(self, address: str) -> Optional[Tuple[float, float]]:
        if address in self._geocode_cache:
            return self._geocode_cache[address]
        try:
            resp = self._session.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": address, "format": "json", "limit": 1},
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                self._geocode_cache[address] = None
                return None
            item = results[0]
            lat = float(item["lat"])
            lon = float(item["lon"])
            value = (lat, lon)
            self._geocode_cache[address] = value
            return value
        except Exception:
            self._geocode_cache[address] = None
            return None


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())
