"""Planificación hidro-espacial de red estratégica de tanques de cosecha de lluvia.

Combina datos físicos verificables de la cuenca de Cochabamba:
1. Topografía y acumulación D8 real (Copernicus DEM GLO-30 + `HydroGridArtifact`).
2. Precipitación diaria y rachas secas reales (NASA POWER / GPM IMERG, 60 días).
3. Focos activos/recientes de calor e incendios (NASA FIRMS VIIRS 375 m, últimos 60 días).
4. Distritos GAMC (`districts.geojson`) y cabeceras del sur en déficit hídrico.

Opcionalmente sintetiza recomendaciones estratégicas con Gemini (`google-genai`)
estrictamente acotadas a las métricas calculadas, con respaldo determinista automático.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel
from shapely.geometry import Point, shape
from shapely.prepared import prep

from config.settings import get_settings
from modules.basin_risk.adapters.copernicus_dem import CopernicusDemProvider
from modules.basin_risk.adapters.dem_hydrology import HydroGridArtifact, SubBasinFeature
from modules.basin_risk.adapters.nasa_precip import NasaPrecipProvider
from modules.basin_risk.domain.zones import BASIN_BBOX
from modules.events.adapters.firms_client import FirmsClient

log = logging.getLogger("basin_risk.tanks")

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tank-hydro")
_EARTH_RADIUS_KM = 6371.0
_SERVICE_RADIUS_DROUGHT_KM = 16.0
_SERVICE_RADIUS_FIRE_KM = 18.0
_COVERAGE_RADIUS_KM = 14.0

RoleType = Literal["dual", "drought", "fire"]

# Etiquetas de comunas GAMC para presentar distritos con claridad geográfica.
_SOUTH_DRY_DISTRICTS = {"D6", "D7", "D8", "D9", "D14", "D15"}
_TRANSITION_DISTRICTS = {"D4", "D5", "D10", "D11", "D12"}

# Zonas rurales/periurbanas del sur fuera del radio urbano compacto D1–D15.
_RURAL_DROUGHT_HUBS: tuple[dict[str, Any], ...] = (
    {
        "id": "SUR-ARRUMANI",
        "name_es": "Arrumani – Santiváñez (Sur seco)",
        "name_en": "Arrumani – Santiváñez (Dry South)",
        "subbasin_id": "sur-arrumani-santivanez",
        "lon": -66.228,
        "lat": -17.535,
        "base_exposure": 26.0,
    },
    {
        "id": "SUR-ANGOSTURA",
        "name_es": "Valle Alto – La Angostura",
        "name_en": "Valle Alto – La Angostura",
        "subbasin_id": "sur-angostura-valle-alto",
        "lon": -66.058,
        "lat": -17.532,
        "base_exposure": 20.0,
    },
)


class TankPriorityAction(BaseModel):
    tank_id: str
    title: str
    impact: str


class TankNetworkLlmReport(BaseModel):
    headline: str
    executive_summary: str
    drought_strategy: str
    wildfire_strategy: str
    priority_actions: list[TankPriorityAction]
    data_caveats: list[str]


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2.0 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _precip_drought_metrics(series: list[dict[str, Any]]) -> dict[str, Any]:
    """Extrae días secos, racha máxima seca y acumulados reales desde la serie diaria."""
    if not series:
        return {
            "sum_7d_mm": 0.0,
            "sum_30d_mm": 0.0,
            "sum_60d_mm": 0.0,
            "max_24h_30d_mm": 0.0,
            "dry_days_60d": 0,
            "max_dry_spell_days": 0,
            "days_count": 0,
        }
    vals = [float(item.get("mm", 0.0)) for item in series]
    last_30 = vals[-30:]
    last_7 = vals[-7:]
    dry_days = sum(1 for v in vals if v < 1.0)
    spell = 0
    max_spell = 0
    for v in vals:
        if v < 1.0:
            spell += 1
            if spell > max_spell:
                max_spell = spell
        else:
            spell = 0
    return {
        "sum_7d_mm": round(sum(last_7), 1),
        "sum_30d_mm": round(sum(last_30), 1),
        "sum_60d_mm": round(sum(vals), 1),
        "max_24h_30d_mm": round(max(last_30) if last_30 else 0.0, 1),
        "dry_days_60d": dry_days,
        "max_dry_spell_days": max_spell,
        "days_count": len(vals),
    }


def _load_districts(path: Path) -> list[dict[str, Any]]:
    try:
        fc = json.loads(path.read_text(encoding="utf-8"))
        return list(fc.get("features") or [])
    except (OSError, json.JSONDecodeError):
        return []


def _cluster_firms_hotspots(
    rows: list[dict[str, Any]],
    dem: CopernicusDemProvider,
    district_shapes: list[tuple[str, str, Any]],
) -> list[dict[str, Any]]:
    """Agrupa detecciones reales FIRMS (60 d) en focos espaciales (~3 km) con elevación real."""
    points: list[dict[str, Any]] = []
    for row in rows:
        try:
            lat = float(row.get("latitude", ""))
            lon = float(row.get("longitude", ""))
        except (TypeError, ValueError):
            continue
        if not (BASIN_BBOX[0] <= lon <= BASIN_BBOX[2] and BASIN_BBOX[1] <= lat <= BASIN_BBOX[3]):
            continue
        try:
            frp = float(row.get("frp") or 0.0)
        except (TypeError, ValueError):
            frp = 0.0
        points.append(
            {
                "lon": lon,
                "lat": lat,
                "frp": frp,
                "acq_date": str(row.get("acq_date") or ""),
            }
        )

    # Ordenar por intensidad descendente para anclar cada clúster en su foco más fuerte.
    points.sort(key=lambda p: (p["acq_date"], p["frp"]), reverse=True)
    clusters_raw: list[list[dict[str, Any]]] = []
    for pt in points:
        placed = False
        for grp in clusters_raw:
            anchor = grp[0]
            if _haversine_km(pt["lon"], pt["lat"], anchor["lon"], anchor["lat"]) <= 3.5:
                grp.append(pt)
                placed = True
                break
        if not placed:
            clusters_raw.append([pt])

    clusters: list[dict[str, Any]] = []
    for idx, grp in enumerate(clusters_raw, start=1):
        lon_c = sum(p["lon"] for p in grp) / len(grp)
        lat_c = sum(p["lat"] for p in grp) / len(grp)
        diag = dem.point_diagnostics(lon_c, lat_c) or {}
        subbasin_id = (diag.get("hydro") or {}).get("subbasin_id")
        elev_m = diag.get("elevation_m")
        max_frp = max(p["frp"] for p in grp)
        latest_date = max(p["acq_date"] for p in grp)

        pt_geom = Point(lon_c, lat_c)
        district_label = None
        for did, comuna, geom in district_shapes:
            if geom.contains(pt_geom):
                district_label = f"{did} · {comuna.title()}"
                break
        if district_label is None and district_shapes:
            # Si está fuera de D1–D15 urbano, referenciar por subcuenca o distrito más cercano.
            nearest_d = min(
                district_shapes,
                key=lambda item: _haversine_km(lon_c, lat_c, item[2].centroid.x, item[2].centroid.y),
            )
            dist_km = _haversine_km(lon_c, lat_c, nearest_d[2].centroid.x, nearest_d[2].centroid.y)
            district_label = f"Cerca {nearest_d[0]} ({dist_km:.1f} km)"

        clusters.append(
            {
                "id": f"FOCO-{idx:02d}",
                "lon": round(lon_c, 5),
                "lat": round(lat_c, 5),
                "elevation_m": elev_m,
                "subbasin_id": subbasin_id,
                "zone_label": district_label or "Cuenca Cochabamba",
                "hotspots_count": len(grp),
                "max_frp_mw": round(max_frp, 1),
                "latest_date": latest_date,
                "severity_score": round(len(grp) * 8.0 + max_frp * 1.4, 1),
            }
        )

    clusters.sort(key=lambda c: c["severity_score"], reverse=True)
    return clusters[:12]


def _pick_capture_node_in_subbasin(
    sb: SubBasinFeature,
    hydro: HydroGridArtifact,
    dem: CopernicusDemProvider,
) -> dict[str, Any] | None:
    """Selecciona sobre la grilla D8 un nodo real de captación construible y con buena cota."""
    mask = hydro.label_grid == sb.code
    ys, xs = np.where(mask & (hydro.acc_grid >= 6))
    if len(ys) == 0:
        ys, xs = np.where(mask)
    if len(ys) == 0:
        return None

    acc_vals = hydro.acc_grid[ys, xs].astype(np.float64)
    q70 = float(np.percentile(acc_vals, 70))
    # Capamos el máximo extremo para no caer solo en el fondo absoluto de la desembocadura.
    q98 = float(np.percentile(acc_vals, 98))
    candidates_idx = np.where((acc_vals >= q70) & (acc_vals <= max(q98, q70 + 1.0)))[0]
    if len(candidates_idx) == 0:
        candidates_idx = np.arange(len(ys))

    # Submuestrear hasta ~80 candidatos distribuidos para evaluar pendiente y elevación reales.
    step = max(1, len(candidates_idx) // 80)
    sampled = candidates_idx[::step][:80]

    best: dict[str, Any] | None = None
    best_score = -1e9
    for k in sampled:
        r = int(ys[k])
        c = int(xs[k])
        lon = hydro.min_lon + (c + 0.5) * hydro.dx
        lat = hydro.max_lat - (r + 0.5) * hydro.dy
        diag = dem.point_diagnostics(lon, lat)
        if not diag:
            continue
        slope = float(diag.get("slope_deg") or 0.0)
        elev = float(diag.get("elevation_m") or 0.0)
        acc = int(hydro.acc_grid[r, c])
        twi = float(hydro.twi_grid[r, c])

        # Preferimos pendientes construibles (<= 19°) y cotas de pie de monte accesibles:
        # Norte: franja 2740–3250 m (dominancia por gravedad sobre valle ~2550 m y acceso vial WUI).
        # Sur/Centro: franja 2580–2980 m sobre abanicos y quebradas secas.
        slope_penalty = 0.0 if slope <= 18.0 else (slope - 18.0) * 4.0
        if sb.subsystem == "north":
            if 2740.0 <= elev <= 3250.0:
                elev_score = 18.0 - abs(elev - 2950.0) / 150.0
            elif elev > 3250.0:
                elev_score = max(-25.0, 10.0 - (elev - 3250.0) / 45.0)
            else:
                elev_score = 8.0
        elif sb.subsystem == "south":
            if 2600.0 <= elev <= 2980.0:
                elev_score = 15.0 - abs(elev - 2740.0) / 140.0
            else:
                elev_score = max(-10.0, 6.0 - abs(elev - 2740.0) / 180.0)
        else:
            elev_score = 10.0 - abs(elev - 2630.0) / 160.0

        cand_score = math.log1p(acc) * 3.8 + twi * 0.5 + elev_score - slope_penalty
        if cand_score > best_score:
            best_score = cand_score
            best = {
                "lon": round(lon, 5),
                "lat": round(lat, 5),
                "elevation_m": round(elev, 1),
                "slope_deg": round(slope, 1),
                "flow_acc_cells": acc,
                "twi": round(twi, 2),
                "site_score": round(cand_score, 2),
            }
    return best


class TankNetworkService:
    """Planificador de red estratégica de tanques para sequía e incendios."""

    def __init__(
        self,
        dem: CopernicusDemProvider,
        precip: NasaPrecipProvider,
        firms_client: FirmsClient | None,
        districts_path: Path,
    ) -> None:
        self._dem = dem
        self._precip = precip
        self._firms = firms_client
        self._districts_path = districts_path
        self._cache: dict[str, Any] | None = None
        self._cache_ts: float = 0.0
        self._lock = asyncio.Lock()
        self._gemini_auth_failed: bool = False

    async def network(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force_refresh and self._cache is not None and (now - self._cache_ts) < 900.0:
            return self._cache
        async with self._lock:
            now = time.monotonic()
            if not force_refresh and self._cache is not None and (now - self._cache_ts) < 900.0:
                return self._cache
            payload = await self._build_network()
            self._cache = payload
            self._cache_ts = time.monotonic()
            return payload

    async def analyze(self, focus_question: str | None = None, lang: str = "es") -> dict[str, Any]:
        """Ejecuta análisis estratégico (Gemini si disponible/válido; respaldo físico si falla)."""
        base = await self.network()
        lang_norm = "en" if lang.lower().startswith("en") else "es"
        llm_report, mode, model_used, note = await self._run_llm_or_fallback(
            base,
            focus_question=(focus_question or "").strip() or None,
            lang=lang_norm,
        )
        return {
            **base,
            "analysis": llm_report,
            "analysis_source": mode,
            "llm_model": model_used,
            "analysis_note": note,
            "focus_question": (focus_question or "").strip() or None,
        }

    async def _collect_firms_60d(self) -> list[dict[str, Any]]:
        if not self._firms or not getattr(self._firms, "configured", False):
            return []
        end = date.today()
        windows = [end - timedelta(days=k + 4) for k in range(0, 60, 5)]

        async def _fetch_one(start: date) -> list[dict[str, Any]]:
            try:
                src = await asyncio.wait_for(self._firms.source_for(start), timeout=12.0)  # type: ignore[union-attr]
                return await asyncio.wait_for(
                    self._firms.area(src, BASIN_BBOX, start, 5),  # type: ignore[union-attr]
                    timeout=15.0,
                )
            except Exception as exc:
                log.debug("FIRMS ventana %s sin respuesta (%s)", start, exc)
                return []

        batches = await asyncio.gather(*(_fetch_one(st) for st in windows))
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        for batch in batches:
            for r in batch:
                key = (
                    str(r.get("latitude", "")),
                    str(r.get("longitude", "")),
                    str(r.get("acq_date", "")),
                    str(r.get("acq_time", "")),
                )
                if key not in seen:
                    seen.add(key)
                    rows.append(r)
        return rows

    async def _build_network(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        hydro = await loop.run_in_executor(_POOL, self._dem.ensure_hydrology)
        dem_stats = await loop.run_in_executor(_POOL, self._dem.all_polygon_stats)

        precip_tasks = [
            self._precip.daily_series(sb.id, sb.centroid[0], sb.centroid[1], days=60)
            for sb in hydro.subbasins
        ]
        firms_rows, precip_results = await asyncio.gather(
            self._collect_firms_60d(),
            asyncio.gather(*precip_tasks, return_exceptions=True),
        )

        precip_by_sb: dict[str, dict[str, Any]] = {}
        precip_source = "NASA POWER PRECTOTCORR"
        for sb, res in zip(hydro.subbasins, precip_results):
            if isinstance(res, dict):
                series = list(res.get("series") or [])
                metrics = _precip_drought_metrics(series)
                src = str((res.get("summary") or {}).get("source") or precip_source)
                precip_source = src
                precip_by_sb[sb.id] = metrics
            else:
                precip_by_sb[sb.id] = _precip_drought_metrics([])

        districts_raw = _load_districts(self._districts_path)
        district_shapes = [
            (
                str(feat.get("properties", {}).get("id") or ""),
                str(feat.get("properties", {}).get("comuna") or ""),
                shape(feat["geometry"]),
            )
            for feat in districts_raw
            if feat.get("geometry") and feat.get("properties", {}).get("id")
        ]

        # Computar puntos de captura DEM, clústeres FIRMS y objetivos de sequía en hilo de cómputo.
        def _compute_spatial() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
            clusters = _cluster_firms_hotspots(firms_rows, self._dem, district_shapes)
            drought_targets = self._evaluate_drought_targets(districts_raw, hydro, precip_by_sb, clusters)
            candidates: dict[str, dict[str, Any]] = {}
            for sb in hydro.subbasins:
                node = _pick_capture_node_in_subbasin(sb, hydro, self._dem)
                if node is not None:
                    candidates[sb.id] = node
            return clusters, drought_targets, candidates

        fire_clusters, drought_targets, capture_nodes = await loop.run_in_executor(_POOL, _compute_spatial)

        sb_by_id = {sb.id: sb for sb in hydro.subbasins}
        tank_candidates: list[dict[str, Any]] = []
        for idx, (sb_id, node) in enumerate(capture_nodes.items(), start=1):
            sb = sb_by_id[sb_id]
            p = precip_by_sb[sb_id]
            st = dem_stats.get(sb_id) or {}
            rain_30d = float(p["sum_30d_mm"])
            rain_60d = float(p["sum_60d_mm"])
            max_24h = float(p["max_24h_30d_mm"])
            dry_days = int(p["dry_days_60d"])
            acc = int(node["flow_acc_cells"])

            # Área efectiva de captación del micro-dique / toma (2.0 – 8.0 ha) según acumulación D8.
            effective_capture_ha = round(min(8.0, max(2.2, 1.8 + math.log10(max(acc, 10)) * 1.35)), 2)
            slope_deg = float(node["slope_deg"])
            runoff_coeff = round(min(0.68, max(0.42, 0.44 + slope_deg * 0.011)), 2)
            # Cosecha física: área (ha -> 10 000 m²) * lluvia (m) * coeficiente de escorrentía.
            harvest_30d_m3 = round(effective_capture_ha * 10000.0 * (rain_30d / 1000.0) * runoff_coeff)
            storm_capture_m3 = round(effective_capture_ha * 10000.0 * (max_24h / 1000.0) * runoff_coeff)

            drought_links: list[dict[str, Any]] = []
            for dt in drought_targets:
                dist = _haversine_km(node["lon"], node["lat"], dt["lon"], dt["lat"])
                if dist <= _SERVICE_RADIUS_DROUGHT_KM:
                    elev_diff = round(node["elevation_m"] - float(dt["elevation_m"]), 1)
                    drought_links.append(
                        {
                            "id": dt["id"],
                            "name_es": dt["name_es"],
                            "name_en": dt["name_en"],
                            "distance_km": round(dist, 2),
                            "elevation_diff_m": elev_diff,
                            "gravity_fed": elev_diff >= 15.0,
                            "drought_score": dt["drought_score"],
                            "dry_days_60d": dt["dry_days_60d"],
                            "rain_30d_mm": dt["rain_30d_mm"],
                            "lon": dt["lon"],
                            "lat": dt["lat"],
                        }
                    )
            drought_links.sort(key=lambda item: (item["distance_km"] - item["drought_score"] * 0.08))
            if not drought_links and drought_targets:
                nearest_dt = min(
                    drought_targets,
                    key=lambda dt: _haversine_km(node["lon"], node["lat"], dt["lon"], dt["lat"]),
                )
                dist = _haversine_km(node["lon"], node["lat"], nearest_dt["lon"], nearest_dt["lat"])
                elev_diff = round(node["elevation_m"] - float(nearest_dt["elevation_m"]), 1)
                drought_links.append(
                    {
                        "id": nearest_dt["id"],
                        "name_es": nearest_dt["name_es"],
                        "name_en": nearest_dt["name_en"],
                        "distance_km": round(dist, 2),
                        "elevation_diff_m": elev_diff,
                        "gravity_fed": elev_diff >= 15.0,
                        "drought_score": nearest_dt["drought_score"],
                        "dry_days_60d": nearest_dt["dry_days_60d"],
                        "rain_30d_mm": nearest_dt["rain_30d_mm"],
                        "lon": nearest_dt["lon"],
                        "lat": nearest_dt["lat"],
                    }
                )
            drought_links = drought_links[:3]

            fire_links: list[dict[str, Any]] = []
            for fc in fire_clusters:
                dist = _haversine_km(node["lon"], node["lat"], fc["lon"], fc["lat"])
                if dist <= _SERVICE_RADIUS_FIRE_KM:
                    elev_diff = round(node["elevation_m"] - float(fc.get("elevation_m") or node["elevation_m"]), 1)
                    fire_links.append(
                        {
                            "id": fc["id"],
                            "zone_label": fc["zone_label"],
                            "distance_km": round(dist, 2),
                            "elevation_diff_m": elev_diff,
                            "gravity_fed": elev_diff >= 15.0,
                            "hotspots_count": fc["hotspots_count"],
                            "max_frp_mw": fc["max_frp_mw"],
                            "latest_date": fc["latest_date"],
                            "lon": fc["lon"],
                            "lat": fc["lat"],
                        }
                    )
            fire_links.sort(key=lambda item: (item["distance_km"], -item["hotspots_count"]))
            if not fire_links and fire_clusters:
                nearest_fc = min(
                    fire_clusters,
                    key=lambda fc: _haversine_km(node["lon"], node["lat"], fc["lon"], fc["lat"]),
                )
                dist = _haversine_km(node["lon"], node["lat"], nearest_fc["lon"], nearest_fc["lat"])
                elev_diff = round(node["elevation_m"] - float(nearest_fc.get("elevation_m") or node["elevation_m"]), 1)
                fire_links.append(
                    {
                        "id": nearest_fc["id"],
                        "zone_label": nearest_fc["zone_label"],
                        "distance_km": round(dist, 2),
                        "elevation_diff_m": elev_diff,
                        "gravity_fed": elev_diff >= 15.0,
                        "hotspots_count": nearest_fc["hotspots_count"],
                        "max_frp_mw": nearest_fc["max_frp_mw"],
                        "latest_date": nearest_fc["latest_date"],
                        "lon": nearest_fc["lon"],
                        "lat": nearest_fc["lat"],
                    }
                )
            fire_links = fire_links[:3]

            near_drought = [d for d in drought_links if d["distance_km"] <= 12.5]
            near_fire = [f for f in fire_links if f["distance_km"] <= 12.5]
            best_d_km = drought_links[0]["distance_km"] if drought_links else 99.0
            best_f_km = fire_links[0]["distance_km"] if fire_links else 99.0
            if near_drought and near_fire:
                role: RoleType = "dual"
            elif best_f_km <= 11.5 and best_d_km > 12.5:
                role = "fire"
            elif best_d_km <= 9.0 and best_f_km > 12.5:
                role = "drought"
            elif best_f_km + 2.0 < best_d_km:
                role = "fire"
            elif best_d_km + 2.0 < best_f_km:
                role = "drought"
            else:
                role = "dual"

            # Dimensionamiento modular del tanque propuesto (500 a 2500 m³).
            raw_capacity = max(storm_capture_m3 * 1.1, min(harvest_30d_m3 * 0.28, 2500.0))
            recommended_capacity_m3 = int(min(2500, max(500, math.ceil(raw_capacity / 250.0) * 250)))

            gravity_bonus = 12.0 if any(x["gravity_fed"] for x in near_drought + near_fire) else 0.0
            drought_need = max((d["drought_score"] for d in near_drought), default=25.0)
            fire_need = min(40.0, sum(f["hotspots_count"] * 4.5 for f in near_fire))
            capture_need = min(30.0, rain_30d * 0.14 + math.log1p(acc) * 1.6)
            priority_score = round(
                min(100.0, 0.35 * drought_need + 0.35 * fire_need + 0.25 * capture_need + gravity_bonus),
                1,
            )

            short_name = sb.name_es.split("·")[-1].strip()
            tank_candidates.append(
                {
                    "id": f"TK-{idx:02d}",
                    "name_es": f"Tanque {short_name}",
                    "name_en": f"Tank {sb.name_en.split('·')[-1].strip()}",
                    "subbasin_id": sb_id,
                    "subbasin_name_es": sb.name_es,
                    "subbasin_name_en": sb.name_en,
                    "subsystem": sb.subsystem,
                    "role": role,
                    "priority_score": priority_score,
                    "lon": node["lon"],
                    "lat": node["lat"],
                    "elevation_m": node["elevation_m"],
                    "slope_deg": node["slope_deg"],
                    "flow_acc_cells": acc,
                    "twi": node["twi"],
                    "subbasin_steep_gt25_pct": float(st.get("steep_pct_gt25") or 0.0),
                    "rain_7d_mm": p["sum_7d_mm"],
                    "rain_30d_mm": rain_30d,
                    "rain_60d_mm": rain_60d,
                    "max_24h_30d_mm": max_24h,
                    "dry_days_60d": dry_days,
                    "effective_capture_ha": effective_capture_ha,
                    "runoff_coeff": runoff_coeff,
                    "harvest_30d_m3": harvest_30d_m3,
                    "storm_capture_m3": storm_capture_m3,
                    "recommended_capacity_m3": recommended_capacity_m3,
                    "gravity_ready": any(x["gravity_fed"] for x in drought_links + fire_links),
                    "nearby_drought_targets": drought_links,
                    "nearby_fire_targets": fire_links,
                }
            )

        # Seleccionar los 6 nodos más estratégicos asegurando cobertura Norte (incendios/cabecera),
        # Centro (regulación) y Sur (sequía + focos secos).
        tank_candidates.sort(key=lambda t: t["priority_score"], reverse=True)
        selected_tanks = self._select_balanced_tanks(tank_candidates, limit=6)

        covered_drought_ids = {
            dt["id"]
            for t in selected_tanks
            for dt in t["nearby_drought_targets"]
            if dt["distance_km"] <= _SERVICE_RADIUS_DROUGHT_KM
        }
        covered_fire_ids = {
            ft["id"]
            for t in selected_tanks
            for ft in t["nearby_fire_targets"]
            if ft["distance_km"] <= _SERVICE_RADIUS_FIRE_KM
        }
        covered_hotspots = sum(
            fc["hotspots_count"] for fc in fire_clusters if fc["id"] in covered_fire_ids
        )
        total_hotspots = sum(fc["hotspots_count"] for fc in fire_clusters)

        payload: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "dem": "Copernicus DEM GLO-30 (30 m) + Red D8",
                "precip": precip_source,
                "fires": f"NASA FIRMS VIIRS_NOAA20 (últimos 60 días · {len(firms_rows)} detecciones)",
                "districts": "GAMC Cercado (15 distritos) + cabeceras Sur",
            },
            "summary": {
                "tanks_count": len(selected_tanks),
                "total_storage_m3": sum(t["recommended_capacity_m3"] for t in selected_tanks),
                "estimated_30d_harvest_m3": sum(t["harvest_30d_m3"] for t in selected_tanks),
                "drought_targets_covered": len(covered_drought_ids),
                "drought_targets_total": len(drought_targets),
                "fire_clusters_covered": len(covered_fire_ids),
                "fire_clusters_total": len(fire_clusters),
                "fire_hotspots_covered": covered_hotspots,
                "fire_hotspots_total": total_hotspots,
                "gravity_fed_tanks": sum(1 for t in selected_tanks if t["gravity_ready"]),
            },
            "tanks": selected_tanks,
            "drought_targets": drought_targets,
            "fire_clusters": fire_clusters,
        }
        llm_report, mode, model_used, note = await self._run_llm_or_fallback(payload, focus_question=None, lang="es")
        payload["analysis"] = llm_report
        payload["analysis_source"] = mode
        payload["llm_model"] = model_used
        payload["analysis_note"] = note
        return payload

    def _select_balanced_tanks(self, ranked: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        used_ids: set[str] = set()
        # Asegurar cobertura equilibrada Sur (2), Norte (2) y Centro (2) según prioridad física.
        for sub in ("south", "north", "central", "south", "north", "central"):
            if len(selected) >= limit:
                break
            match = next((t for t in ranked if t["subsystem"] == sub and t["id"] not in used_ids), None)
            if match:
                selected.append(match)
                used_ids.add(match["id"])
        for t in ranked:
            if len(selected) >= limit:
                break
            if t["id"] not in used_ids:
                selected.append(t)
                used_ids.add(t["id"])
        selected.sort(key=lambda t: t["priority_score"], reverse=True)
        return selected

    def _evaluate_drought_targets(
        self,
        districts_raw: list[dict[str, Any]],
        hydro: HydroGridArtifact,
        precip_by_sb: dict[str, dict[str, Any]],
        fire_clusters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        max_30d = max((float(v["sum_30d_mm"]) for v in precip_by_sb.values()), default=150.0) or 150.0

        def _score_point(
            tid: str,
            name_es: str,
            name_en: str,
            lon: float,
            lat: float,
            sb_fallback: str | None,
            base_exposure: float,
        ) -> dict[str, Any]:
            diag = self._dem.point_diagnostics(lon, lat) or {}
            elev_m = float(diag.get("elevation_m") or 2580.0)
            slope_deg = float(diag.get("slope_deg") or 3.0)
            sb_id = (diag.get("hydro") or {}).get("subbasin_id") or sb_fallback or "centro-rocha-cercado"
            p = precip_by_sb.get(sb_id) or next(iter(precip_by_sb.values()))
            rain_30d = float(p["sum_30d_mm"])
            dry_days = int(p["dry_days_60d"])
            max_spell = int(p["max_dry_spell_days"])

            deficit_rel = max(0.0, (max_30d - rain_30d) / max_30d) * 28.0
            dry_frac = (dry_days / 60.0) * 34.0
            spell_pts = min(20.0, max_spell * 1.4)
            slope_pts = 8.0 if slope_deg >= 12.0 else 3.0
            fire_near = any(_haversine_km(lon, lat, fc["lon"], fc["lat"]) <= 8.0 for fc in fire_clusters)
            fire_pts = 8.0 if fire_near else 0.0
            score = round(min(100.0, base_exposure + dry_frac + spell_pts + deficit_rel + slope_pts + fire_pts), 1)
            return {
                "id": tid,
                "name_es": name_es,
                "name_en": name_en,
                "lon": round(lon, 5),
                "lat": round(lat, 5),
                "elevation_m": round(elev_m, 1),
                "subbasin_id": sb_id,
                "rain_30d_mm": round(rain_30d, 1),
                "dry_days_60d": dry_days,
                "max_dry_spell_days": max_spell,
                "drought_score": score,
            }

        for feat in districts_raw:
            props = feat.get("properties") or {}
            did = str(props.get("id") or "")
            comuna = str(props.get("comuna") or "").title()
            centro = props.get("centro") or []
            if not did or len(centro) != 2:
                continue
            # Solo priorizamos distritos con exposición estacional a sequía / escasez sur o ladera seca.
            if did in _SOUTH_DRY_DISTRICTS:
                base_exp = 24.0
            elif did in _TRANSITION_DISTRICTS:
                base_exp = 13.0
            else:
                base_exp = 7.0
            targets.append(
                _score_point(
                    did,
                    f"{did} · {comuna}",
                    f"{did} · {comuna}",
                    float(centro[0]),
                    float(centro[1]),
                    None,
                    base_exp,
                )
            )

        for hub in _RURAL_DROUGHT_HUBS:
            targets.append(
                _score_point(
                    hub["id"],
                    hub["name_es"],
                    hub["name_en"],
                    float(hub["lon"]),
                    float(hub["lat"]),
                    str(hub["subbasin_id"]),
                    float(hub["base_exposure"]),
                )
            )

        targets.sort(key=lambda t: t["drought_score"], reverse=True)
        return targets[:8]

    async def _run_llm_or_fallback(
        self,
        payload: dict[str, Any],
        focus_question: str | None,
        lang: str,
    ) -> tuple[dict[str, Any], str, str | None, str]:
        settings = get_settings()
        api_key = (settings.gemini_api_key or "").strip()
        if api_key and not api_key.startswith("your-") and not self._gemini_auth_failed:
            models = []
            for m in (settings.gemini_stt_model, settings.gemini_fallback_model, "gemini-2.5-flash"):
                m_clean = (m or "").strip()
                if m_clean and m_clean not in models:
                    models.append(m_clean)
            brief = _build_llm_brief(payload, focus_question, lang)
            loop = asyncio.get_running_loop()
            for model_name in models:
                try:
                    report = await asyncio.wait_for(
                        loop.run_in_executor(_POOL, _call_gemini_sync, api_key, model_name, brief),
                        timeout=12.0,
                    )
                    note = (
                        f"Síntesis generada por {model_name} sobre métricas reales NASA POWER/FIRMS/DEM."
                        if lang == "es"
                        else f"Synthesis generated by {model_name} over real NASA POWER/FIRMS/DEM metrics."
                    )
                    return report.model_dump(), "gemini", model_name, note
                except Exception as exc:
                    msg = str(exc)
                    if "401" in msg or "403" in msg or "API key not valid" in msg:
                        self._gemini_auth_failed = True
                        log.warning("Gemini API key no válida; usando síntesis hidro-espacial local (%s)", model_name)
                        break
                    log.warning("Gemini tank analysis fallback (%s): %s", model_name, exc)

        det = _build_deterministic_analysis(payload, focus_question, lang)
        note = (
            "Análisis hidro-espacial calculado localmente (Copernicus DEM 30 m, NASA POWER 60 d y FIRMS VIIRS 60 d)."
            if lang == "es"
            else "Hydro-spatial analysis computed locally (Copernicus 30 m DEM, 60d NASA POWER, and 60d FIRMS VIIRS)."
        )
        return det, "hydro_deterministic", None, note


def _call_gemini_sync(api_key: str, model_name: str, prompt: str) -> TankNetworkLlmReport:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TankNetworkLlmReport,
            temperature=0.2,
        ),
    )
    if getattr(response, "parsed", None) is not None and isinstance(response.parsed, TankNetworkLlmReport):
        return response.parsed
    return TankNetworkLlmReport.model_validate_json(response.text or "{}")


def _build_llm_brief(payload: dict[str, Any], focus_question: str | None, lang: str) -> str:
    compact_tanks = [
        {
            "id": t["id"],
            "name": t["name_es"] if lang == "es" else t["name_en"],
            "role": t["role"],
            "elev_m": t["elevation_m"],
            "slope_deg": t["slope_deg"],
            "rain_30d_mm": t["rain_30d_mm"],
            "dry_days_60d": t["dry_days_60d"],
            "recommended_capacity_m3": t["recommended_capacity_m3"],
            "harvest_30d_m3": t["harvest_30d_m3"],
            "gravity_ready": t["gravity_ready"],
            "nearby_drought": [
                {
                    "id": d["id"],
                    "name": d["name_es"],
                    "km": d["distance_km"],
                    "d_elev_m": d["elevation_diff_m"],
                    "drought_score": d["drought_score"],
                }
                for d in t["nearby_drought_targets"]
            ],
            "nearby_fires": [
                {
                    "id": f["id"],
                    "zone": f["zone_label"],
                    "km": f["distance_km"],
                    "hotspots": f["hotspots_count"],
                    "max_frp_mw": f["max_frp_mw"],
                    "latest_date": f["latest_date"],
                }
                for f in t["nearby_fire_targets"]
            ],
        }
        for t in payload["tanks"]
    ]
    lang_label = "Spanish" if lang == "es" else "English"
    focus_line = f"\nUser specific focus: {focus_question}" if focus_question else ""
    return (
        f"Analyze this Cochabamba rainwater harvesting tank network in {lang_label}.\n"
        "STRICT RULES: Only cite numbers, tank IDs, zones, distances (km), rainfall (mm), "
        "elevations (m), and FIRMS counts/dates present in the JSON below. Do not invent any value.\n"
        "Explain how the network serves both nearby drought locations and nearby wildfire hotspots."
        f"{focus_line}\n\n"
        + json.dumps({"summary": payload["summary"], "tanks": compact_tanks}, ensure_ascii=False)
    )


def _build_deterministic_analysis(
    payload: dict[str, Any],
    focus_question: str | None,
    lang: str,
) -> dict[str, Any]:
    s = payload["summary"]
    tanks = payload["tanks"]
    drought_targets = payload["drought_targets"]
    fires = payload["fire_clusters"]

    dual_tanks = [t for t in tanks if t["role"] == "dual"]
    top_tank = tanks[0] if tanks else None
    top_drought = drought_targets[0] if drought_targets else None
    top_fire = fires[0] if fires else None

    if lang == "en":
        headline = (
            f"{s['tanks_count']} rainwater nodes · {s['total_storage_m3']:,} m³ reserve · "
            f"{s['drought_targets_covered']} drought zones & {s['fire_hotspots_covered']} FIRMS hotspots covered"
        )
        exec_sum = (
            f"The DEM + NASA POWER + FIRMS spatial optimization prioritizes {s['tanks_count']} capture tanks "
            f"({s['total_storage_m3']:,} m³ modular storage, {s['gravity_fed_tanks']} gravity-fed nodes). "
            f"Estimated 30-day micro-catchment harvest reaches {s['estimated_30d_harvest_m3']:,} m³, "
            f"covering {s['drought_targets_covered']} drought-stressed zones and {s['fire_hotspots_covered']} of "
            f"{s['fire_hotspots_total']} active 60-day FIRMS fire detections within 18 km."
        )
        if focus_question and top_tank:
            exec_sum += f" Focused on '{focus_question}', node {top_tank['id']} ({top_tank['name_en']}) leads with priority {top_tank['priority_score']}/100."
        drought_str = (
            f"Top drought demand is in {top_drought['name_en']} (score {top_drought['drought_score']}/100, "
            f"{top_drought['dry_days_60d']} dry days in 60 d, {top_drought['rain_30d_mm']} mm / 30 d). "
            f"Foothill tanks store wet-season storms to supply southern valleys by gravity where Δelev >= 15 m."
            if top_drought
            else "Southern agricultural districts receive priority reserve buffers from foothill capture."
        )
        fire_str = (
            f"Highest 60-day FIRMS concentration is {top_fire['id']} near {top_fire['zone_label']} "
            f"({top_fire['hotspots_count']} hotspots, max FRP {top_fire['max_frp_mw']} MW, last seen {top_fire['latest_date']}). "
            f"{len(dual_tanks)} dual-purpose nodes sit within dispatch range for pre-wetting and rapid suppression refills."
            if top_fire
            else "North and South foothill tanks maintain dedicated fire-hydrant manifolds for WUI brigades."
        )
        actions = [
            {
                "tank_id": t["id"],
                "title": f"{t['id']} · {t['name_en']} ({t['recommended_capacity_m3']} m³)",
                "impact": (
                    f"Serves {t['nearby_drought_targets'][0]['name_en']} ({t['nearby_drought_targets'][0]['distance_km']} km) "
                    f"& {t['nearby_fire_targets'][0]['zone_label']} ({t['nearby_fire_targets'][0]['distance_km']} km, "
                    f"{t['nearby_fire_targets'][0]['hotspots_count']} FIRMS pts)"
                )
                if t["nearby_drought_targets"] and t["nearby_fire_targets"]
                else f"30d capture {t['harvest_30d_m3']} m³ at {t['elevation_m']} m a.s.l.",
            }
            for t in tanks[:3]
        ]
        caveats = [
            "Tank volumes (500–2500 m³) represent engineered rainwater storage targets derived from D8 catchment area and observed 30d NASA rain, not natural lake bathymetry.",
            "Gravity delivery requires field topographic verification of pipe route head loss between foothill tanks and target hydrants.",
        ]
    else:
        headline = (
            f"{s['tanks_count']} tanques estratégicos · {s['total_storage_m3']:,} m³ de reserva · "
            f"{s['drought_targets_covered']} zonas secas y {s['fire_hotspots_covered']} focos FIRMS cubiertos"
        ).replace(",", ".")
        exec_sum = (
            f"El análisis combinado sobre DEM Copernicus 30 m, lluvia NASA POWER/IMERG (60 d) y focos FIRMS VIIRS "
            f"prioriza {s['tanks_count']} tanques de cosecha pluvial ({s['total_storage_m3']:,} m³ totales, "
            f"{s['gravity_fed_tanks']} con descarga por gravedad >= 15 m). La captación estimada en 30 días "
            f"alcanza {s['estimated_30d_harvest_m3']:,} m³, atendiendo {s['drought_targets_covered']} ubicaciones "
            f"con estrés por sequía y {s['fire_hotspots_covered']} de {s['fire_hotspots_total']} focos de incendio "
            f"detectados en los últimos 60 días."
        ).replace(",", ".")
        if focus_question and top_tank:
            exec_sum += f" Ante el foco «{focus_question}», destaca el nodo {top_tank['id']} ({top_tank['name_es']}, prioridad {top_tank['priority_score']}/100)."
        drought_str = (
            f"Mayor vulnerabilidad por sequía en {top_drought['name_es']} (índice {top_drought['drought_score']}/100, "
            f"{top_drought['dry_days_60d']} días secos en 60 d y {top_drought['rain_30d_mm']} mm en 30 d). "
            f"Los tanques en laderas y cabeceras acumulan tormentas recientes para abastecer valles del sur y reducir extracción subterránea."
            if top_drought
            else "Los nodos del sur y centro almacenan excedentes pluviales para mitigar estiaje periurbano y agrícola."
        )
        fire_str = (
            f"Mayor concentración de incendios recientes en {top_fire['id']} ({top_fire['zone_label']}: "
            f"{top_fire['hotspots_count']} focos FIRMS, FRP máx. {top_fire['max_frp_mw']} MW, último {top_fire['latest_date']}). "
            f"{len(dual_tanks)} tanques operan en modo dual con hidrantes para recarga rápida de cisternas y cortafuegos húmedos."
            if top_fire
            else "Los tanques de cabecera Tunari y pie de monte sur mantienen reserva dedicada para ataque inicial a incendios."
        )
        actions = [
            {
                "tank_id": t["id"],
                "title": f"{t['id']} · {t['name_es']} ({t['recommended_capacity_m3']} m³)",
                "impact": (
                    f"Cubre sequía en {t['nearby_drought_targets'][0]['name_es']} ({t['nearby_drought_targets'][0]['distance_km']} km) "
                    f"y focos cerca de {t['nearby_fire_targets'][0]['zone_label']} ({t['nearby_fire_targets'][0]['distance_km']} km · "
                    f"{t['nearby_fire_targets'][0]['hotspots_count']} focos)"
                )
                if t["nearby_drought_targets"] and t["nearby_fire_targets"]
                else f"Captación 30 d de {t['harvest_30d_m3']} m³ a {t['elevation_m']} m s.n.m.",
            }
            for t in tanks[:3]
        ]
        caveats = [
            "Las capacidades (500–2.500 m³) corresponden al dimensionamiento propuesto de obra civil modular según acumulación D8 y lluvia 30 d observada.",
            "La entrega por gravedad (Δcota >= 15 m) requiere verificación de trazado, pérdidas por fricción y servidumbres de paso en campo.",
        ]

    return {
        "headline": headline,
        "executive_summary": exec_sum,
        "drought_strategy": drought_str,
        "wildfire_strategy": fire_str,
        "priority_actions": actions,
        "data_caveats": caveats,
    }
