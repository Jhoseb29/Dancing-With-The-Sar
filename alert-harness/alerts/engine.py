"""Alert engine: indicators -> components (0..1) -> risk index (0..100) -> level + actions.

Risk model v3 (thresholds.yaml): index = 100 · disparo × terrain factor (+ radar evidence);
disparo = 24/72 h rain against thresholds lowered by wet antecedent conditions (API).

Everything here is deterministic and driven by config/thresholds.yaml and config/protocols.yaml.
Missing components (e.g. no radar pass around the date) are left out and their weight is
redistributed, but confidence drops accordingly - the alert says what it could NOT see.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import indicators as ind
from . import schema
from .settings import Settings
from .sources import dem, imerg, radar

LEVELS = ("verde", "amarillo", "naranja", "rojo")
CONF_VALUE = {"alta": 1.0, "media": 0.65, "baja": 0.35}


@dataclass
class Request:
    nombre: str
    bbox: tuple[float, float, float, float]
    fecha: str
    peligro: str | None = None  # None = deducido del relieve
    radar_run: str | None = None
    radar_mode: str = "reuse"  # reuse | run | skip
    case_id: str | None = None


def scale(x: float, bands: dict[str, float]) -> float:
    """Piecewise: 0..moderada -> 0..0.33, ..fuerte -> 0.66, ..extrema -> 1.0."""
    pts = [(0.0, 0.0), (bands["moderada"], 0.33), (bands["fuerte"], 0.66), (bands["extrema"], 1.0)]
    if x >= pts[-1][0]:
        return 1.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return 1.0


def _expand(bbox: tuple[float, ...], margin: float) -> tuple[float, ...]:
    w, s, e, n = bbox
    return (round(w - margin, 4), round(s - margin, 4), round(e + margin, 4), round(n + margin, 4))


def evaluate(req: Request, st: Settings) -> dict[str, Any]:
    th = st.thresholds
    cache = st.output_dir / "cache"
    ref = date.fromisoformat(req.fecha)
    found: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    # --- sources -> indicators
    rain_box = _expand(req.bbox, th["area"]["margen_cuenca_aporte_grados"])
    series = imerg.daily_series(rain_box, ref - timedelta(days=th["lluvia"]["dias_api"]), ref, st.earthdata_token, cache)
    for i in ind.rain(series, req.fecha, th["lluvia"]):
        found[i["id"]] = i
    terr = dem.terrain_stats(req.bbox, th["terreno"]["pendiente_fuerte_grados"], cache)
    for i in ind.terrain(terr):
        found[i["id"]] = i
    hazard = req.peligro or ("mazamorra" if terr.steep_fraction_pct >= th["terreno"]["fraccion_fuerte_alta_pct"] else "inundacion")
    ev = radar.evidence(st.nisar_harness_dir, st.uv_bin, req.bbox, req.fecha, hazard, req.radar_run, req.radar_mode)
    if ev is None:
        missing.append("evidencia radar (sin corrida NISAR/Sentinel-1 para esta fecha)")
    else:
        for i in ind.radar(ev):
            found[i["id"]] = i
    missing.append("humedad del suelo SMAP (aún no integrada)")
    missing.append("pronóstico de lluvia (aún no integrado)")

    # --- components (0..1)
    lt = th["lluvia"]
    # v3: wet antecedent conditions lower the rain thresholds instead of adding to the trigger.
    wet = scale(found["lluvia_api_mm"]["valor"], lt["api_mm"])
    factor = 1.0 - lt["reduccion_umbral_suelo_humedo"] * wet
    lower = lambda bands: {k: v * factor for k, v in bands.items()}  # noqa: E731
    disparo = max(scale(found["lluvia_max_24h_mm"]["valor"], lower(lt["max_24h_mm"])),
                  scale(found["lluvia_acumulada_72h_mm"]["valor"], lower(lt["acumulada_72h_mm"])))
    steep = min(1.0, found["fraccion_pendiente_fuerte_pct"]["valor"] / th["terreno"]["fraccion_fuerte_alta_pct"])
    susceptibilidad = steep if hazard in ("mazamorra", "deslizamiento") else 1.0 - 0.5 * steep
    evidencia = None
    if ev is not None and ev.spans_event:
        rt = th["radar"]
        sed = found.get("radar_sedimento_corredor_km2", {}).get("valor", 0.0)
        wat = found.get("radar_agua_nueva_km2", {}).get("valor", 0.0)
        evidencia = min(1.0, max(sed / rt["sedimento_alto_km2"], wat / rt["agua_nueva_alta_km2"]))
    elif ev is not None:
        missing.append("radar sin tomas antes y después del evento")
    comps = {"disparo": disparo, "susceptibilidad": susceptibilidad, "evidencia_radar": evidencia}

    # v2: rain is necessary; terrain modulates it (x f_min .. x1); radar adds observed evidence.
    f_min = th["susceptibilidad_factor_min"]
    core = disparo * (f_min + (1 - f_min) * susceptibilidad)
    w_radar = th["pesos"]["evidencia_radar"]
    risk = 100 * ((1 - w_radar) * core + w_radar * evidencia if evidencia is not None else core)
    level = max((lv for lv in LEVELS if risk >= th["niveles"][lv]), key=LEVELS.index)

    # --- confidence: indicator quality x share of the model actually observed (radar missing -> less)
    quality = sum(CONF_VALUE[i["confianza"]] for i in found.values()) / len(found)
    observed = 1.0 if evidencia is not None else 1.0 - w_radar
    conf_pct = round(100 * quality * observed, 1)
    conf_label = "alta" if conf_pct >= 70 else "media" if conf_pct >= 45 else "baja"

    alert = {
        "id": hashlib.sha1(f"{req.case_id}|{req.bbox}|{req.fecha}|{hazard}".encode()).hexdigest()[:12],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "case_id": req.case_id,
        "area": {"nombre": req.nombre, "bbox": list(req.bbox)},
        "fecha_referencia": req.fecha,
        "peligro": hazard,
        "nivel": level,
        "indice_riesgo": round(risk, 1),
        "confianza": {"porcentaje": conf_pct, "etiqueta": conf_label, "faltantes": missing},
        "componentes": {k: (round(v, 3) if v is not None else None) for k, v in comps.items()},
        "indicadores": list(found.values()),
        "motivos": _reasons(found, comps, hazard),
        "acciones": _actions(st.protocols, level, hazard),
        "fuentes": sorted({i["evidencia"].split(" (")[0] for i in found.values()}),
        "caveats": sorted({i["caveat"] for i in found.values() if i.get("caveat")}),
    }
    return schema.require("alert", alert)


def _reasons(found: dict[str, dict], comps: dict[str, float | None], hazard: str) -> list[str]:
    r = [f"Lluvia: {found['lluvia_max_24h_mm']['valor']:.1f} mm en 24 h y "
         f"{found['lluvia_acumulada_72h_mm']['valor']:.1f} mm en 72 h (disparo {comps['disparo']:.2f})."]
    r.append(f"Relieve: {found['fraccion_pendiente_fuerte_pct']['valor']:.0f} % del área con pendiente fuerte "
             f"(susceptibilidad a {hazard} {comps['susceptibilidad']:.2f}).")
    if comps["evidencia_radar"] is not None:
        sed = found.get("radar_sedimento_corredor_km2", {}).get("valor")
        wat = found.get("radar_agua_nueva_km2", {}).get("valor")
        r.append(f"Radar: sedimento junto a cauces {sed} km², agua nueva {wat} km² (evidencia {comps['evidencia_radar']:.2f}).")
    return r


def _actions(protocols: dict[str, Any], level: str, hazard: str) -> dict[str, list[str]]:
    base = protocols["comunes"][level]
    extra = protocols.get("por_peligro", {}).get(hazard, {}).get(level, {})
    return {aud: [*base.get(aud, []), *extra.get(aud, [])] for aud in ("tecnicos", "ciudadania")}
