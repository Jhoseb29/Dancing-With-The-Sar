"""Natural-language query -> validated analysis intent.

The model (small/fast, one tool-less turn) only *extracts* place, bbox, theme and dates.
Everything it returns is validated and normalised here; known regions override its bbox.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .claude_cli import ask_structured
from .regions import REGIONS, Region, bbox_overlap_fraction
from .settings import Settings
from .themes import THEMES, get_theme, theme_from_text

log = logging.getLogger("nisar.intent")

PROMPT_FILE = Path(__file__).parent / "prompts" / "intent_parser.md"
MAX_SPAN_DEG = 1.5  # NISAR frame ~2.4°; larger AOIs are cropped around their centre
MIN_SPAN_DEG = 0.1
SENSORS = ("auto", "nisar", "sentinel-1")
MODES = ("radar", "alertas")  # radar = analyse satellite takes; alertas = explain Centinela's current alerts
_ALERT_WORDS = ("alerta", "aviso", "centinela", "nivel de riesgo", "esta en naranja", "esta en rojo",
                "esta en amarillo", "esta en verde", "por que naranja", "por que rojo", "por que amarillo",
                "alert", "warning")
# A one-day question ("ayer", "hoy") needs a radar take BEFORE the event and the newest one AFTER it.
EVENT_BEFORE_DAYS = 14  # covers one repeat cycle of NISAR / each Sentinel-1 unit (12 d)
EVENT_AFTER_DAYS = 14
COCHABAMBA_ALERTS_BBOX = (-66.28, -17.53, -66.07, -17.26)
_RELATIVE_DAYS = (  # deterministic fallback; longest words first ("anteayer" before "ayer")
    (("anteayer", "antier", "day before yesterday"), 2),
    (("ayer", "anoche", "yesterday", "last night"), 1),
    (("hoy", "esta mañana", "esta madrugada", "today", "this morning", "tonight"), 0),
)

INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "place_name": {"type": ["string", "null"]},
        "bbox": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
        "theme": {"type": "string", "enum": list(THEMES)},
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "needs_clarification": {"type": "boolean"},
        "clarification_question": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "language": {"type": "string"},
        "event_date": {"type": ["string", "null"]},
        "sensor": {"type": "string", "enum": list(SENSORS)},
        "mode": {"type": "string", "enum": list(MODES)},
    },
    "required": ["place_name", "bbox", "theme", "start_date", "end_date",
                 "needs_clarification", "confidence", "language"],
}


@dataclass
class Intent:
    text: str
    place_name: str | None
    bbox: tuple[float, float, float, float] | None
    theme: str
    start_date: str
    end_date: str
    language: str
    confidence: float
    needs_clarification: bool
    clarification_question: str | None
    notes: list[str]
    usage: dict[str, Any] | None = None
    event_date: str | None = None  # a specific day the person asks about ("ayer")
    mode: str = "radar"
    sensor: str = "auto"  # auto | nisar | sentinel-1 (if the person names a satellite)

    @property
    def temporal(self) -> str:
        return f"{self.start_date}T00:00:00Z,{self.end_date}T23:59:59Z"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_intent(text: str, settings: Settings, today: date | None = None) -> Intent:
    today = today or date.today()
    result = ask_structured(
        system_prompt=PROMPT_FILE.read_text(encoding="utf-8"),
        user_prompt=f"HOY: {today.isoformat()}\nCONSULTA: {text.strip()}",
        schema=INTENT_SCHEMA,
        model=settings.intent_model,
        settings=settings,
    )
    intent = normalise(text, result.data, today)
    intent.usage = result.usage
    return intent


def offline_intent(text: str, today: date | None = None, reason: str = "") -> Intent:
    """Deterministic fallback when Claude is unavailable (e.g. subscription limit reached):
    theme from keywords, place only from curated regions. Never guesses a bbox."""
    low = text.lower()
    region = next((r for r in REGIONS if any(a in low for a in r.aliases)), None)
    raw = {
        "place_name": region.name if region else None,
        "bbox": list(region.bbox) if region else None,
        "theme": theme_from_text(text),
        "language": "es",
        "confidence": 0.5 if region else 0.0,
        "needs_clarification": region is None,
        "clarification_question": None if region else (
            "El asistente que interpreta lugares no está disponible ahora mismo. Nombra una región conocida "
            "(" + ", ".join(r.name for r in REGIONS) + ") o vuelve a intentarlo en un rato."),
    }
    intent = normalise(text, raw, today or date.today())
    intent.notes.append(f"parser determinista (Claude no disponible{': ' + reason[:120] if reason else ''})")
    return intent


def normalise(text: str, raw: dict[str, Any], today: date) -> Intent:
    """Pure function: validate/repair model output with deterministic rules."""
    notes: list[str] = []
    theme = get_theme(raw.get("theme"))
    bbox = _clean_bbox(raw.get("bbox"), notes)

    known = _known_region(raw.get("place_name"), bbox)
    if known:
        bbox = known.bbox
        notes.append(f"bbox de región conocida: {known.name}")

    event = _parse_date(raw.get("event_date")) or relative_event(text, today)
    if event:
        event = min(event, today)
        start = event - timedelta(days=EVENT_BEFORE_DAYS)
        end = min(today, event + timedelta(days=EVENT_AFTER_DAYS))
        notes.append(f"suceso puntual {event.isoformat()}: ventana con una toma antes y la más reciente después")
    else:
        end = _parse_date(raw.get("end_date")) or today
        end = min(end, today)
        start = _parse_date(raw.get("start_date")) or end - timedelta(days=theme.default_days)
        if start >= end:
            start = end - timedelta(days=theme.default_days)
            notes.append("rango temporal inválido: se aplicó la ventana del tema")
    mode = raw.get("mode") if raw.get("mode") in MODES else mode_from_text(text)
    if mode == "radar" and mode_from_text(text) == "alertas":
        mode = "alertas"  # explicit alert words win: no need to download radar to explain an alert
    if mode == "alertas" and bbox is None:
        bbox = COCHABAMBA_ALERTS_BBOX  # Centinela covers Cochabamba's 15 districts
    sensor = raw.get("sensor") if raw.get("sensor") in SENSORS and raw.get("sensor") != "auto" else sensor_from_text(text)

    needs = mode != "alertas" and (bool(raw.get("needs_clarification")) or bbox is None)
    return Intent(
        text=text,
        place_name=raw.get("place_name"),
        bbox=bbox,
        theme=theme.key,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        language=raw.get("language") or "es",
        confidence=float(raw.get("confidence") or 0.0),
        needs_clarification=needs,
        clarification_question=raw.get("clarification_question")
        or ("¿Sobre qué lugar quieres consultar? Puedes nombrar una ciudad, cuenca o región." if needs else None),
        notes=notes,
        event_date=event.isoformat() if event else None,
        sensor=sensor,
        mode=mode,
    )


def relative_event(text: str, today: date) -> date | None:
    """'ayer', 'anoche', 'hoy', 'anteayer' -> date. Pure, used when the model gives no event_date."""
    low = text.lower()
    for words, days_ago in _RELATIVE_DAYS:
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            return today - timedelta(days=days_ago)
    return None


def mode_from_text(text: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return "alertas" if any(w in folded for w in _ALERT_WORDS) else "radar"


def sensor_from_text(text: str) -> str:
    low = text.lower()
    if "sentinel" in low:
        return "sentinel-1"
    if "nisar" in low:
        return "nisar"
    return "auto"


def _clean_bbox(value: Any, notes: list[str]) -> tuple[float, float, float, float] | None:
    if not value or len(value) != 4:
        return None
    w, s, e, n = (float(v) for v in value)
    w, e = min(w, e), max(w, e)
    s, n = min(s, n), max(s, n)
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= 90 and -90 <= n <= 90):
        notes.append("bbox fuera de rango descartado")
        return None
    cx, cy = (w + e) / 2, (s + n) / 2
    half_x = min(max((e - w) / 2, MIN_SPAN_DEG / 2), MAX_SPAN_DEG / 2)
    half_y = min(max((n - s) / 2, MIN_SPAN_DEG / 2), MAX_SPAN_DEG / 2)
    if (e - w) > MAX_SPAN_DEG or (n - s) > MAX_SPAN_DEG:
        notes.append(f"área recortada a {MAX_SPAN_DEG}° alrededor del centro")
    return (round(cx - half_x, 4), round(cy - half_y, 4), round(cx + half_x, 4), round(cy + half_y, 4))


def _known_region(place: str | None, bbox: tuple[float, ...] | None) -> Region | None:
    """Use a curated bbox only when the query is at region scale (not a sub-place like a lagoon)."""
    if not place:
        return None
    place_l = place.lower()
    for region in REGIONS:
        if not any(alias in place_l for alias in region.aliases):
            continue
        if bbox is None or bbox_overlap_fraction(region.bbox, bbox) >= 0.5:
            return region
    return None


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None
