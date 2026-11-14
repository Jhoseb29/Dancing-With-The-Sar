"""Transcripción con Gemini (audio como entrada de generate_content). Verificado el
2026-11-14: transcribe español correctamente; se dan pistas de vocabulario del proyecto."""

from __future__ import annotations

import re

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from modules.llm_advisor.ports.speech_to_text import SpeechToTextError

VOCABULARY = (
    "Dancing with the SARs, NISAR, SAR, radar, Cochabamba, Tunari, Rocha, Bolivia, GAMC, FIRMS, "
    "MODIS, VIIRS, cuenca, cuencas, Cota 2750, Chiquitania, Beni, Santa Cruz, La Paz"
)

NO_SPEECH = "[SIN_VOZ]"

# El vocabulario solo corrige la ortografía de palabras que de verdad se oyen: sin la
# marca de "sin voz", el modelo llegó a "transcribir" el nombre del proyecto desde un tono puro.
PROMPT = {
    "es": (
        "Transcribe exactamente las palabras habladas por una persona en este audio, en español. "
        f"Si oyes alguna de estas palabras, escríbela así: {VOCABULARY}. No las agregues si no se dicen. "
        f"Si el audio no contiene voz humana inteligible (silencio, ruido, tonos, música), responde exactamente {NO_SPEECH}. "
        "Devuelve solo la transcripción, sin comillas ni comentarios."
    ),
    "en": (
        "Transcribe exactly the words spoken by a person in this audio. "
        f"If you hear any of these words, spell them like this: {VOCABULARY}. Do not add them if they are not said. "
        f"If the audio contains no intelligible human speech (silence, noise, tones, music), reply exactly {NO_SPEECH}. "
        "Return only the transcription, no quotes or comments."
    ),
}


class GeminiTranscriber:
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = genai.Client(api_key=api_key) if api_key else None

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def transcribe(self, audio: bytes, mime_type: str, lang: str) -> str:
        if self._client is None:
            raise SpeechToTextError("GEMINI_API_KEY no configurada")
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[types.Part.from_bytes(data=audio, mime_type=mime_type), PROMPT.get(lang, PROMPT["es"])],
            )
        except genai_errors.APIError as err:
            raise SpeechToTextError(f"Gemini respondió {err.code}") from err
        text = (response.text or "").strip().strip('"“”').strip()
        # Etiquetas como "<noise>" o "[música]" no son voz.
        if re.fullmatch(r"[\s<\[(][^>\])]*[>\])]\s*", text):
            return ""
        if not text or NO_SPEECH in text or _only_vocabulary(text):
            return ""
        return text


_VOCAB_WORDS = {w.lower() for term in VOCABULARY.split(",") for w in term.strip().split()} | {"the", "with"}


def _only_vocabulary(text: str) -> bool:
    """Una "transcripción" hecha solo de términos del vocabulario es casi siempre una alucinación
    (verificado: con un tono puro el modelo devolvió "SAR" o el nombre del proyecto)."""
    words = [w.strip(".,;:¡!¿?\"'").lower() for w in text.split()]
    words = [w for w in words if w]
    return bool(words) and all(w in _VOCAB_WORDS for w in words)
