"""Bridge between the deterministic pipeline and the cognitive layer.

1. build_context()       compact JSON (numbers only, no images, no paths) -> interpreter_context.json
2. interpret()           ONE tool-less Claude call (role = the nisar-didactic-interpreter skill)
                         -> interpretation_narrative.json (short chat message) + interpretation.md (lesson)
3. assemble_ui_payload() deterministic metrics + media (images with fixed captions) + model text
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from .change import change_summary
from .claude_cli import ask_structured
from .jsonio import read_json, write_json
from .run_context import RunContext
from .settings import HARNESS_DIR, Settings
from .themes import get_theme

log = logging.getLogger("nisar.interpreter")

SKILL_FILE = HARNESS_DIR / ".claude" / "skills" / "nisar-didactic-interpreter" / "SKILL.md"
ALERT_LEVELS = ("verde", "amarillo", "naranja", "rojo", "sin_datos")

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chat": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "alert_level": {"type": "string", "enum": list(ALERT_LEVELS)},
                "alert_reason": {"type": "string"},
                "highlights": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "follow_up_questions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            },
            "required": ["message", "alert_level", "alert_reason", "highlights"],
        },
        "lesson_markdown": {"type": "string"},
    },
    "required": ["chat", "lesson_markdown"],
}

# What each exported file is, for the UI. Images are shown to the user, never sent to the model.
MEDIA_CATALOG: dict[str, dict[str, Any]] = {
    "rgb": {"kind": "image", "overlay": True, "title": "Falso color radar",
            "caption": "Rojo = HH (superficies, edificios) · Verde = HV (vegetación) · Azul = HH/HV. "
                       "Lo oscuro es agua o superficie lisa."},
    "classes": {"kind": "image", "overlay": True, "title": "Mapa de mecanismos de dispersión",
                "caption": "Azul agua · beige suelo desnudo · verde vegetación · rojo urbano/rebote doble."},
    "png": {"kind": "image", "overlay": False, "title": "Retrodispersión HH (dB)",
            "caption": "Brillo = cuánta energía devuelve el terreno al radar. Ejes en longitud/latitud."},
    "histogram": {"kind": "image", "overlay": False, "title": "Distribución de retrodispersión",
                  "caption": "Cuántos píxeles hay en cada nivel de dB, con los umbrales de cada clase."},
    "tif": {"kind": "download", "overlay": False, "title": "GeoTIFF (QGIS/ArcGIS)",
            "caption": "Una banda por polarización, en dB, georreferenciado."},
    "kml": {"kind": "download", "overlay": False, "title": "KML (Google Earth)",
            "caption": "Superpone el falso color sobre el relieve 3D."},
    "geojson": {"kind": "geojson", "overlay": False, "title": "Huella del análisis (GeoJSON)",
                "caption": "Área analizada y huella completa del gránulo."},
}


# ------------------------------------------------------------------ context
def _granule_metrics(run: RunContext) -> list[dict[str, Any]]:
    items = []
    for gdir in run.granule_dirs():
        path = gdir / "curated_metrics.json"
        if path.exists():
            items.append(read_json(path))
    return sorted(items, key=lambda m: m["acquisition"].get("start_time") or "")


def _date_row(m: dict[str, Any]) -> dict[str, Any]:
    acq, q = m["acquisition"], m["data_quality"]
    return {
        "date": (acq.get("start_time") or "")[:10],
        "season": acq.get("season"),
        "orbit": acq.get("orbit_pass_direction"),
        "track": acq.get("track"),
        "product_version": acq.get("product_version"),
        "valid_pixels_pct": q.get("valid_pixels_pct"),
        "pixel_spacing_m": m["spatial_reference"].get("analysis_pixel_spacing_m"),
        "scattering_pct": m["physical_scattering_breakdown"],
        "classification_method": m.get("classification", {}).get("method"),
        "mean_db": m["statistical_distribution_db"].get("mean_db"),
        "p05_p95_db": [m["statistical_distribution_db"].get("p05_db"), m["statistical_distribution_db"].get("p95_db")],
        "per_pol_mean_db": {k: v.get("mean_db") for k, v in (m.get("per_polarization_db") or {}).items()},
        "rvi_mean": m["polarimetric_indices"].get("rvi_mean"),
        "cross_pol_ratio_mean_db": m["polarimetric_indices"].get("cross_pol_ratio_mean_db"),
    }


def build_context(run: RunContext) -> dict[str, Any]:
    metrics = _granule_metrics(run)
    intent = run.manifest.get("intent") or {}
    theme = get_theme(intent.get("theme") or run.manifest.get("request", {}).get("theme"))
    query = read_json(run.query_json) if run.query_json.exists() else {}
    newest = metrics[-1] if metrics else None
    sref = newest["spatial_reference"] if newest else {}
    radar = newest["radar_physics"] if newest else {}
    context = {
        "run_id": run.run_id,
        "question": intent.get("text"),
        "place": intent.get("place_name"),
        "theme": {"key": theme.key, "label": theme.label, "radar_signal": theme.radar_signal,
                  "focus_metrics": list(theme.focus_metrics)},
        "period": {"start": intent.get("start_date"), "end": intent.get("end_date")},
        "regions": [{"name": r["name"], "landmarks": r["landmarks"]} for r in sref.get("regions", [])],
        "aoi": {"intersects_granule": sref.get("aoi_intersects_granule"),
                "covered_fraction": sref.get("aoi_covered_fraction")},
        "radar": {"band": radar.get("band"), "wavelength_cm": radar.get("wavelength_cm"),
                  "incidence_mean_deg": (radar.get("incidence_angle") or {}).get("mean_deg"),
                  "polarizations": radar.get("polarizations")},
        "catalog": {"total_hits": query.get("total_hits"),
                    "available_dates": sorted({g["time_start"][:10] for g in query.get("granules", [])}),
                    "temporal_widened": query.get("temporal_widened", False)},
        "dates": [_date_row(m) for m in metrics],
        "change": change_summary(metrics),
        "media_shown_to_user": [v["title"] for k, v in MEDIA_CATALOG.items() if v["kind"] == "image"],
    }
    write_json(run.context_json, context)
    return context


# ------------------------------------------------------------------ model call
def _skill_role() -> str:
    """The skill file is the single source of the interpreter's role (frontmatter stripped)."""
    text = SKILL_FILE.read_text(encoding="utf-8")
    return re.sub(r"\A---.*?---\s*", "", text, flags=re.DOTALL)


def interpret(run: RunContext, settings: Settings, model: str | None = None) -> dict[str, Any]:
    context = read_json(run.context_json) if run.context_json.exists() else build_context(run)
    result = ask_structured(
        system_prompt=_skill_role(),
        user_prompt=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
        schema=OUTPUT_SCHEMA,
        model=model or settings.interpret_model,
        settings=settings,
    )
    write_json(run.narrative_json, result.data["chat"])
    run.interpretation_md.write_text(result.data["lesson_markdown"], encoding="utf-8")
    return result.usage


# ------------------------------------------------------------------ ui payload
def build_media(run: RunContext) -> list[dict[str, Any]]:
    media = []
    for gdir in run.granule_dirs():
        index, metrics = gdir / "formats.json", gdir / "curated_metrics.json"
        if not index.exists() or not metrics.exists():
            continue
        m = read_json(metrics)
        date = (m["acquisition"].get("start_time") or "")[:10]
        bounds = m["spatial_reference"]["analyzed_bounds_lonlat"]
        for fmt, path in read_json(index).items():
            info = MEDIA_CATALOG.get(fmt)
            if info:
                media.append({"format": fmt, "date": date, "path": path,
                              "bounds_lonlat": bounds if info["overlay"] else None, **info})
    order = list(MEDIA_CATALOG)  # catalogue order = display priority
    media.sort(key=lambda x: order.index(x["format"]))
    return sorted(media, key=lambda x: x["date"], reverse=True)  # stable: newest date first


def assemble_ui_payload(run: RunContext, usage: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    context = read_json(run.context_json) if run.context_json.exists() else build_context(run)
    chat = read_json(run.narrative_json) if run.narrative_json.exists() else None
    lesson = run.interpretation_md.read_text(encoding="utf-8") if run.interpretation_md.exists() else None
    issues = []
    if chat and chat.get("alert_level") not in ALERT_LEVELS:
        issues.append("alert_level inválido")
    newest = context["dates"][-1] if context["dates"] else None
    payload = {
        "schema_version": "3.0",
        "run_id": run.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if chat and lesson and not issues else "data_only",
        "validation_issues": issues,
        "query": run.manifest.get("intent"),
        "chat": chat,                    # short: render as the assistant's chat bubble
        "lesson_markdown": lesson,       # long: render below the bubble / "aprende más"
        "metrics": newest,
        "time_series": context["dates"],
        "change": context["change"],
        "media": build_media(run),
        "map": {"aoi_bbox": run.manifest.get("request", {}).get("bbox"),
                "regions": context["regions"]},
        "usage": usage or [],
    }
    write_json(run.ui_payload_json, payload)
    return payload


def clarification_payload(run: RunContext, question: str) -> dict[str, Any]:
    payload = {
        "schema_version": "3.0",
        "run_id": run.run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "needs_clarification",
        "query": run.manifest.get("intent"),
        "chat": {"message": question, "alert_level": "sin_datos", "alert_reason": "", "highlights": []},
        "lesson_markdown": None,
        "media": [],
    }
    write_json(run.ui_payload_json, payload)
    return payload
