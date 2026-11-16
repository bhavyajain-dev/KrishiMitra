import os
import logging
import joblib
import pandas as pd
from django.conf import settings

logger = logging.getLogger("core.services.fertilizer")

# Correct absolute paths to the model artifacts
MODEL_DIR = os.path.join(settings.BASE_DIR, "krishi_core", "ml_models", "artifacts")
MODEL_PATH = os.path.join(MODEL_DIR, "fertilizer_model.pkl")
PREPROCESSOR_PATH = os.path.join(MODEL_DIR, "fertilizer_feature_preprocessor.pkl")
LABEL_ENCODER_PATH = os.path.join(MODEL_DIR, "fertilizer_label_encoder.pkl")


class FertilizerRecommendationService:

    def __init__(self):
        self.model = None
        self.encoder = None
        # Internal state flag: True only when the model artifacts loaded OK.
        self._loaded = False
        self._load_models()

    def _load_models(self):
        """Load the model + label encoder if the artifacts exist.

        Missing or unreadable artifacts are logged and leave the service in an
        'unavailable' state, rather than raising during import (which would
        crash Django startup). When valid artifacts are later supplied, loading
        succeeds and behavior is identical to before.
        """
        try:
            self.model = joblib.load(MODEL_PATH)
            self.encoder = joblib.load(LABEL_ENCODER_PATH)
            self._loaded = True
            logger.info("Fertilizer model loaded successfully.")
        except Exception as e:
            logger.error(
                f"Fertilizer model unavailable (could not load from {MODEL_DIR}): {e}"
            )

    def _get_kb_recommendation(self, crop_type, stage):
        """Consult verified ICAR agronomic CSV knowledge base when model binary is unavailable."""
        csv_path = os.path.join(settings.BASE_DIR, "krishi_core", "data", "06_crop_fertilizer_plan.csv")
        if not os.path.exists(csv_path):
            return "N/A (Agronomic knowledge base file not found)"

        try:
            df = pd.read_csv(csv_path)
            crop_lower = str(crop_type or "").strip().lower()
            stage_lower = str(stage or "").strip().lower()

            # Filter rows by crop
            crop_rows = df[df["crop_name"].str.strip().str.lower() == crop_lower]
            if crop_rows.empty:
                # Try substring match
                crop_rows = df[df["crop_name"].str.strip().str.lower().str.contains(crop_lower, regex=False)]

            if crop_rows.empty:
                return f"N/A (No verified ICAR fertilizer plan available for {crop_type})"

            # Try matching growth stage
            matched_row = None
            if stage_lower:
                for _, row in crop_rows.iterrows():
                    r_stage = str(row.get("stage", "")).lower()
                    if stage_lower in r_stage or any(s in r_stage for s in stage_lower.split()):
                        matched_row = row
                        break

            # Fallback to basal or first row for this crop
            if matched_row is None:
                matched_row = crop_rows.iloc[0]

            products = str(matched_row.get("products_and_dose", "")).strip()
            purpose = str(matched_row.get("purpose", "")).strip()
            matched_stage = str(matched_row.get("stage", "")).strip()

            return {
                "recommended_fertilizer": products,
                "stage": matched_stage,
                "purpose": purpose,
                "source": "knowledge_base",
                "is_ml_prediction": False,
                "note": "Verified ICAR agronomic package of practices",
            }
        except Exception as e:
            logger.error("Failed to query fertilizer knowledge base: %s", e)
            return "N/A (Knowledge base query error)"

    def predict(self, data):
        if not self._loaded or self.model is None:
            return self._get_kb_recommendation(
                data.get("Crop_Type", "Wheat"),
                data.get("Crop_Growth_Stage", "Vegetative")
            )

        try:
            features = pd.DataFrame([{
                "Soil_Type": data.get("Soil_Type", "Black"),
                "Crop_Type": data.get("Crop_Type", "Wheat"),
                "Crop_Growth_Stage": data.get("Crop_Growth_Stage", "Pre-emergence"),
                "Season": data.get("Season", "Kharif"),
                "Irrigation_Type": data.get("Irrigation_Type", "Drip"),
                "Previous_Crop": data.get("Previous_Crop", "Fallow"),
                "Region": data.get("Region", "Maharashtra"),
                "Soil_pH": float(data.get("Soil_pH", 6.5)),
                "Soil_Moisture": float(data.get("Soil_Moisture", 40.0)),
                "Organic_Carbon": float(data.get("Organic_Carbon", 0.5)),
                "Electrical_Conductivity": float(data.get("Electrical_Conductivity", 0.4)),
                "Nitrogen_Level": float(data.get("Nitrogen_Level", 50.0)),
                "Phosphorus_Level": float(data.get("Phosphorus_Level", 30.0)),
                "Potassium_Level": float(data.get("Potassium_Level", 40.0)),
                "Temperature": float(data.get("Temperature", data.get("Temperature_C", 25.0))),
                "Humidity": float(data.get("Humidity", 60.0)),
                "Rainfall": float(data.get("Rainfall", data.get("Rainfall_mm", 100.0))),
                "Fertilizer_Used_Last_Season": data.get("Fertilizer_Used_Last_Season", "Urea"),
                "Yield_Last_Season": float(data.get("Yield_Last_Season", 2.5)),
            }])

            prediction = self.model.predict(features)[0]
            fertilizer = self.encoder.inverse_transform([prediction])[0]
            return {
                "recommended_fertilizer": fertilizer,
                "source": "ml_model",
                "is_ml_prediction": True,
                "note": "Machine Learning Model Prediction",
            }
        except Exception as e:
            logger.error("Fertilizer prediction failed: %s", e)
            return self._get_kb_recommendation(
                data.get("Crop_Type", "Wheat"),
                data.get("Crop_Growth_Stage", "Vegetative")
            )


fertilizer_service = FertilizerRecommendationService()
