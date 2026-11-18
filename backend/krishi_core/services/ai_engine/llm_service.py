import json
import logging
import re

from .gemini_client import gemini_generate

logger = logging.getLogger(__name__)


def _parse_json(text: str):
    cleaned = re.sub(r'^```(?:json)?\n', '', text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'\n```$', '', cleaned.strip())
    return json.loads(cleaned)


class LLMService:
    """Text generation via Google Gemini (the app's only LLM provider)."""

    def generate_response(self, prompt: str, force_json: bool = True, timeout: tuple = None) -> dict | str:
        text, model = gemini_generate(
            prompt,
            json_mode=force_json,
            temperature=0.2,
            timeout=timeout or (5.0, 60.0),
        )
        if text:
            if not force_json:
                return text
            try:
                return _parse_json(text)
            except (ValueError, TypeError):
                logger.warning("Gemini (%s) returned non-JSON output for a JSON request", model)

        # Graceful fallback when Gemini is unavailable, rate-limited or unconfigured
        if force_json:
            return {"error": "AI service unavailable", "fallback": True}
        return "AI service is currently unavailable (offline, rate-limited, or unconfigured). Please configure GEMINI_API_KEY."


llm_service = LLMService()
