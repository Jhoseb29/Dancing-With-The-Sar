"""Voz a texto en el servidor (OpenSpec 10, D6): respaldo de la Web Speech API del navegador.

POST /api/voice/transcribe   cuerpo = audio crudo (audio/webm|ogg|mp4|mpeg|wav|aac, ≤ 2 MB)
                             -> {"text": "..."}  ("" si no hubo voz)

El navegador graba con MediaRecorder y corta por silencio; aquí Gemini transcribe. Anti-alucinación:
el modelo debe responder [SIN_VOZ] si no oye una persona hablando, y se descartan salidas que son
solo etiquetas (<noise>, [música]...).
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from config.settings import get_settings

router = APIRouter(prefix="/api/voice")
log = logging.getLogger(__name__)

MAX_BYTES = 2 * 1024 * 1024
ALLOWED = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac")
NO_SPEECH = "[SIN_VOZ]"
_ONLY_TAGS = re.compile(r"^\s*([\[<(][^\]>)]*[\]>)]\s*)+$")
_WORD = re.compile(r"[^\W\d_]{2,}")  # al menos una palabra de 2+ letras (cualquier alfabeto)

PROMPT = (
    "Transcribe literalmente lo que dice la persona en este audio (español de Bolivia o inglés). "
    "Devuelve SOLO el texto dicho, sin comillas ni comentarios. "
    f"Si no hay una persona hablando (silencio, ruido, tonos, música), responde exactamente {NO_SPEECH}."
)


@lru_cache
def _client():
    from google import genai

    return genai.Client(api_key=get_settings().gemini_api_key)


def _transcribe(audio: bytes, mime: str) -> str:
    from google.genai import errors, types

    s = get_settings()
    part = types.Part.from_bytes(data=audio, mime_type=mime)
    # Variables vacías en .env (GEMINI_STT_MODEL=) cuentan como "usar el valor por defecto".
    models = (s.gemini_stt_model or "gemini-3.5-flash-lite", s.gemini_fallback_model or "gemini-3.8-flash")
    for model in models:
        try:
            resp = _client().models.generate_content(model=model, contents=[part, PROMPT])
            break
        except errors.APIError as exc:
            if exc.code == 404 or (exc.code or 0) >= 500:
                log.warning("Gemini %s no disponible (%s); pruebo el respaldo", model, exc.code)
                continue
            raise
    else:
        raise RuntimeError("Ningún modelo de Gemini respondió")
    text = (resp.text or "").strip().strip('"“”')
    # Sin voz el modelo a veces devuelve marcas de tiempo ("00:00") o puntuación: sin palabras = sin voz.
    if not text or NO_SPEECH in text or _ONLY_TAGS.match(text) or not _WORD.search(text):
        return ""
    return text


@router.post("/transcribe")
async def transcribe(request: Request) -> dict:
    if not get_settings().gemini_api_key:
        raise HTTPException(503, detail={"code": "stt_unconfigured", "message": "Falta GEMINI_API_KEY en .env."})
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if mime not in ALLOWED:
        raise HTTPException(415, detail={"code": "bad_audio", "message": f"Formato de audio no permitido: {mime}"})
    audio = await request.body()
    if not audio or len(audio) > MAX_BYTES:
        raise HTTPException(413, detail={"code": "audio_size", "message": "El audio debe pesar entre 1 byte y 2 MB."})
    try:
        return {"text": await run_in_threadpool(_transcribe, audio, mime)}
    except Exception as exc:  # noqa: BLE001 - el panel muestra un error de voz y sigue funcionando por teclado
        log.error("Transcripción falló: %s", exc)
        raise HTTPException(502, detail={"code": "stt_failed", "message": "No se pudo transcribir el audio."}) from exc
