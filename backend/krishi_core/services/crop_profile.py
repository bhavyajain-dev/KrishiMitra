"""Crop-specific explanation text built from data/01_crop_profile.csv."""
import os
import re
from functools import lru_cache

from django.conf import settings

_DROUGHT_TEXT = {
    "high": "Tolerates dry spells well.",
    "medium": "Moderately drought tolerant.",
    "low": "Needs reliable irrigation.",
}


@lru_cache(maxsize=1)
def _profiles():
    import pandas as pd
    path = os.path.join(settings.BASE_DIR, "krishi_core", "data", "01_crop_profile.csv")
    try:
        df = pd.read_csv(path)
    except (OSError, ValueError):
        return {}
    return {str(r["crop_name"]).strip().lower(): r.to_dict() for _, r in df.iterrows()}


def _num(v):
    f = float(v)
    return int(f) if f.is_integer() else f


_PRETTY = {"chickpea": "Chickpea", "mungbean": "Mung bean", "uradbean": "Urad bean",
           "kidneybeans": "Kidney beans", "pigeonpeas": "Pigeon pea", "mothbeans": "Moth bean"}


def pretty_crop_name(name):
    """Readable crop name: "ChickPea" -> "Chickpea", "MungBean" -> "Mung bean"."""
    raw = str(name or "").strip()
    key = raw.lower().replace(" ", "")
    if key in _PRETTY:
        return _PRETTY[key]
    if " " not in raw and re.search(r"[a-z][A-Z]", raw):
        words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw).split()
        return " ".join([words[0]] + [w.lower() for w in words[1:]])
    return raw


def crop_reason(crop_name, ph=None):
    """One or two sentences on why this crop fits, or None if not profiled."""
    p = _profiles().get(str(crop_name or "").strip().lower())
    if not p:
        return None
    try:
        season = str(p["season"]).strip()
        season_txt = "an annual crop" if season.lower() == "annual" else f"a {season} crop"
        ph_lo, ph_hi = float(p["ideal_ph_min"]), float(p["ideal_ph_max"])
        text = (f"{pretty_crop_name(p['crop_name'])} is {season_txt} that grows best at "
                f"{_num(p['temp_min'])}–{_num(p['temp_max'])} °C in soil pH {ph_lo:.1f}–{ph_hi:.1f}.")
        if ph is not None:
            if ph_lo <= ph <= ph_hi:
                text += f" Your soil pH {ph:g} is in its ideal range."
            else:
                side = "above" if ph > ph_hi else "below"
                text += f" Your soil pH {ph:g} is {side} its ideal range."
        drought = _DROUGHT_TEXT.get(str(p.get("drought_tolerance", "")).strip().lower())
        if drought:
            text += f" {drought}"
        return text
    except (KeyError, TypeError, ValueError):
        return None
