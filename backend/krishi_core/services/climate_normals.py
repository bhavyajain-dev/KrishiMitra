"""Seasonal climate normals per state (see scripts/build_climate_normals.py).

Used by the crop model only when the live climate lookup for the farm's
location fails, so recommendations still come from the trained model using
real (10-year average) climate data for the farm's state.
"""
import json
import os
from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=1)
def _load():
    path = os.path.join(settings.BASE_DIR, "krishi_core", "data", "state_climate_normals.json")
    try:
        with open(path) as f:
            return json.load(f).get("states", {})
    except (OSError, ValueError):
        return {}


def state_climate_normal(state_token, season_token):
    """{"temperature_C", "humidity_pct", "rainfall_mm"} for a model state token
    ("Punjab", "MP", ...) and season ("Kharif", "Rabi", "Summer", or combos),
    or None if unknown."""
    entry = _load().get(state_token or "")
    if not entry or not season_token:
        return None
    seasons = entry.get("seasons", {})
    normal = seasons.get(season_token) or seasons.get(str(season_token).split("/")[0])
    if not normal or None in (normal.get("temperature_C"), normal.get("humidity_pct"), normal.get("rainfall_mm")):
        return None
    return normal
