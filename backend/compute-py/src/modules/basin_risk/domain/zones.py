"""Subsistemas Qucha-SAR (Norte, Centro, Sur) y evaluación determinista de riesgo en Cochabamba.

Combina tres pilares físicos verificables:
1. Topografía real (Copernicus DEM GLO-30: subcuencas D8, elevación, pendiente, Cota 2750, TWI).
2. Disparador hidrometeorológico diario (GPM_3IMERGDL / NASA POWER: lluvia 24h, API-7d, acumulado 30d).
3. Pre-acondicionamiento y cobertura (anomalía OPERA DSWx-S1, cambios SAR y focos FIRMS > 2750 m).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

AlertLevel = Literal["verde", "amarillo", "naranja", "rojo"]
HazardType = Literal["slope_mudflow", "flood_saturation", "water_balance"]
SubsystemId = Literal["north", "central", "south"]

BASIN_BBOX: tuple[float, float, float, float] = (-66.536394, -17.870027, -65.574648, -17.186852)
COTA_URBANA_M = 2750.0


@dataclass(frozen=True)
class SubsystemSpec:
    id: SubsystemId
    name_es: str
    name_en: str
    focus_es: str
    focus_en: str


SUBSYSTEM_SPECS: dict[SubsystemId, SubsystemSpec] = {
    "north": SubsystemSpec(
        id="north",
        name_es="Norte · Cabecera Tunari (> 2750 m)",
        name_en="North · Tunari Headwaters (> 2750 m)",
        focus_es="Deslizamientos, mazamorras y pérdida de cobertura sobre torrenteras; cautela SAR en pendientes >= 25°.",
        focus_en="Landslides, debris flows and post-fire cover loss above torrents; SAR foreshortening caution >= 25°.",
    ),
    "central": SubsystemSpec(
        id="central",
        name_es="Centro · Eje Río Rocha y Valle Urbano",
        name_en="Central · Rocha River Corridor & Urban Valley",
        focus_es="Anegamiento pluvial/fluvial y expansión de agua superficial fuera de cauces permanentes.",
        focus_en="Urban waterlogging and surface water expansion outside permanent river/lagoon beds.",
    ),
    "south": SubsystemSpec(
        id="south",
        name_es="Sur · Balance Hídrico y Cosecha (Indicativo)",
        name_en="South · Indicative Water Balance & Harvesting",
        focus_es="Monitoreo indicativo de déficit pluviométrico y área superficial en km² (sin estimar volumen en m³).",
        focus_en="Indicative rainfall deficit and surface water extent in km² (no fabricated m³ volume).",
    ),
}


@dataclass(frozen=True)
class BasinZone:
    id: str
    name_es: str
    name_en: str
    hazard: HazardType
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    description_es: str
    description_en: str
    subsystem: SubsystemId = "central"
    area_km2: float = 0.0
    downstream_target: str | None = None
    geometry: dict[str, Any] | None = None


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _level_from_score(score: float) -> AlertLevel:
    if score >= 72.0:
        return "rojo"
    if score >= 50.0:
        return "naranja"
    if score >= 28.0:
        return "amarillo"
    return "verde"


def evaluate_zone_risk(
    zone: Any,
    dem_stats: dict[str, Any],
    precip_summary: dict[str, Any],
    fire_count_30d: int | None,
    sat_zone_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calcula el índice determinista (0–100) diferenciando Norte, Centro y Sur."""
    steep_pct = float(dem_stats.get("steep_pct_gt20", 0.0))
    steep_25_pct = float(dem_stats.get("steep_pct_gt25", 0.0))
    slope_p90 = float(dem_stats.get("slope_p90_deg", 0.0))
    above_2750_pct = float(dem_stats.get("above_2750_pct", 0.0))
    valley_low_pct = float(dem_stats.get("low_slope_pct_lt5", 0.0))
    twi_p90 = float(dem_stats.get("twi_p90", 0.0))

    rain_7d = float(precip_summary.get("sum_7d_mm", 0.0))
    rain_30d = float(precip_summary.get("sum_30d_mm", 0.0))
    max_24h = float(precip_summary.get("max_24h_30d_mm", 0.0))
    latest_mm = float(precip_summary.get("latest_mm", 0.0))
    precip_source = str(precip_summary.get("source", "NASA POWER PRECTOTCORR"))
    imerg_active = bool(precip_summary.get("imerg_spatial_active", False))

    sat_m = sat_zone_metrics or {}
    water_anomaly_km2 = float(sat_m.get("water_anomaly_km2", 0.0))
    opera_water_km2 = float(sat_m.get("opera_water_km2", 0.0))
    baseline_dry_km2 = float(sat_m.get("baseline_dry_km2", 0.0))
    sar_change_idx = sat_m.get("sar_change_index")

    rain_score = _clamp(rain_7d * 0.45 + max_24h * 0.62 + rain_30d * 0.05, 0.0, 56.0)
    fire_boost = _clamp((fire_count_30d or 0) * 2.1, 0.0, 16.0)
    water_boost = _clamp(water_anomaly_km2 * 6.5, 0.0, 22.0)

    if zone.hazard == "slope_mudflow":
        # En cabecera Norte, la pendiente solo amplifica cuando existe disparador húmedo (o cicatriz de fuego).
        wet_gate = _clamp((rain_7d + max_24h * 1.4) / 28.0, 0.25, 1.0)
        terrain_base = _clamp(steep_pct * 0.34 + slope_p90 * 0.45, 0.0, 26.0)
        score = _clamp(terrain_base * wet_gate + rain_score * 0.92 + fire_boost, 0.0, 100.0)
        if fire_boost >= 6.0 and rain_7d >= 15.0:
            dom_es = "Lluvia sobre ladera con focos FIRMS recientes (> 2750 m)"
            dom_en = "Rain over slopes with recent FIRMS hotspots (> 2750 m)"
        elif rain_score >= 22.0:
            dom_es = f"Lluvia 7d ({rain_7d:.1f} mm) sobre pendiente p90 {slope_p90:.1f}°"
            dom_en = f"7d rain ({rain_7d:.1f} mm) over {slope_p90:.1f}° p90 slope"
        else:
            dom_es = f"Pre-acondicionamiento topográfico Tunari (p90 {slope_p90:.1f}°)"
            dom_en = f"Tunari topographic susceptibility (p90 {slope_p90:.1f}°)"
    elif zone.hazard == "flood_saturation":
        convergence_base = _clamp(valley_low_pct * 0.28 + max(0.0, twi_p90 - 7.0) * 1.8, 0.0, 24.0)
        wet_gate = _clamp((rain_7d + max_24h + water_anomaly_km2 * 8.0) / 30.0, 0.28, 1.0)
        score = _clamp(convergence_base * wet_gate + rain_score * 0.92 + water_boost, 0.0, 100.0)
        if water_anomaly_km2 >= 0.4:
            dom_es = f"Anomalía agua OPERA (+{water_anomaly_km2:.2f} km²) + convergencia TWI"
            dom_en = f"OPERA water anomaly (+{water_anomaly_km2:.2f} km²) + TWI convergence"
        elif rain_score >= 20.0:
            dom_es = f"Lluvia 7d ({rain_7d:.1f} mm) en llanura aluvial (< 5°)"
            dom_en = f"7d rain ({rain_7d:.1f} mm) on alluvial flat (< 5°)"
        else:
            dom_es = f"Convergencia de valle (TWI p90 {twi_p90:.1f}) en cauce Rocha"
            dom_en = f"Valley convergence (TWI p90 {twi_p90:.1f}) along Rocha"
    else:  # water_balance (Sur indicativo: nunca inventar m³)
        if rain_30d < 10.0:
            dry_stress = 32.0
            dom_es = f"Déficit pluviométrico severo ({rain_30d:.1f} mm / 30 d) · espejo {opera_water_km2:.2f} km²"
            dom_en = f"Severe rainfall deficit ({rain_30d:.1f} mm / 30 d) · water {opera_water_km2:.2f} km²"
        elif rain_30d < 25.0:
            dry_stress = 22.0
            dom_es = f"Estiaje moderado ({rain_30d:.1f} mm / 30 d) · espejo {opera_water_km2:.2f} km²"
            dom_en = f"Moderate dry stress ({rain_30d:.1f} mm / 30 d) · water {opera_water_km2:.2f} km²"
        else:
            dry_stress = 0.0
            dom_es = f"Recarga / espejo superficial ({opera_water_km2:.2f} km² · lluvia 7d {rain_7d:.1f} mm)"
            dom_en = f"Recharge / surface water ({opera_water_km2:.2f} km² · 7d rain {rain_7d:.1f} mm)"
        overflow_pressure = _clamp(rain_7d * 0.45 + max_24h * 0.65 + water_boost, 0.0, 68.0)
        score = _clamp(max(dry_stress, overflow_pressure + valley_low_pct * 0.12), 0.0, 100.0)

    score_rounded = round(score, 1)
    level = _level_from_score(score_rounded)

    drivers: list[dict[str, str]] = [
        {"label_es": "Lluvia 7 días", "label_en": "7-day rainfall", "value": f"{rain_7d:.1f} mm"},
        {"label_es": "Pico máx. 24 h", "label_en": "Peak 24 h rain", "value": f"{max_24h:.1f} mm"},
        {"label_es": "Pendiente p90 (DEM 30 m)", "label_en": "Slope p90 (30 m DEM)", "value": f"{slope_p90:.1f}°"},
        {"label_es": "Área > 2750 m s.n.m.", "label_en": "Area > 2750 m a.s.l.", "value": f"{above_2750_pct:.1f}%"},
    ]
    if zone.subsystem == "south":
        drivers.append({
            "label_es": "Espejo de agua (indicativo)",
            "label_en": "Surface water (indicative)",
            "value": f"{opera_water_km2:.2f} km² (sin m³)",
        })
    elif water_anomaly_km2 > 0 or zone.subsystem == "central":
        drivers.append({
            "label_es": "Anomalía OPERA DSWx-S1",
            "label_en": "OPERA DSWx-S1 anomaly",
            "value": f"+{water_anomaly_km2:.2f} km²",
        })
    if fire_count_30d is not None:
        drivers.append({
            "label_es": "Focos FIRMS (> 2750 m / subcuenca)",
            "label_en": "FIRMS hotspots (30 d)",
            "value": str(fire_count_30d),
        })

    caveats: list[str] = [
        "Ciclo NISAR de 12 días: mide pre-acondicionamiento superficial; la lluvia diaria dispara la alerta."
    ]
    if steep_25_pct >= 12.0:
        caveats.append(
            f"{steep_25_pct:.0f}% del área tiene pendiente >= 25°: escorzo/sombra geométrica SAR activa."
        )
    if zone.subsystem == "south":
        caveats.append(
            "Balance Sur reportado únicamente en km² superficiales y mm de lluvia; no se estiman m³ sin batimetría."
        )

    geometry = getattr(zone, "geometry", None) or {
        "type": "Polygon",
        "coordinates": [[
            [zone.bbox[0], zone.bbox[1]],
            [zone.bbox[2], zone.bbox[1]],
            [zone.bbox[2], zone.bbox[3]],
            [zone.bbox[0], zone.bbox[3]],
            [zone.bbox[0], zone.bbox[1]],
        ]],
    }

    return {
        "id": zone.id,
        "subsystem": getattr(zone, "subsystem", "central"),
        "downstream_target": getattr(zone, "downstream_target", None),
        "name": {"es": zone.name_es, "en": zone.name_en},
        "description": {"es": zone.description_es, "en": zone.description_en},
        "hazard": zone.hazard,
        "area_km2": round(float(getattr(zone, "area_km2", 0.0)), 1),
        "bbox": [round(float(v), 5) for v in zone.bbox],
        "centroid": [round(float(v), 5) for v in zone.centroid],
        "geometry": geometry,
        "score": score_rounded,
        "level": level,
        "dominant_driver": {"es": dom_es, "en": dom_en},
        "terrain": dem_stats,
        "precipitation": {
            "source": precip_source,
            "imerg_spatial_active": imerg_active,
            "latest_mm": round(latest_mm, 2),
            "sum_7d_mm": round(rain_7d, 1),
            "sum_30d_mm": round(rain_30d, 1),
            "max_24h_30d_mm": round(max_24h, 1),
        },
        "fire_hotspots_30d": fire_count_30d,
        "surface_water": {
            "opera_water_km2": round(opera_water_km2, 3),
            "baseline_dry_km2": round(baseline_dry_km2, 3),
            "water_anomaly_km2": round(water_anomaly_km2, 3),
            "sar_change_index": round(float(sar_change_idx), 3) if sar_change_idx is not None else None,
            "note": (
                "Área superficial indicativa en km² (sin m³)."
                if getattr(zone, "subsystem", "central") == "south"
                else "Anomalía estimada respecto a línea base seca."
            ),
        },
        "drivers": drivers,
        "caveats": caveats,
    }


def build_subsystems_summary(zones_out: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa subcuencas evaluadas en los 3 subsistemas operativos Norte–Centro–Sur."""
    rank = {"verde": 0, "amarillo": 1, "naranja": 2, "rojo": 3}
    order: tuple[SubsystemId, ...] = ("north", "central", "south")
    result: list[dict[str, Any]] = []
    for sub_id in order:
        spec = SUBSYSTEM_SPECS[sub_id]
        members = [z for z in zones_out if z["subsystem"] == sub_id]
        if not members:
            continue
        top = max(members, key=lambda z: z["score"])
        level = max((z["level"] for z in members), key=lambda lv: rank[lv])
        if sub_id == "south":
            total_km2 = sum(float(z.get("surface_water", {}).get("opera_water_km2", 0.0)) for z in members)
            avg_30d = sum(float(z["precipitation"]["sum_30d_mm"]) for z in members) / len(members)
            metric_es = f"Espejo {total_km2:.2f} km² · Lluvia 30d {avg_30d:.1f} mm"
            metric_en = f"Surface {total_km2:.2f} km² · 30d rain {avg_30d:.1f} mm"
        elif sub_id == "central":
            anom_km2 = sum(float(z.get("surface_water", {}).get("water_anomaly_km2", 0.0)) for z in members)
            max_7d = max(float(z["precipitation"]["sum_7d_mm"]) for z in members)
            metric_es = f"Anomalía +{anom_km2:.2f} km² · Lluvia 7d máx. {max_7d:.1f} mm"
            metric_en = f"Anomaly +{anom_km2:.2f} km² · Max 7d rain {max_7d:.1f} mm"
        else:
            max_slope = max(float(z["terrain"].get("steep_pct_gt25", 0.0)) for z in members)
            fires = sum(int(z.get("fire_hotspots_30d") or 0) for z in members)
            metric_es = f"Índice {top['score']:.0f}/100 · {max_slope:.0f}% >= 25° · {fires} focos"
            metric_en = f"Score {top['score']:.0f}/100 · {max_slope:.0f}% >= 25° · {fires} fires"

        result.append({
            "id": spec.id,
            "name": {"es": spec.name_es, "en": spec.name_en},
            "focus": {"es": spec.focus_es, "en": spec.focus_en},
            "level": level,
            "max_score": top["score"],
            "subbasin_ids": [z["id"] for z in members],
            "summary_metric": {"es": metric_es, "en": metric_en},
        })
    return result
