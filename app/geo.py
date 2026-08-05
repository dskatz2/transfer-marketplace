"""City/state-level great-circle distance between two worksites.

Backed by a bundled US city coordinate table (app/data/us_cities.csv,
~29.7k cities, MIT-licensed from kelvins/US-Cities-Database) rather than a
live geocoding API - no network call, no API key, no rate limit, and city
centroid precision is plenty for "roughly how far apart are these two
worksites" rather than turn-by-turn accuracy.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "data" / "us_cities.csv"
_EARTH_RADIUS_MILES = 3958.8


def _load_city_coords() -> dict[tuple[str, str], tuple[float, float]]:
    coords: dict[tuple[str, str], tuple[float, float]] = {}
    if not _DATA_PATH.exists():
        return coords
    with open(_DATA_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["city"].strip().lower(), row["state"].strip().upper())
            try:
                coords[key] = (float(row["lat"]), float(row["lon"]))
            except (KeyError, ValueError):
                continue
    return coords


_CITY_COORDS = _load_city_coords()


def _lookup(city: str | None, state: str | None) -> tuple[float, float] | None:
    if not city or not state:
        return None
    return _CITY_COORDS.get((city.strip().lower(), state.strip().upper()))


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def distance_miles(city1: str | None, state1: str | None, city2: str | None, state2: str | None) -> float | None:
    """Returns None (rather than raising) when either city/state can't be
    resolved - callers should render that as "unknown", not zero."""
    p1 = _lookup(city1, state1)
    p2 = _lookup(city2, state2)
    if p1 is None or p2 is None:
        return None
    return round(haversine_miles(p1[0], p1[1], p2[0], p2[1]), 1)
