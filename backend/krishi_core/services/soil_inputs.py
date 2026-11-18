"""
Turn a farmer's soil test into inputs the crop-recommendation model understands.

Why this exists
---------------
The model's N/P/K features are on the *crop nutrient requirement* scale (the
``N_required`` / ``P_required`` / ``K_required`` columns of
``data/01_crop_profile.csv``: e.g. Maize 120/60/40, ChickPea 20/50/20). Farmers
enter *Soil Health Card* values instead: plant-available nutrients in kg/ha,
where "medium" nitrogen is 280-560. Feeding those numbers straight in puts them
outside anything the model saw (N > 250), so it saturated and gave biased
rankings.

There is no exact formula between the two quantities, so we use the standard
agronomic idea of a *fertility class*: Soil Health Card bands say whether each
nutrient is Low / Medium / High, and we place the value at the same relative
position on the model's scale (piecewise-linear, monotonic). Low-N soils then
point towards low-N crops (legumes), high-N soils towards heavy feeders, and
inputs always stay inside the range the model learned.

When the farmer has no soil test, we do NOT invent numbers. ``soil_scenarios``
returns a small grid of typical soils so the caller can average the model's
predictions over them: the ranking then reflects climate, season and region
only, and the response says the soil was assumed.
"""
import itertools
import os

import numpy as np

# Soil Health Card "medium" bands (kg/ha), the same ones the farm form shows as
# "Ideal": N 280-560, P (P2O5) 22-56, K (K2O) 120-340. Below = Low, above = High.
SOIL_TEST_BANDS = {
    "N": (280.0, 560.0),
    "P": (22.0, 56.0),
    "K": (120.0, 340.0),
}

# Fallback model-scale anchors (min, q35, q70, q95, max) if the CSV can't be read.
_DEFAULT_MODEL_ANCHORS = {
    "N": (20.0, 54.0, 120.0, 196.0, 250.0),
    "P": (20.0, 44.0, 60.0, 80.0, 100.0),
    "K": (20.0, 30.0, 58.0, 144.0, 300.0),
}
_CSV_COLUMN = {"N": "N_required", "P": "P_required", "K": "K_required"}

# pH values tried when the soil pH is unknown (typical Indian agricultural range).
_PH_GRID = (6.0, 6.8, 7.5)


def _load_model_anchors():
    """Model-scale anchor points from the crop profile the model's N/P/K come from."""
    try:
        import pandas as pd
        from django.conf import settings
        path = os.path.join(settings.BASE_DIR, "krishi_core", "data", "01_crop_profile.csv")
        df = pd.read_csv(path)
        anchors = {}
        for nutrient, col in _CSV_COLUMN.items():
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            anchors[nutrient] = (float(s.min()), float(s.quantile(0.35)), float(s.quantile(0.70)),
                                 float(s.quantile(0.95)), float(s.max()))
        return anchors
    except Exception:
        return dict(_DEFAULT_MODEL_ANCHORS)


_MODEL_ANCHORS = _load_model_anchors()


def fertility_class(nutrient, value):
    """'Low' / 'Medium' / 'High' per Soil Health Card bands, or None if unknown."""
    if value is None:
        return None
    low_max, high_min = SOIL_TEST_BANDS[nutrient]
    if value < low_max:
        return "Low"
    if value > high_min:
        return "High"
    return "Medium"


def to_model_scale(nutrient, value):
    """Map a soil-test value (kg/ha) onto the model's N/P/K scale.

    Anchors: 0 -> model min, Low/Medium boundary -> model 35th percentile,
    Medium/High boundary -> model 70th percentile, twice that -> 95th
    percentile; values beyond are capped at the model's maximum.
    """
    low_max, high_min = SOIL_TEST_BANDS[nutrient]
    m_min, m_q35, m_q70, m_q95, m_max = _MODEL_ANCHORS[nutrient]
    xs = [0.0, low_max, high_min, 2.0 * high_min]
    ys = [m_min, m_q35, m_q70, m_q95]
    mapped = float(np.interp(max(0.0, float(value)), xs, ys, right=m_q95))
    return round(min(mapped, m_max), 1)


def _grid(nutrient):
    """Low / typical / high values on the model scale, for an unknown nutrient."""
    m_min, m_q35, m_q70, m_q95, _ = _MODEL_ANCHORS[nutrient]
    return (round((m_min + m_q35) / 2, 1), round((m_q35 + m_q70) / 2, 1), round((m_q70 + m_q95) / 2, 1))


def soil_scenarios(nitrogen=None, phosphorus=None, potassium=None, ph=None):
    """Model-ready soil rows plus a description of what was known.

    Returns ``(rows, basis, classes)``:
      rows    -- list of {"N", "P", "K", "ph"} dicts on the model scale. One row
                 when the full soil test is known; a grid over the unknown
                 values otherwise (average the model's probabilities over it).
      basis   -- "soil_test" (all four known), "partial", or "assumed" (none).
      classes -- {"N": "Low"|"Medium"|"High"|None, "P": ..., "K": ...}
    """
    given = {"N": nitrogen, "P": phosphorus, "K": potassium}
    options = {}
    for nutrient, value in given.items():
        options[nutrient] = [to_model_scale(nutrient, value)] if value is not None else list(_grid(nutrient))
    options["ph"] = [round(float(ph), 2)] if ph is not None else list(_PH_GRID)

    rows = [dict(zip(("N", "P", "K", "ph"), combo))
            for combo in itertools.product(options["N"], options["P"], options["K"], options["ph"])]

    known = sum(v is not None for v in (nitrogen, phosphorus, potassium, ph))
    basis = "soil_test" if known == 4 else ("assumed" if known == 0 else "partial")
    classes = {n: fertility_class(n, v) for n, v in given.items()}
    return rows, basis, classes
