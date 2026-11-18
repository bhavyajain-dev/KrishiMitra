"""
Django REST Framework views — one-to-one replacement for the old Flask routes:

    Flask route                    -> DRF view (same URL, same JSON contract)
    ---------------------------------------------------------------------
    POST /api/retrieve             -> RetrieveView
    POST /api/soil_recommend       -> SoilRecommendView
    POST /api/crop_stage_tips      -> CropStageTipsView
    POST /api/predict_disease      -> PredictDiseaseView
    GET  /api/health                -> HealthView
    GET  /api/weather                -> WeatherView

Every response shape is unchanged, so the Node backend (which calls this
service) needs zero changes.
"""
import io
import json
import logging
import re
import time
import traceback

import numpy as np
import pandas as pd
import requests
from PIL import Image

from django.conf import settings
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from .parsers import ObjectJSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import ml_loader
from .throttles import AIRateThrottle
from .utils import CROPS, WATER_COMPAT, get_crop_meta, check_image_quality, extract_section
from .serializers import (
    RetrieveRequestSerializer,
    SoilRecommendRequestSerializer,
    CropStageTipsRequestSerializer,
)
from .services.fertilizer_service import fertilizer_service
from .services.irrigation_service import irrigation_service
from .services.crop_recommendation_service import (
    crop_recommendation_service,
    canonical_season,
    normalize_state_token,
)

logger = logging.getLogger("core.views")


class RetrieveView(APIView):
    """RAG semantic search over the ChromaDB knowledge base using the advanced RAGRetriever."""
    parser_classes = [ObjectJSONParser]

    def post(self, request):
        from krishi_core.services.ai_engine.rag_retriever import rag_retriever
        
        serializer = RetrieveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]
        n_results = serializer.validated_data.get("n_results", 5)
        # We can pass an optional target_crop if the frontend provides it in the future
        target_crop = request.data.get("target_crop", "")

        try:
            context = rag_retriever.search(query=query, k=n_results, target_crop=target_crop)
            
            # The previous frontend expected raw_results and distances, but we now format a cohesive context.
            # We return empty raw arrays to not break existing frontend expectations if any.
            return Response({
                "context": context,
                "distances": [], 
                "raw_results": {"documents": [], "distances": []} 
            })
            
        except Exception as e:
            logger.error("Error during advanced retrieval: %s", traceback.format_exc())
            return Response({"error": str(e)}, status=500)


class SoilRecommendView(APIView):
    """
    Soil-powered crop recommendation engine (Unit 4/5: regression + classification
    features feed a RandomForest classifier; falls back to a rule-based heuristic
    scorer if the model isn't loaded).
    """
    parser_classes = [ObjectJSONParser]
    throttle_classes = [AIRateThrottle]

    def post(self, request):
        serializer = SoilRecommendRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        ph = d["ph"]
        nitrogen = d["nitrogen"]
        phosphorus = d["phosphorus"]
        potassium = d["potassium"]
        # EC / organic carbon are optional. Rules below need a number, so a
        # neutral 0.5 % is used internally, but only values the farmer entered
        # are ever shown or sent to the AI summary.
        org_carbon_given = d["organicCarbon"]
        ec_given = d["ec"]
        org_carbon = org_carbon_given if org_carbon_given is not None else 0.5
        season_in = d["season"].lower()
        area_acres = d["areaAcres"]
        water_avail = d["waterAvailability"].lower()

        # The farm may have no soil test. Never invent one: the model averages
        # over typical soils instead (see services/soil_inputs.py), and the
        # response says which basis was used.
        from krishi_core.services.soil_inputs import soil_scenarios
        soil_rows, soil_basis, soil_classes = soil_scenarios(nitrogen, phosphorus, potassium, ph)
        # Rule-based parts (heuristic fallback, pH match bar) need one pH value.
        ph_rule = ph if ph is not None else 6.8

        collection = ml_loader.state.get("collection")

        # Canonical path: the trained crop-recommendation model. Used ONLY when
        # it is loaded AND all nine real features can be sourced — soil NPK + pH
        # and season come from the form; state and season-aligned climatological
        # temperature / humidity / rainfall come from the farm's real location.
        # If ANY real input is missing, we fall back to the heuristic rather
        # than fabricating temperature / humidity / rainfall / state.
        results = self._model_recommend(
            request, ph, nitrogen, phosphorus, potassium,
            org_carbon, season_in, area_acres, collection,
            soil_rows=soil_rows,
        )
        used_model = bool(results)

        if not results:
            # Rule-based heuristic fallback (best true match on soil/water data).
            results = self._heuristic_fallback(ph_rule, org_carbon, season_in, area_acres, water_avail, collection,
                                               ph_known=ph is not None)
        if ph is None:
            # No soil test: don't show a made-up soil-match score.
            for r in results:
                r["soilMatchPct"] = None

        # Sort primarily by suitabilityScore (best match)
        results.sort(key=lambda x: x["suitabilityScore"], reverse=True)
        
        # Keep top 5
        results = results[:5]
        if results:
            results[0]["isTopPick"] = True
            
            # Predict Fertilizer and Irrigation for top picks
            for r in results:
                ml_data = {
                    "Soil_Type": d.get("soilType", "Black"),
                    "Crop_Type": r["cropName"].capitalize(),
                    "Crop_Growth_Stage": "Pre-emergence",
                    "Season": season_in.capitalize(),
                    "Irrigation_Type": d.get("irrigationType", "Drip"),
                    "Previous_Crop": d.get("previousCrop", "Fallow"),
                    "Region": d.get("state", "Maharashtra"),
                    "Soil_pH": ph,
                    "Soil_Moisture": 40.0,
                    "Organic_Carbon": org_carbon_given,
                    "Electrical_Conductivity": ec_given,
                    "Nitrogen_Level": nitrogen,
                    "Phosphorus_Level": phosphorus,
                    "Potassium_Level": potassium,
                    "Temperature_C": d.get("temperature", 25.0),
                    "Temperature": d.get("temperature", 25.0),
                    "Humidity": d.get("humidity", 60.0),
                    "Rainfall_mm": d.get("rainfall", 100.0),
                    "Rainfall": d.get("rainfall", 100.0),
                    "Sunlight_Hours": 7.0,
                    "Wind_Speed_kmh": 10.0,
                    "Water_Source": d.get("waterSource", "Borewell"),
                    "Field_Area_hectare": area_acres * 0.404686,  # convert acres to hectares
                    "Mulching_Used": d.get("mulchingUsed", "No"),
                    "Previous_Irrigation_mm": 20.0,
                    "Forecast_Rainfall_7Days_mm": 15.0,
                    "Forecast_Temp_7Days_Avg": d.get("temperature", 25.0),
                    "Fertilizer_Used_Last_Season": d.get("fertilizerUsedLastSeason", "Urea"),
                    "Yield_Last_Season": 2.5,
                }
                ml_data = {k: v for k, v in ml_data.items() if v is not None}
                r["suggestedFertilizer"] = fertilizer_service.predict(ml_data)
                r["irrigationPrediction"] = irrigation_service.predict(ml_data)
            
        if soil_basis == "assumed":
            soil_desc = "No soil test was provided, so this ranking is based on your local climate, season and region."
        else:
            parts = []
            if ph is not None:
                parts.append(f"pH {ph}")
            for label, key, val in (("Nitrogen", "N", nitrogen), ("Phosphorus", "P", phosphorus), ("Potassium", "K", potassium)):
                if val is not None:
                    parts.append(f"{label} {val:g} kg/ha ({soil_classes[key]})")
            soil_desc = "Soil test: " + ", ".join(parts) + "."

        extra_bits = []
        if ec_given is not None:
            extra_bits.append(f"EC {ec_given:g} dS/m")
        if org_carbon_given is not None:
            extra_bits.append(f"Organic carbon {org_carbon_given:g}%")
        extra_soil = (" " + ", ".join(extra_bits) + ".") if extra_bits else ""

        llm_summary = ""
        try:
            from krishi_core.services.ai_engine.llm_service import llm_service
            prompt = f"""
You are an agricultural expert. A farmer is asking for crop recommendations for their land.
{soil_desc}{extra_soil}
The top crops recommended by our engine are:
{', '.join([r['cropName'] for r in results])}

Mention only the soil values listed above; do not assume or invent any other soil readings.
Write a short, engaging 2-paragraph summary directly to the farmer. Explain why the top pick ({results[0]['cropName']}) is the best choice based on their soil and local climate, and briefly mention the alternatives.{" Also encourage them to add their Soil Health Card values for a more precise recommendation." if soil_basis != "soil_test" else ""}
Keep it conversational, encouraging, and formatted in plain text (no markdown formatting needed).
"""
            # Strict short timeout (1.0s connect, 2.5s read) to ensure fast endpoint response
            llm_summary_resp = llm_service.generate_response(prompt, force_json=False, timeout=(3.0, 8.0))
            if isinstance(llm_summary_resp, dict) and 'error' not in llm_summary_resp:
                llm_summary = llm_summary_resp.get('answer', llm_summary_resp.get('text', str(llm_summary_resp)))
            elif isinstance(llm_summary_resp, str) and llm_summary_resp.strip() and "AI service is currently unavailable" not in llm_summary_resp:
                llm_summary = llm_summary_resp.strip()
        except Exception as e:
            logger.warning(f"Fast LLM summary unavailable: {e}")

        # Deterministic agronomic explanation if LLM is offline, timed out, or unavailable
        if not llm_summary and results:
            top_crop = results[0]["cropName"]
            top_score = results[0].get("suitabilityScore", 85)
            alt_crops = ", ".join([r["cropName"] for r in results[1:4]]) if len(results) > 1 else "other seasonal crops"
            llm_summary = (
                f"{soil_desc} {top_crop} is your best match this season with an estimated suitability score of {top_score}%. "
                f"Viable alternatives for this season include {alt_crops}."
            )
            if soil_basis != "soil_test":
                llm_summary += " Add your Soil Health Card values to your farm for a soil-specific recommendation."

        return Response({
            "recommendations": results,
            "llm_summary": llm_summary,
            "engine": "model" if used_model else "heuristic",  # additive, non-breaking
            "soilBasis": soil_basis,      # "soil_test" | "partial" | "assumed"
            "soilClasses": soil_classes,  # {"N": "Low"|"Medium"|"High"|None, ...}
            "climateSource": getattr(self, "_climate_source", None) if used_model else None,
        })

    @staticmethod
    def _rag_reason(collection, crop_name, ph):
        # Crop-specific reason from the crop profile. (The knowledge-base
        # search below isn't filtered by crop, so it returned the same generic
        # "land preparation" note for every crop.)
        from krishi_core.services.crop_profile import crop_reason
        specific = crop_reason(crop_name, ph)
        if specific:
            return specific
        if ph is None:
            reason = f"{crop_name} suits your local climate and season."
        else:
            reason = f"{crop_name} suits your soil's pH {ph} and current nutrient profile."
        if collection:
            try:
                query = f"{crop_name} soil requirements pH nitrogen phosphorus recommendation"
                rag = collection.query(query_texts=[query], n_results=1, where={"source": "timeline_kb"})
                docs = rag.get("documents", [[]])[0]
                if docs:
                    why = extract_section(docs[0] + "\n", "Why it matters") or None
                    if why:
                        reason = why
            except Exception:
                pass
        return reason

    def _heuristic_fallback(self, ph, org_carbon, season_in, area_acres, water_avail, collection, ph_known=True):
        results = []
        for crop in CROPS:
            ph_lo, ph_hi = crop["phRange"]
            
            soil_match = 100 if ph_lo <= ph <= ph_hi else max(0, 100 - abs(ph - (ph_lo + ph_hi) / 2) * 20)
            soil_match = round(min(100, soil_match * (1 + (org_carbon - 0.5) * 0.3)))

            water_mult = WATER_COMPAT.get(water_avail, {}).get(crop["water"], 0.5)
            weather_pct = round(60 + water_mult * 35)
            
            # Suitability score is average of soil and weather match
            suit = (soil_match + weather_pct) / 2
            
            if crop["season"] != season_in:
                suit = max(0, suit - 20)
            suit = round(min(100, max(0, suit)))

            yield_kg = round(crop["yieldKgPerAcre"] * area_acres)
            cost = round(crop["costPerAcre"] * area_acres)
            revenue = round(crop["yieldKgPerAcre"] * area_acres * crop["pricePerKg"])
            margin = revenue - cost

            results.append({
                "cropName": crop["name"], "suitabilityScore": suit,
                "soilMatchPct": soil_match, "weatherMatchPct": weather_pct,
                "expectedYieldKg": yield_kg, "expectedMarginRs": margin,
                "durationDays": crop["durationDays"],
                "reason": self._rag_reason(collection, crop["name"], ph if ph_known else None),
                "isTopPick": False,
            })
        return results

    def _model_recommend(self, request, ph, nitrogen, phosphorus, potassium,
                         org_carbon, season_in, area_acres, collection, soil_rows=None):
        """Rank crops with the trained model when — and only when — it is
        loaded AND all nine real features are available.

        Returns a schema-compatible results list, or None to signal the caller
        to use the heuristic. Temperature / humidity / rainfall / state are
        sourced from the farm's real location (weather Archive + geocoded
        state); none of them are ever fabricated. If the frontend did not send
        a real location, or the Archive lookup fails, this returns None.
        """
        if not crop_recommendation_service.is_available():
            return None

        # Real geo + state from the farm (sent by the frontend). No defaults.
        try:
            lat = float(request.data.get("latitude"))
            lon = float(request.data.get("longitude"))
        except (TypeError, ValueError):
            lat = lon = None
        raw_state = request.data.get("state")

        # Farms saved with only a typed address (no coordinates) used to skip
        # the model entirely. Resolve the farm's real address server-side so
        # the trained model runs for every farm. Falls back to the state name
        # (state-level regional centre) only if the address can't be resolved.
        if lat is None or lon is None:
            from krishi_core.services.geocoding import geocode_lookup
            for query in (request.data.get("address"), raw_state):
                if not query:
                    continue
                geo = geocode_lookup(str(query), limit=1)
                if geo and geo.get("lat") is not None and geo.get("lon") is not None:
                    lat, lon = float(geo["lat"]), float(geo["lon"])
                    raw_state = raw_state or geo.get("state")
                    break

        state_token = normalize_state_token(raw_state)
        season_token = canonical_season(season_in)

        temperature = humidity = rainfall = None
        if lat is not None and lon is not None:
            from krishi_core.services.openmeteo_service import OpenMeteoService
            svc = OpenMeteoService()
            # Rainfall + temperature: season-aligned climatology (Archive API).
            clim = svc.get_seasonal_climatology(lat, lon, season_token)
            if clim:
                rainfall = clim.get("rainfall_mm")
                temperature = clim.get("temperature_C")
            # Humidity: current real value (Archive has no daily RH mean).
            wx = svc.get_forecast(lat, lon)
            if wx:
                cur = wx.get("current", {}) or {}
                humidity = cur.get("humidity")
                if temperature is None:            # fallback: current temp if climatology missing
                    temperature = cur.get("temperature")

        # Live climate unavailable (e.g. the weather API rate-limits the host)?
        # Use the state's 10-year seasonal normals so the trained model still
        # runs on real climate data instead of dropping to the rule-based path.
        climate_source = "live" if None not in (temperature, humidity, rainfall) else None
        if None in (temperature, humidity, rainfall) and state_token:
            from krishi_core.services.climate_normals import state_climate_normal
            normal = state_climate_normal(state_token, season_token)
            if normal:
                temperature = temperature if temperature is not None else normal["temperature_C"]
                humidity = humidity if humidity is not None else normal["humidity_pct"]
                rainfall = rainfall if rainfall is not None else normal["rainfall_mm"]
                climate_source = "state_normals"
        self._climate_source = climate_source

        # Climate, season and state must be genuinely present. Soil may be
        # unknown: that is handled by averaging over soil_rows, never invented.
        have_context = (
            None not in (temperature, humidity, rainfall)
            and bool(season_token) and bool(state_token)
        )
        if not have_context:
            logger.info(
                "Crop model skipped (real inputs incomplete): "
                "lat=%s lon=%s temp=%s humid=%s rain=%s season=%s state=%s",
                lat, lon, temperature, humidity, rainfall, season_token, state_token,
            )
            return None

        if soil_rows is None:
            from krishi_core.services.soil_inputs import soil_scenarios
            soil_rows, _, _ = soil_scenarios(nitrogen, phosphorus, potassium, ph)
        ranked = crop_recommendation_service.recommend_over_soil({
            "temperature_C": temperature, "humidity_pct": humidity,
            "rainfall_mm": rainfall, "season": season_token, "state": state_token,
        }, soil_rows, top_n=5)
        if not ranked:
            return None

        results = []
        for item in ranked:
            crop = item["crop"]
            conf = item.get("confidence")
            score = round((conf or 0.0) * 100)
            meta = get_crop_meta(crop)                    # never None (generic default fallback)

            # Real soil-pH match (same formula as the heuristic) so the UI's
            # soil bar reflects the farm, not just model confidence.
            ph_lo, ph_hi = meta["phRange"]
            if ph is None:
                soil_match = None        # no soil test: no made-up soil score
            else:
                soil_match = 100 if ph_lo <= ph <= ph_hi else max(0, 100 - abs(ph - (ph_lo + ph_hi) / 2) * 20)
                soil_match = round(min(100, soil_match * (1 + (org_carbon - 0.5) * 0.3)))

            yield_kg = round(meta["yieldKgPerAcre"] * area_acres)
            cost = round(meta["costPerAcre"] * area_acres)
            revenue = round(meta["yieldKgPerAcre"] * area_acres * meta["pricePerKg"])

            results.append({
                "cropName": crop,
                "suitabilityScore": score,       # canonical: model confidence
                "soilMatchPct": soil_match,      # real pH-based signal
                "weatherMatchPct": score,        # model/climate-driven
                "expectedYieldKg": yield_kg,
                "expectedMarginRs": revenue - cost,
                "durationDays": meta["durationDays"],
                "reason": self._rag_reason(collection, crop, ph),
                "isTopPick": False,
                "modelConfidence": conf,         # additive, non-breaking
            })

        logger.info(
            "Crop model ranked %d crops (top=%s, conf=%s).",
            len(results), results[0]["cropName"], results[0]["modelConfidence"],
        )
        return results


TASK_CALENDAR_TO_KB_STAGE_MAP = {
    "land preparation": "Land Preparation",
    "sowing": "Germination & Early Growth",
    "germination & establishment": "Germination & Early Growth",
    "planting/establishment": "Germination & Early Growth",
    "germination & early growth": "Germination & Early Growth",
    "vegetative growth": "Vegetative Growth",
    "flowering / reproductive": "Flowering / Reproductive Phase",
    "flowering/fruiting": "Flowering / Reproductive Phase",
    "flowering / reproductive phase": "Flowering / Reproductive Phase",
    "maturity & pre-harvest": "Fruit / Grain Development",
    "fruit / grain development": "Fruit / Grain Development",
    "harvest & post-harvest": "Harvesting",
    "harvesting": "Harvesting",
    "maturity & harvest": "Harvesting",
}


class CropStageTipsView(APIView):
    """RAG-powered field tips for a crop + growth stage (Crop Plan timeline)."""
    parser_classes = [ObjectJSONParser]

    def post(self, request):
        collection = ml_loader.state["collection"]
        if not collection:
            return Response({"error": "ChromaDB collection not initialized."}, status=500)

        serializer = CropStageTipsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        crop = serializer.validated_data["crop"].strip()
        stage = serializer.validated_data["stage"].strip()

        mapped_stage = TASK_CALENDAR_TO_KB_STAGE_MAP.get(stage.lower())
        if not mapped_stage:
            return Response({"found": False, "crop": crop, "stage": stage, "tips": {}})

        try:
            crop_name = crop.capitalize()
            where_filter = {
                "$and": [
                    {"source": {"$eq": "timeline_kb"}},
                    {"crop": {"$eq": crop_name}},
                    {"stage": {"$eq": mapped_stage}}
                ]
            }
            results = collection.get(where=where_filter)
            documents = results.get("documents", [])

            if not documents:
                for alt_crop in [crop.title(), crop]:
                    if alt_crop != crop_name:
                        alt_filter = {
                            "$and": [
                                {"source": {"$eq": "timeline_kb"}},
                                {"crop": {"$eq": alt_crop}},
                                {"stage": {"$eq": mapped_stage}}
                            ]
                        }
                        alt_res = collection.get(where=alt_filter)
                        if alt_res.get("documents"):
                            documents = alt_res.get("documents")
                            break

            if not documents:
                return Response({"found": False, "crop": crop, "stage": stage, "tips": {}})

            raw_text = documents[0]
            tasks_block = re.search(r"Key tasks:\n((?:- .+\n?)+)", raw_text)
            key_tasks = []
            if tasks_block:
                key_tasks = [l.strip("- ").strip() for l in tasks_block.group(1).strip().split("\n") if l.strip()]

            irrigation = extract_section(raw_text, "Irrigation")
            fertilizer = extract_section(raw_text, "Fertilizer")
            watch_for = extract_section(raw_text, "Watch for")
            treatment = extract_section(raw_text, "Treatment if needed")
            why_matters = extract_section(raw_text, "Why it matters")
            critical_raw = extract_section(raw_text, "Critical")
            is_critical = critical_raw.upper().startswith("YES")

            return Response({
                "found": True, "crop": crop, "stage": stage, "raw_text": raw_text,
                "tips": {
                    "key_tasks": key_tasks, "irrigation": irrigation, "fertilizer": fertilizer,
                    "watch_for": watch_for, "treatment": treatment, "why_it_matters": why_matters,
                    "critical": is_critical,
                },
            })
        except Exception as e:
            logger.error("Error in crop_stage_tips: %s", traceback.format_exc())
            return Response({"error": str(e)}, status=500)


class PredictDiseaseView(APIView):
    """
    Multimodal disease classification (Unit 6): Uses Google Gemini Vision to analyze
    the uploaded crop leaf image directly, avoiding heavy local CNN/YOLO models.
    Supports clear leaves, healthy foliage, uncertain/low-quality images, and non-plant rejection.
    """
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [AIRateThrottle]

    def post(self, request):
        image_file = request.FILES.get("image")
        if not image_file:
            return Response({
                "error": "No image uploaded in form-data field 'image'.",
                "status": "failed",
                "disease": "Missing Image",
                "confidence": 0.0,
                "treatment": "Please upload a clear photograph of the affected crop leaf to perform disease diagnosis.",
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate file size (max 10MB)
        if image_file.size > 10 * 1024 * 1024:
            return Response({
                "error": "Image file too large. Please upload an image under 10MB.",
                "status": "failed",
                "disease": "File Too Large",
                "confidence": 0.0,
                "treatment": "Compress the photo or upload a smaller file under 10MB.",
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate MIME type
        mime_type = image_file.content_type or "image/jpeg"
        if not mime_type.startswith("image/"):
            return Response({
                "error": f"Invalid file format ({mime_type}). Please upload a JPEG, PNG, or WEBP image.",
                "status": "failed",
                "disease": "Invalid File Format",
                "confidence": 0.0,
                "treatment": "Upload a valid image file (JPG, PNG, or WEBP).",
            }, status=status.HTTP_400_BAD_REQUEST)

        # The bytes must really be an image (a renamed text/PDF file passes the
        # MIME check above because browsers guess the type from the extension).
        # HEIC/HEIF (iPhone) can't be opened by Pillow but Gemini reads it.
        try:
            if mime_type not in ("image/heic", "image/heif"):
                from PIL import Image
                with Image.open(image_file) as probe:
                    probe.verify()
            image_file.seek(0)
        except Exception:
            return Response({
                "error": "This file is not a readable image. Please upload a JPEG, PNG, or WEBP photo.",
                "status": "failed",
                "disease": "Invalid File Format",
                "confidence": 0.0,
                "treatment": "Upload a valid image file (JPG, PNG, or WEBP).",
            }, status=status.HTTP_400_BAD_REQUEST)

        gemini_key = getattr(settings, "GEMINI_API_KEY", "")
        if not gemini_key:
            return Response({
                "error": "Disease inference service is not configured (GEMINI_API_KEY missing).",
                "status": "failed",
                "disease": "Service Unavailable",
                "confidence": 0.0,
                "treatment": "Please configure GEMINI_API_KEY in the server environment to enable plant disease diagnosis.",
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            import base64
            # Read image and encode to base64
            image_data = image_file.read()
            b64_image = base64.b64encode(image_data).decode('utf-8')

            # Multimodal prompt asking for calibrated, structured agronomic evaluation
            prompt = (
                "You are an expert plant pathologist and agronomist for Indian agriculture.\n"
                "Examine this image carefully and provide an honest, accurate evaluation:\n\n"
                "1. PLANT IDENTIFICATION:\n"
                "   - Is this an image of a real plant, crop, or leaf? (Set is_plant: true or false).\n"
                "   - If this is NOT a plant or leaf (e.g. human, animal, car, building, random indoor object, screenshot, artificial graphic, or unrelated item), set is_plant: false, status: 'invalid_image', disease: 'Not a Plant / Crop Leaf', crop: 'None', confidence: 0.0, symptoms: 'No plant or agricultural foliage detected in this image.', treatment: 'Please upload a clear photograph of a crop leaf or plant to receive a disease diagnosis.', preventive_measures: 'Ensure camera is focused on the crop foliage.'\n\n"
                "2. IMAGE CLARITY & QUALITY:\n"
                "   - Is the image clear enough to identify features? (Set is_clear: true or false).\n"
                "   - If the image is extremely blurry, poorly lit, or out of focus, set is_clear: false, status: 'uncertain', disease: 'Uncertain / Low Quality Photo', confidence: 0.40, symptoms: 'Image is too blurry, dark, or low-resolution for conclusive diagnosis.', treatment: 'Inspect the foliage in person. Retake the photograph under good natural lighting with the lens focused closely on the affected leaf.', preventive_measures: 'Ensure good focus and lighting when photographing plant symptoms.'\n\n"
                "3. DISEASE & HEALTH DIAGNOSIS:\n"
                "   - If it is a clear plant image, identify the crop species (e.g. 'Tomato', 'Wheat', 'Rice', 'Potato', 'Apple', etc.).\n"
                "   - If healthy (no spots, lesions, blight, or pests), set status: 'healthy', disease: 'Healthy Foliage', confidence: 0.90 to 0.98, symptoms: 'Vibrant green foliage with no visible fungal lesions, bacterial spots, chlorosis, or pest damage.', treatment: 'Maintain standard crop care, balanced irrigation, and routine scouting.', preventive_measures: 'Maintain proper plant spacing, avoid excessive nitrogen, and practice crop rotation.'\n"
                "   - If diseased, identify the specific disease (e.g. 'Tomato Early Blight', 'Tomato Bacterial Spot', 'Potato Late Blight', 'Wheat Rust', etc.), set status: 'diseased', confidence: 0.75 to 0.98 based on visual clarity of diagnostic symptoms.\n"
                "   - Provide concise, observed visual symptoms.\n"
                "   - Provide an agronomically sound, practical, and safe treatment plan grounded in ICAR guidelines (emphasizing sanitation, removing severely infected lower foliage, improving air circulation, avoiding overhead irrigation, and using safe organic treatments like neem oil or recommended copper fungicides if fungal/bacterial). Do NOT invent toxic chemical dosages.\n"
                "   - Provide key preventive measures for next season or surrounding plants.\n\n"
                "Respond STRICTLY with a valid JSON object matching this schema:\n"
                "{\n"
                '  "is_plant": true,\n'
                '  "is_clear": true,\n'
                '  "crop": "Crop Name",\n'
                '  "disease": "Disease Name",\n'
                '  "status": "healthy" | "diseased" | "uncertain" | "invalid_image",\n'
                '  "confidence": 0.85,\n'
                '  "symptoms": "Description of visible symptoms",\n'
                '  "treatment": "Practical, safe treatment recommendations",\n'
                '  "preventive_measures": "Key preventive practices"\n'
                "}"
            )

            # Multimodal payload properly formatted for Gemini Vision generateContent
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": b64_image
                                }
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 1024,
                }
            }

            configured_model = getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest")
            model_candidates = [configured_model]
            for candidate in [
                "gemini-flash-lite-latest",
                "gemini-3.5-flash-lite",
                "gemini-3.5-flash",
                "gemini-flash-latest",
                "gemini-pro-latest"
            ]:
                if candidate not in model_candidates:
                    model_candidates.append(candidate)

            res = None
            gemini_model = configured_model
            # API key goes in a header, never the URL (URLs end up in error
            # messages and logs, which would leak the key).
            gemini_headers = {"Content-Type": "application/json", "x-goog-api-key": gemini_key}
            for candidate_model in model_candidates:
                gemini_model = candidate_model
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent"
                try:
                    candidate_res = requests.post(url, json=payload, headers=gemini_headers, timeout=(5.0, 45.0))
                    if candidate_res.status_code == 200:
                        res = candidate_res
                        break
                    if candidate_res.status_code in (429, 503):
                        time.sleep(0.5)
                        candidate_res = requests.post(url, json=payload, headers=gemini_headers, timeout=(5.0, 45.0))
                        if candidate_res.status_code == 200:
                            res = candidate_res
                            break
                    res = candidate_res
                except (requests.Timeout, requests.RequestException):
                    continue

            if res is None:
                logger.error("Gemini API requests failed for candidates %s", model_candidates)
                return Response({
                    "error": "Upstream AI Vision service request failed. Please check your network connection and try again.",
                    "status": "failed",
                    "disease": "Service Unavailable",
                    "confidence": 0.0,
                    "treatment": "Unable to contact Gemini vision service.",
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

            if res.status_code != 200:
                logger.error("Gemini API error (%s): %s", res.status_code, res.text)
                if res.status_code == 429:
                    err_msg = "Gemini API quota or rate limit exceeded. Please wait a few moments and try scanning again."
                elif res.status_code == 503:
                    err_msg = "The AI vision model is temporarily overloaded. Please retry in a few seconds."
                elif res.status_code in (401, 403):
                    err_msg = "Gemini API credentials invalid or unauthorized. Please verify the backend environment."
                elif res.status_code == 404:
                    err_msg = f"Configured Gemini model '{gemini_model}' is unavailable."
                else:
                    err_msg = f"Upstream AI Vision service unavailable (HTTP {res.status_code})."

                return Response({
                    "error": err_msg,
                    "status": "failed",
                    "disease": "Service Unavailable",
                    "confidence": 0.0,
                    "treatment": err_msg,
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE if res.status_code in (429, 503) else status.HTTP_500_INTERNAL_SERVER_ERROR)

            candidates = res.json().get("candidates", [])
            if not candidates or not candidates[0].get("content", {}).get("parts"):
                logger.error("Gemini API returned empty candidate parts: %s", res.text)
                return Response({
                    "error": "AI model returned an empty response. Please try scanning a different photo.",
                    "status": "failed",
                    "disease": "Inconclusive",
                    "confidence": 0.0,
                    "treatment": "Could not extract diagnosis from image. Please ensure good lighting and try again.",
                }, status=status.HTTP_502_BAD_GATEWAY)

            text_resp = candidates[0]["content"]["parts"][0].get("text", "").strip()

            # Clean markdown code fences if present
            clean_text = text_resp
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```(?:json|JSON)?\s*\n?", "", clean_text, flags=re.IGNORECASE)
            if clean_text.endswith("```"):
                clean_text = re.sub(r"\n?```\s*$", "", clean_text)
            clean_text = clean_text.strip()

            first_brace = clean_text.find("{")
            last_brace = clean_text.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                json_str = clean_text[first_brace:last_brace + 1]
            elif first_brace != -1:
                json_str = clean_text[first_brace:]
            else:
                json_str = clean_text

            is_plant = True
            is_clear = True
            crop_name = "Crop"
            disease_name = "Unknown"
            status_val = "diseased"
            confidence = 0.85
            symptoms = ""
            treatment = ""
            preventive = ""

            try:
                parsed = json.loads(json_str)
                is_plant = bool(parsed.get("is_plant", True))
                is_clear = bool(parsed.get("is_clear", True))
                crop_name = str(parsed.get("crop", "Crop")).strip()
                disease_name = str(parsed.get("disease", "Unknown")).strip()
                status_val = str(parsed.get("status", "diseased" if is_plant else "invalid_image")).strip().lower()
                confidence = float(parsed.get("confidence", 0.85 if is_plant else 0.0))
                symptoms = str(parsed.get("symptoms", "")).strip()
                treatment = str(parsed.get("treatment", "")).strip()
                preventive = str(parsed.get("preventive_measures", "")).strip()
            except (json.JSONDecodeError, ValueError, TypeError) as parse_err:
                logger.warning("JSON decode failed for Gemini response (%s); attempting regex salvage: %s", parse_err, text_resp)
                disease_match = re.search(r'"disease"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', clean_text)
                crop_match = re.search(r'"crop"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', clean_text)
                status_match = re.search(r'"status"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', clean_text)
                conf_match = re.search(r'"confidence"\s*:\s*([0-9]*\.?[0-9]+)', clean_text)
                treatment_match = re.search(r'"treatment"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', clean_text)
                symptoms_match = re.search(r'"symptoms"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', clean_text)
                preventive_match = re.search(r'"preventive_measures"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', clean_text)

                if disease_match and disease_match.group(1).strip():
                    disease_name = disease_match.group(1).strip()
                    if crop_match:
                        crop_name = crop_match.group(1).strip()
                    if status_match:
                        status_val = status_match.group(1).strip().lower()
                    if conf_match:
                        try:
                            confidence = float(conf_match.group(1))
                        except ValueError:
                            confidence = 0.85
                    if treatment_match:
                        treatment = treatment_match.group(1).strip()
                    if symptoms_match:
                        symptoms = symptoms_match.group(1).strip()
                    if preventive_match:
                        preventive = preventive_match.group(1).strip()
                else:
                    logger.error("Failed to salvage disease diagnosis from Gemini output: %s", text_resp)
                    return Response({
                        "error": "The AI model response could not be parsed into a structured diagnosis.",
                        "status": "failed",
                        "disease": "Inconclusive",
                        "confidence": 0.0,
                        "treatment": "Could not complete diagnosis. Please ensure the leaf is clearly visible and try scanning again.",
                    }, status=status.HTTP_502_BAD_GATEWAY)

            # Guard against empty fields
            if not symptoms:
                if status_val == "healthy":
                    symptoms = "Foliage appears green and vigorous with no visible necrotic lesions, spots, or pest feeding."
                elif status_val == "invalid_image":
                    symptoms = "No agricultural crop leaf identified in this image."
                else:
                    symptoms = f"Visual symptoms characteristic of {disease_name} observed on leaf surface."

            if not treatment:
                if status_val == "healthy":
                    treatment = "Maintain current balanced irrigation, nutrient management, and regular field scouting."
                elif status_val == "invalid_image":
                    treatment = "Please upload a clear photograph of a crop leaf or plant foliage to receive a disease diagnosis."
                else:
                    treatment = (
                        f"Inspect affected foliage for symptoms of {disease_name}. "
                        "Prune and destroy severely infected lower leaves, ensure good row aeration, "
                        "avoid overhead watering, and apply recommended organic remedies (such as neem oil formulation) or targeted ICAR-approved fungicides if symptoms persist."
                    )

            if not preventive:
                preventive = "Ensure crop rotation, sanitize tools between plots, maintain recommended spacing, and avoid excessive nitrogen application."

            # Query ChromaDB disease treatments KB to enrich treatment if applicable
            try:
                from krishi_core.ml_loader import state
                d_col = state.get("disease_collection")
                if d_col and disease_name and disease_name not in ("Unknown", "Healthy Foliage", "Not a Plant / Crop Leaf") and is_plant:
                    kb_results = d_col.query(query_texts=[f"{crop_name} {disease_name}"], n_results=1)
                    if kb_results and kb_results.get("documents") and kb_results["documents"][0]:
                        kb_doc = kb_results["documents"][0][0]
                        if kb_doc and len(kb_doc) > 20 and kb_doc not in treatment:
                            treatment += f"\n\n**Verified KB Advisory:** {kb_doc}"
            except Exception:
                pass

            top3 = [
                {"label": disease_name, "prob": confidence}
            ]

            return Response({
                "disease": disease_name,
                "crop": crop_name,
                "status": status_val,
                "is_plant": is_plant,
                "is_clear": is_clear,
                "confidence": confidence,
                "symptoms": symptoms,
                "treatment": treatment,
                "preventive_measures": preventive,
                "top3": top3,
                "quality_passed": is_clear and is_plant,
                "quality_issues": [] if (is_clear and is_plant) else (["Non-plant image"] if not is_plant else ["Image quality is low/blurry"]),
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error("Error during disease prediction with Gemini: %s", traceback.format_exc())
            return Response({
                "error": f"Disease diagnosis failed due to an unexpected error: {str(e)}",
                "status": "failed",
                "disease": "Error",
                "confidence": 0.0,
                "treatment": "An unexpected error occurred during diagnosis. Please try again.",
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HealthView(APIView):
    def get(self, request):
        return Response({
            "status": "ok",
            "db_connected": ml_loader.state.get("collection") is not None,
            "ml_ready": True,
        })


class WeatherView(APIView):
    def get(self, request):
        lat_str = request.query_params.get("latitude")
        lon_str = request.query_params.get("longitude")
        if not lat_str or not lon_str:
            return Response({"error": "Missing latitude or longitude parameters"}, status=400)
        try:
            lat, lon = float(lat_str), float(lon_str)
        except ValueError:
            return Response({"error": "Latitude and longitude must be valid numbers"}, status=400)

        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return Response({"error": "Latitude must be between -90 and 90, and longitude between -180 and 180."}, status=400)

        from krishi_core.services.openmeteo_service import OpenMeteoService
        from krishi_core.services.alert_engine import alert_engine

        svc = OpenMeteoService()
        forecast = svc.get_forecast(latitude=lat, longitude=lon)
        if forecast is None:
            # The host's shared IP may be rate-limited by Open-Meteo. Tell the
            # browser where to fetch the forecast itself; it then POSTs the raw
            # response back here for parsing + alerts (see post()).
            # 200 (not 502): this is an expected hand-off, not a failure, and a
            # 5xx would show as a red error in every visitor's browser console.
            return Response({
                "needsBrowserFetch": True,
                "message": "Weather provider unreachable from the server; fetch it from the browser.",
                "fallbackUrl": svc.forecast_url(lat, lon),
            }, status=200)
        
        # Generate dynamic weather alerts based on current conditions
        forecast["alerts"] = alert_engine.generate_alerts(forecast.get("current", {}))

        return Response(forecast)

    def post(self, request):
        """Format a forecast the browser fetched from Open-Meteo directly
        (fallback when the server can't reach Open-Meteo) and add alerts."""
        from krishi_core.services.openmeteo_service import OpenMeteoService
        from krishi_core.services.alert_engine import alert_engine

        forecast = OpenMeteoService().parse_raw(request.data.get("raw"))
        if forecast is None:
            return Response({"error": "Body must be {\"raw\": <Open-Meteo forecast JSON>}"}, status=400)
        forecast["alerts"] = alert_engine.generate_alerts(forecast.get("current", {}))
        return Response(forecast)


class DecisionEngineView(APIView):
    """
    Advanced AI orchestration endpoint ported from Farmsense.
    Expects { "user_query": "...", "ml_predictions": {...}, "weather": {...}, "history": {...} }
    """
    parser_classes = [ObjectJSONParser]
    throttle_classes = [AIRateThrottle]
    
    def post(self, request):
        from krishi_core.services.ai_engine.decision_engine import decision_engine
        
        user_query = request.data.get("user_query", "")
        ml_predictions = request.data.get("ml_predictions", {})
        weather = request.data.get("weather", {})
        history = request.data.get("history", {})
        
        try:
            response = decision_engine.generate_recommendation(
                user_query=user_query,
                ml_predictions=ml_predictions,
                weather=weather,
                history=history
            )
            return Response(response)
        except Exception as e:
            logger.error("DecisionEngine Error: %s", traceback.format_exc())
            return Response({"error": str(e)}, status=500)
