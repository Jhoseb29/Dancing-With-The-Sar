"""Servicio de aplicación Qucha-SAR: cruza hidrología Copernicus DEM, NASA lluvia, NISAR/OPERA y FIRMS."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import time
from typing import Any

from shapely.geometry import Point, shape
from shapely.prepared import prep

from modules.basin_risk.adapters.copernicus_dem import CopernicusDemProvider
from modules.basin_risk.adapters.dem_hydrology import HydroGridArtifact, SubBasinFeature
from modules.basin_risk.adapters.nasa_precip import NasaPrecipProvider
from modules.basin_risk.adapters.nisar_cmr import NisarCmrProvider
from modules.basin_risk.adapters.satellite_pipeline import BasinSatellitePipeline, get_satellite_pipeline
from modules.basin_risk.domain.zones import (
    BASIN_BBOX,
    COTA_URBANA_M,
    build_subsystems_summary,
    evaluate_zone_risk,
)

_DEM_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dem-cpu")
_LEVEL_RANK = {"verde": 0, "amarillo": 1, "naranja": 2, "rojo": 3}


class BasinRiskService:
    def __init__(
        self,
        dem: CopernicusDemProvider,
        precip: NasaPrecipProvider,
        nisar: NisarCmrProvider,
        firms_client: Any = None,
        sat_pipeline: BasinSatellitePipeline | None = None,
    ) -> None:
        self._dem = dem
        self._precip = precip
        self._nisar = nisar
        self._firms = firms_client
        self.sat_pipeline = sat_pipeline or get_satellite_pipeline()
        self._last_rain_factor: float = 0.35
        self._latest_opera_day: str | None = None
        self._overview_cache: dict[int, tuple[float, dict[str, Any]]] = {}
        self._overview_lock = asyncio.Lock()

    async def overview(self, days: int = 60) -> dict[str, Any]:
        cached = self._overview_cache.get(days)
        if cached and (time.monotonic() - cached[0]) < 120.0:
            return cached[1]
        async with self._overview_lock:
            cached = self._overview_cache.get(days)
            if cached and (time.monotonic() - cached[0]) < 120.0:
                return cached[1]
            payload = await self._compute_overview(days=days)
            self._overview_cache[days] = (time.monotonic(), payload)
            return payload

    async def _compute_overview(self, days: int = 60) -> dict[str, Any]:
        loop = asyncio.get_running_loop()

        hydro: HydroGridArtifact = await loop.run_in_executor(_DEM_POOL, self._dem.ensure_hydrology)
        subbasins = hydro.subbasins

        dem_task = loop.run_in_executor(_DEM_POOL, self._dem.all_polygon_stats)
        precip_tasks = [
            self._precip.daily_series(sb.id, sb.centroid[0], sb.centroid[1], days=days)
            for sb in subbasins
        ]
        gpm_task = self._precip.gpm_catalog_status()
        nisar_task = self._nisar.catalog()
        fires_task = self._recent_fires_by_subbasin(subbasins)

        dem_by_zone, *rest = await asyncio.gather(
            dem_task, *precip_tasks, gpm_task, nisar_task, fires_task
        )
        precip_results = rest[: len(subbasins)]
        gpm_status, nisar_catalog, fires_by_zone = rest[len(subbasins) :]

        # Mantener estado EULA actualizado si el primer sondeado ocurrió en daily_series
        gpm_status = {**gpm_status, **self._precip.eula_state()}

        opera_dates = nisar_catalog.get("opera_dswx_dates") or []
        nisar_dates = nisar_catalog.get("verified_gibs_dates") or []
        if opera_dates:
            self._latest_opera_day = str(opera_dates[0])
        baseline_opera_day = str(opera_dates[-1]) if len(opera_dates) >= 2 else None
        latest_nisar_day = str(nisar_dates[0]) if nisar_dates else None

        sat_summary = await self.sat_pipeline.summarize_basin_satellites(
            opera_day=self._latest_opera_day,
            nisar_day=latest_nisar_day,
            hydro=hydro,
            baseline_opera_day=baseline_opera_day,
        )
        by_zone_surface = (sat_summary.get("opera_dswx") or {}).get("by_zone_surface") or {}

        zones_out: list[dict[str, Any]] = []
        for sb, precip in zip(subbasins, precip_results):
            summary_with_meta = {
                **precip["summary"],
                "source": precip.get("source", "NASA POWER PRECTOTCORR"),
                "imerg_spatial_active": bool(precip.get("imerg_spatial_active", False)),
            }
            zones_out.append(
                evaluate_zone_risk(
                    zone=sb,
                    dem_stats=dem_by_zone.get(sb.id, {}),
                    precip_summary=summary_with_meta,
                    fire_count_30d=fires_by_zone.get(sb.id),
                    sat_zone_metrics=by_zone_surface.get(sb.id),
                )
            )

        subsystems_out = build_subsystems_summary(zones_out)
        combined_series = _merge_basin_precip([p["series"] for p in precip_results])
        mean_7d = sum(z["precipitation"]["sum_7d_mm"] for z in zones_out) / max(len(zones_out), 1)
        self._last_rain_factor = min(1.0, max(0.15, mean_7d / 60.0))

        top_zone = max(zones_out, key=lambda z: z["score"])
        overall_level = max((z["level"] for z in zones_out), key=lambda lv: _LEVEL_RANK[lv])

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "basin": "Cuenca de Cochabamba",
            "overall": {
                "level": overall_level,
                "max_score": top_zone["score"],
                "priority_zone_id": top_zone["id"],
                "priority_zone_name": top_zone["name"],
                "cota_urbana_m": COTA_URBANA_M,
            },
            "subsystems": subsystems_out,
            "zones": zones_out,
            "precipitation": {
                "source": precip_results[0]["source"] if precip_results else "NASA POWER",
                "gpm_cmr": gpm_status,
                "series": combined_series,
            },
            "nisar": nisar_catalog,
            "satellite_processing": sat_summary,
            "sources": {
                "dem": "Copernicus DEM GLO-30 (AWS Open Data · 30 m · D8 + TWI)",
                "precipitation": "NASA GPM_3IMERGDL (0.1°) / respaldo NASA POWER PRECTOTCORR",
                "sar": "NASA CMR NISAR L2 GCOV + NASA GIBS (recorte Cuenca + máscara >= 25°)",
                "surface_water": "NASA/JPL OPERA DSWx-S1 (Sentinel-1 30 m · área superficial en km²)",
            },
        }

    async def point(self, lon: float, lat: float) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        diag = await loop.run_in_executor(_DEM_POOL, self._dem.point_diagnostics, lon, lat)
        if diag is None:
            return {"inside_basin": False, "lon": lon, "lat": lat}

        hydro = await loop.run_in_executor(_DEM_POOL, self._dem.ensure_hydrology)
        sb_id = (diag.get("hydro") or {}).get("subbasin_id")
        sb = next((s for s in hydro.subbasins if s.id == sb_id), None)

        precip_summary = None
        if sb is not None:
            try:
                p = await self._precip.daily_series(sb.id, sb.centroid[0], sb.centroid[1], days=30)
                precip_summary = p["summary"]
            except Exception:
                precip_summary = None

        return {
            "inside_basin": True,
            "lon": round(lon, 6),
            "lat": round(lat, 6),
            "zone": (
                {"id": sb.id, "subsystem": sb.subsystem, "name": {"es": sb.name_es, "en": sb.name_en}}
                if sb
                else None
            ),
            "dem": diag,
            "precipitation": precip_summary,
            "source": "Copernicus DEM GLO-30 (30 m)",
        }

    async def render_tile(self, layer: str, z: int, x: int, y: int) -> bytes:
        loop = asyncio.get_running_loop()
        if layer == "integrated_alert":
            if self._latest_opera_day is None:
                try:
                    cat = await self._nisar.catalog()
                    dates = cat.get("opera_dswx_dates") or []
                    if dates:
                        self._latest_opera_day = str(dates[0])
                except Exception:
                    self._latest_opera_day = "2026-11-13"
            grid = await loop.run_in_executor(_DEM_POOL, self._dem.ensure_loaded)
            return await self.sat_pipeline.render_integrated_alert_tile(
                grid,
                self._last_rain_factor,
                z,
                x,
                y,
                self._latest_opera_day,
            )
        return await loop.run_in_executor(
            _DEM_POOL, self._dem.render_tile, layer, z, x, y, self._last_rain_factor
        )

    async def render_sar_change_tile(
        self,
        before_day: str,
        after_day: str,
        z: int,
        x: int,
        y: int,
        sensor: str = "auto",
    ) -> bytes:
        loop = asyncio.get_running_loop()
        grid = await loop.run_in_executor(_DEM_POOL, self._dem.ensure_loaded)
        return await self.sat_pipeline.get_sar_change_tile(
            before_day=before_day,
            after_day=after_day,
            z=z,
            x=x,
            y=y,
            dem_grid=grid,
            sensor=sensor,  # type: ignore[arg-type]
        )

    async def bulletin_markdown(self) -> str:
        data = await self.overview(days=30)
        ov = data["overall"]
        nisar = data["nisar"]
        latest_g = nisar.get("latest_granule") or {}
        lines = [
            "# Boletín Preventivo Qucha-SAR · Cuenca de Cochabamba",
            f"- **Emitido:** {data['generated_at']}",
            f"- **Nivel global de alerta:** `{ov['level'].upper()}` (índice máx. {ov['max_score']}/100 en **{ov['priority_zone_name']['es']}**)",
            f"- **Último gránulo NISAR en CMR:** `{latest_g.get('title', 'N/D')}` (`{latest_g.get('maturity', 'N/D')}`, fecha `{latest_g.get('date', 'N/D')}`)",
            f"- **Fuente pluviométrica activa:** `{data['precipitation']['source']}`",
            "",
            "## Resumen por Subsistema (Norte – Centro – Sur)",
        ]
        for sub in data.get("subsystems", []):
            lines.append(f"- **{sub['name']['es']}** (`{sub['level'].upper()}`): {sub['summary_metric']['es']} — _{sub['focus']['es']}_")

        lines.extend([
            "",
            "## Estado por Subcuenca Hidrológica (Copernicus DEM 30 m)",
            "| Subcuenca | Subsistema | Área | Índice | Nivel | Lluvia 7d | Pendiente p90 | Agua OPERA | Driver dominante |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ])
        for z in data["zones"]:
            sw = z.get("surface_water") or {}
            lines.append(
                f"| {z['name']['es']} | {z['subsystem'].upper()} | {z['area_km2']} km² | {z['score']}/100 | **{z['level'].upper()}** | "
                f"{z['precipitation']['sum_7d_mm']} mm | {z['terrain'].get('slope_p90_deg', '—')}° | "
                f"{sw.get('opera_water_km2', 0.0)} km² | {z['dominant_driver']['es']} |"
            )
        lines.extend([
            "",
            "## Notas Metodológicas y Límites Físicos",
            "- **Pre-acondicionamiento vs. disparador:** NISAR (banda L, ciclo 12 días) mide humedad superficial y cambios de estructura; la lluvia diaria actúa como disparador dinámico.",
            "- **Escorzo/sombra SAR (>= 25°):** Las laderas del Tunari >= 25° están enmascaradas con advertencia geométrica para evitar falsas alarmas.",
            "- **Honestidad en Zona Sur:** El balance del Sur reporta área superficial de agua (km²) y déficit pluviométrico (mm); no se estiman volúmenes en m³ sin batimetría validada.",
            "- **Fuentes:** Copernicus DEM GLO-30 (sin dependencia WMS GAMC), NASA POWER / GPM IMERG, NASA CMR NISAR, OPERA DSWx-S1 y NASA FIRMS.",
        ])
        return "\n".join(lines)

    async def _recent_fires_by_subbasin(self, subbasins: tuple[SubBasinFeature, ...]) -> dict[str, int | None]:
        if not self._firms or not getattr(self._firms, "configured", False):
            return {sb.id: None for sb in subbasins}
        try:
            end = date.today()
            start = end - timedelta(days=4)
            source = await self._firms.source_for(start)
            rows = await self._firms.area(source, BASIN_BBOX, start, 5)
            counts: dict[str, int] = {sb.id: 0 for sb in subbasins}
            polys = [(sb.id, prep(shape(sb.geometry))) for sb in subbasins]
            for row in rows:
                try:
                    lon = float(row.get("longitude", ""))
                    lat = float(row.get("latitude", ""))
                except ValueError:
                    continue
                pt = Point(lon, lat)
                for sid, poly in polys:
                    if poly.contains(pt):
                        counts[sid] += 1
                        break
            return dict(counts)
        except Exception:
            return {sb.id: None for sb in subbasins}


def _merge_basin_precip(series_list: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_date: dict[str, list[float]] = {}
    for series in series_list:
        for item in series:
            by_date.setdefault(item["date"], []).append(float(item["mm"]))
    return [
        {"date": d, "mm": round(sum(vals) / len(vals), 2)}
        for d, vals in sorted(by_date.items())
    ]
