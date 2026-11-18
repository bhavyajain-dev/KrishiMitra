"""
Single entry point for Google Gemini text generation.

- The API key is sent in the ``x-goog-api-key`` header, never in the URL, so it
  can't leak through exception messages or request logs.
- Tries the configured model first, then a short list of fallbacks, retrying
  once on 429/503 (rate-limit / overloaded).
"""
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FALLBACK_MODELS = [
    # Measured Nov 2026 with this project's key: 3.1-flash-lite answers in
    # ~2 s; flash-lite-latest (3.5) takes 7-9 s; the 2.x names return 404.
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]


def gemini_configured() -> bool:
    return bool(getattr(settings, "GEMINI_API_KEY", ""))


def _candidate_models():
    configured = getattr(settings, "GEMINI_MODEL", "") or "gemini-3.1-flash-lite"
    models = [configured]
    for m in FALLBACK_MODELS:
        if m not in models:
            models.append(m)
    return models


def gemini_generate(prompt: str, *, json_mode: bool = False, temperature: float | None = None,
                    timeout: tuple = (5.0, 60.0), image: tuple | None = None):
    """Generate text with Gemini.

    Returns ``(text, model_used)`` on success, or ``(None, None)`` when Gemini
    is unconfigured or every candidate model failed.
    """
    key = getattr(settings, "GEMINI_API_KEY", "")
    if not key:
        return None, None

    parts = [{"text": prompt}]
    if image:
        # (mime_type, base64_data): a photo the farmer attached in chat.
        mime, data = image
        parts.append({"inline_data": {"mime_type": mime, "data": data}})
    body = {"contents": [{"parts": parts}]}
    gen_cfg = {}
    if json_mode:
        gen_cfg["responseMimeType"] = "application/json"
    if temperature is not None:
        gen_cfg["temperature"] = temperature
    if gen_cfg:
        body["generationConfig"] = gen_cfg

    headers = {"Content-Type": "application/json", "x-goog-api-key": key}

    for model in _candidate_models():
        url = GEMINI_ENDPOINT.format(model=model)
        for attempt in range(2):
            try:
                res = requests.post(url, json=body, headers=headers, timeout=timeout)
            except requests.RequestException as exc:
                # Timeouts / network failures aren't model-specific: trying the
                # next model would only multiply the wait. Give up quickly.
                logger.warning("Gemini %s request error: %s", model, type(exc).__name__)
                return None, None
            if res.status_code == 200:
                try:
                    cands = res.json().get("candidates", [])
                    text = cands[0].get("content", {}).get("parts", [{}])[0].get("text", "") if cands else ""
                except (ValueError, IndexError, AttributeError):
                    text = ""
                if text:
                    return text.strip(), model
                break
            if res.status_code in (429, 503) and attempt == 0:
                time.sleep(0.5)
                continue
            logger.warning("Gemini %s returned HTTP %s", model, res.status_code)
            break
    return None, None
