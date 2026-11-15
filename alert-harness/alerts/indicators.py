"""Deterministic indicators. Each one is a dict validated against schemas/indicator.schema.json.

Confidence rules (explicit, so the evaluation can challenge them):
  * IMERG: "media" (0.1° cells smooth 30–60 min convective storms); "baja" if days are missing.
  * DEM:   "alta" (30 m, static).
  * Radar: "media" if the takes bracket the event and pixels are >= 80 % valid; else "baja".
           Sediment is "baja" without the channel corridor (could be harvest/tillage).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import schema
from .sources.dem import Terrain
from .sources.imerg import DayRain
from .sources.radar import RadarEvidence

Indicator = dict[str, Any]


def _ind(id_: str, valor: float, unidad: str, metodo: str, evidencia: str, confianza: str,
         caveat: str | None = None) -> Indicator:
    doc = {"id": id_, "valor": round(float(valor), 3), "unidad": unidad, "metodo": metodo,
           "evidencia": evidencia, "confianza": confianza}
    if caveat:
        doc["caveat"] = caveat
    return schema.require("indicator", doc)


def rain(series: list[DayRain], ref_day: str, cfg: dict[str, Any]) -> list[Indicator]:
    by_day = {r.day: r for r in series}
    ref = date.fromisoformat(ref_day)
    window = lambda n: [by_day.get((ref - timedelta(d)).isoformat()) for d in range(n)]  # noqa: E731
    products = sorted({r.product for r in series if r.max_mm is not None})
    missing = sum(r.max_mm is None for r in series)
    conf = "baja" if missing > len(series) * 0.2 else "media"
    src = f"NASA GPM IMERG ({', '.join(products) or 'sin dato'}), {len(series)} días, {missing} sin dato"
    caveat = "Celdas de ~10 km: suaviza tormentas cortas y locales; puede subestimar el pico."

    last2 = [r.max_mm for r in window(2) if r and r.max_mm is not None]
    last3 = [r.max_mm for r in window(3) if r and r.max_mm is not None]
    k, api = cfg["api_k"], 0.0
    for r in sorted(series, key=lambda x: x.day):
        if r.day <= ref_day:
            api = k * api + (r.max_mm or 0.0)
    peak = max(series, key=lambda r: r.max_mm or -1)
    return [
        _ind("lluvia_max_24h_mm", max(last2, default=0.0), "mm/día",
             "Máximo diario de la celda IMERG más lluviosa del área (día evaluado o el anterior, por precisión de fecha)",
             src, conf, caveat),
        _ind("lluvia_acumulada_72h_mm", sum(last3), "mm",
             "Suma de los 3 días hasta el día evaluado (celda más lluviosa)", src, conf, caveat),
        _ind("lluvia_api_mm", api, "mm",
             f"Índice de precipitación antecedente API_t = {k}·API_(t-1) + P_t sobre {cfg['dias_api']} días",
             src, conf, "Humedad del suelo inferida solo de la lluvia (sin SMAP todavía)."),
        _ind("lluvia_pico_ventana_mm", peak.max_mm or 0.0, "mm/día",
             f"Día más lluvioso de la ventana analizada ({peak.day})", src, conf),
    ]


def terrain(t: Terrain) -> list[Indicator]:
    src = f"Copernicus DEM GLO-30 ({', '.join(t.tiles)})"
    return [
        _ind("pendiente_media_grados", t.mean_slope_deg, "°", "Media de la pendiente (gradiente del DEM 30 m)", src, "alta"),
        _ind("fraccion_pendiente_fuerte_pct", t.steep_fraction_pct, "%",
             f"Área con pendiente > {t.steep_threshold_deg}°", src, "alta"),
        _ind("relieve_m", t.relief_m, "m", "Diferencia de altura máxima − mínima en el área", src, "alta"),
    ]


def radar(ev: RadarEvidence) -> list[Indicator]:
    base_conf = "media" if ev.spans_event and (ev.valid_pixels_pct or 0) >= 80 else "baja"
    src = (f"{ev.sensor or 'radar'} vía nisar-harness (corrida {ev.run_id}; tomas {' → '.join(ev.dates)})")
    span_caveat = None if ev.spans_event else "Las tomas no rodean la fecha del evento: el cambio no se puede atribuir."
    out = []
    water = (ev.kinds.get("nueva_agua") or {}).get("area_km2")
    if water is not None:
        out.append(_ind("radar_agua_nueva_km2", water, "km²",
                        "Celdas que pasan a agua y se oscurecen ≥3 dB (relativo al corrimiento de escena)",
                        src, base_conf, span_caveat))
    sediment = (ev.kinds.get("nuevo_sedimento") or {}).get("area_km2")
    if sediment is not None:
        corridor = (ev.corridor or {}).get("applied")
        conf = base_conf if corridor else "baja"
        cav = "; ".join(filter(None, [
            span_caveat,
            None if corridor else "Sin corredor de cauces: puede ser cosecha o labranza.",
            "Compatible con lodo/sedimento, no confirma el evento.",
        ]))
        out.append(_ind("radar_sedimento_corredor_km2", sediment, "km²",
                        "Vegetación→suelo con caída de pol. cruzada ≥2 dB dentro del corredor de cauces (±300 m)",
                        src, conf, cav))
    if ev.valid_pixels_pct is not None:
        out.append(_ind("radar_pixeles_validos_pct", ev.valid_pixels_pct, "%",
                        "Mínimo de píxeles válidos entre las tomas", src, "alta"))
    return out
