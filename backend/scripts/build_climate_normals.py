#!/usr/bin/env python
"""
Build krishi_core/data/state_climate_normals.json.

Seasonal climate normals (10-year averages) for each state the crop model was
trained on, taken from the Open-Meteo Archive API at one representative
agricultural centre per state. The crop model uses these only when the live
climate lookup for the farm's exact location fails (e.g. the hosting
provider's IP is rate-limited), so it can still run on real climate data
instead of falling back to rules.

Re-run any time:  python scripts/build_climate_normals.py
"""
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "krishimitra_ml.settings")
import django  # noqa: E402
django.setup()

from krishi_core.services.openmeteo_service import (  # noqa: E402
    ARCHIVE_URL, SEASON_MONTHS, _aggregate_seasonal_climatology,
)

YEARS = 10
SEASONS = ("Kharif", "Rabi", "Summer")

# Crop-model state token -> (representative agricultural centre, lat, lon)
CENTRES = {
    "AndhraPradesh": ("Vijayawada", 16.51, 80.65),
    "Bihar": ("Patna", 25.59, 85.14),
    "Gujarat": ("Ahmedabad", 23.02, 72.57),
    "Haryana": ("Karnal", 29.69, 76.99),
    "Karnataka": ("Davanagere", 14.46, 75.92),
    "MP": ("Bhopal", 23.26, 77.41),
    "Maharashtra": ("Aurangabad", 19.88, 75.34),
    "Punjab": ("Ludhiana", 30.90, 75.85),
    "Rajasthan": ("Ajmer", 26.45, 74.64),
    "TamilNadu": ("Tiruchirappalli", 10.79, 78.70),
    "Telangana": ("Hyderabad", 17.39, 78.49),
    "UP": ("Lucknow", 26.85, 80.95),
    "WestBengal": ("Bardhaman", 23.23, 87.86),
}


def main():
    end = date.today().replace(day=1) - timedelta(days=1)
    start = date(end.year - YEARS, 1, 1)
    out = {
        "_about": (
            "10-year seasonal climate normals per state (Open-Meteo Archive API, "
            "one agricultural centre per state). Used by the crop model only when "
            "the live climate lookup for a farm fails."
        ),
        "_period": f"{start.isoformat()}..{end.isoformat()}",
        "states": {},
    }
    for token, (city, lat, lon) in CENTRES.items():
        resp = requests.get(ARCHIVE_URL, params={
            "latitude": lat, "longitude": lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": "precipitation_sum,temperature_2m_mean,relative_humidity_2m_mean",
            "timezone": "Asia/Kolkata",
        }, timeout=60)
        resp.raise_for_status()
        daily = resp.json()["daily"]
        entry = {"centre": city, "latitude": lat, "longitude": lon, "seasons": {}}
        for season in SEASONS:
            months = set(SEASON_MONTHS[season])
            agg = _aggregate_seasonal_climatology(
                daily["time"], daily["precipitation_sum"], daily["temperature_2m_mean"], months)
            hum = [h for t, h in zip(daily["time"], daily["relative_humidity_2m_mean"])
                   if h is not None and int(t[5:7]) in months]
            entry["seasons"][season] = {
                "rainfall_mm": agg["rainfall_mm"],
                "temperature_C": agg["temperature_C"],
                "humidity_pct": round(sum(hum) / len(hum), 1) if hum else None,
            }
        out["states"][token] = entry
        print(f"{token:14} {city:15} " + "  ".join(
            f"{s}: {v['temperature_C']}C {v['rainfall_mm']}mm {v['humidity_pct']}%"
            for s, v in entry["seasons"].items()))

    path = BASE_DIR / "krishi_core" / "data" / "state_climate_normals.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
