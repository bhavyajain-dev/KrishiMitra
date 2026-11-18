import os
import logging
import threading
import joblib
import pandas as pd
from django.conf import settings

logger = logging.getLogger("core.services.yield")

MODEL_PATH = os.path.join(
    settings.BASE_DIR,
    "krishi_core",
    "ml_models",
    "artifacts",
    "crop_yield_model.pkl",
)


# App crop names (01_crop_profile.csv) -> names used in the yield model's
# training data ("Crop Yield in Indian States"). Without this, 11 app crops
# (Cotton, Soybean, Mustard, ...) were unknown to the model and silently
# ignored by its one-hot encoder, giving a generic, crop-agnostic number.
_CROP_ALIASES = {
    "castor": "Castor seed",
    "chickpea": "Gram",
    "chilli": "Dry chillies",
    "chillies": "Dry chillies",
    "cotton": "Cotton(lint)",
    "guar": "Guar seed",
    "mungbean": "Moong(Green Gram)",
    "moong": "Moong(Green Gram)",
    "mustard": "Rapeseed &Mustard",
    "pigeonpea": "Arhar/Tur",
    "arhar": "Arhar/Tur",
    "tur": "Arhar/Tur",
    "sesame": "Sesamum",
    "soybean": "Soyabean",
    "uradbean": "Urad",
    "paddy": "Rice",
}


class CropYieldPredictionService:

    def __init__(self):
        self.model = None
        # lower-cased name -> exact training category, per categorical column
        self._categories = {}
        # Internal state flag: True only when the model artifact loaded OK.
        self._loaded = False
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        """Thread-safe lazy loader called on first access."""
        if not self._loaded:
            with self._lock:
                if not self._loaded:
                    self._load_model()

    def _load_model(self):
        """Load the model artifact if it exists.

        A missing or unreadable artifact is logged and leaves the service in an
        'unavailable' state, rather than raising during import (which would
        crash Django startup). When a valid artifact is later supplied, loading
        succeeds and behavior is identical to before.
        """
        try:
            self.model = joblib.load(MODEL_PATH)
            self._categories = self._learned_categories(self.model)
            self._loaded = True
            logger.info("Crop yield model loaded successfully.")
        except Exception as e:
            logger.error(
                f"Crop yield model unavailable (could not load {MODEL_PATH}): {e}"
            )

    @staticmethod
    def _learned_categories(model):
        """Read the categories the model's one-hot encoder was trained on."""
        cats = {}
        try:
            reg = getattr(model, "regressor_", model)
            pre = reg.named_steps["pre"]
            for _name, tr, cols in pre.transformers_:
                cols = [cols] if isinstance(cols, str) else list(cols)
                enc = tr.named_steps[list(tr.named_steps)[-1]] if hasattr(tr, "named_steps") else tr
                if hasattr(enc, "categories_"):
                    for col, values in zip(cols, enc.categories_):
                        cats[col] = {str(v).strip().lower(): v for v in values}
        except Exception:
            logger.warning("Could not read yield model categories", exc_info=True)
        return cats

    def _canonical(self, column, value):
        """Map an app value to the exact training category (or None if unknown)."""
        known = self._categories.get(column)
        raw = str(value or "").strip()
        if not known:            # categories unreadable: pass through unchanged
            return raw
        key = raw.lower()
        if column == "Crop":
            key = _CROP_ALIASES.get(key.replace(" ", ""), raw).strip().lower()
        return known.get(key)

    def supports_crop(self, crop):
        self._ensure_loaded()
        return self._loaded and self._canonical("Crop", crop) is not None

    def predict(self, data):
        """Predicted yield in tonnes per hectare, or None for a crop the model
        has no training data for (e.g. Tomato, Fennel)."""
        self._ensure_loaded()
        if not self._loaded or self.model is None:
            return "N/A (Model unavailable)"

        crop = self._canonical("Crop", data["Crop"])
        if crop is None:
            return None
        season = self._canonical("Season", data["Season"]) or data["Season"]
        state = self._canonical("State", data["State"]) or data["State"]

        features = pd.DataFrame([{
            "Crop": crop,
            "Crop_Year": data["Crop_Year"],
            "Season": season,
            "State": state,
            "Area": data["Area"],
            "Annual_Rainfall": data["Annual_Rainfall"],
            "Fertilizer": data["Fertilizer"],
            "Pesticide": data["Pesticide"],
        }])

        prediction = self.model.predict(features)[0]

        return round(float(prediction), 2)


yield_service = CropYieldPredictionService()
