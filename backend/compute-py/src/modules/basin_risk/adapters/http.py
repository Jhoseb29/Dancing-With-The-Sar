"""Endpoints HTTP de riesgo de cuenca, terreno Copernicus DEM y precipitación NASA."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from config.settings import get_settings
from modules.basin_risk.adapters.copernicus_dem import CopernicusDemProvider
from modules.basin_risk.adapters.nasa_precip import NasaPrecipProvider
from modules.basin_risk.adapters.nisar_cmr import NisarCmrProvider
from modules.basin_risk.application.service import BasinRiskService
from modules.events.adapters.firms_client import FirmsClient

router = APIRouter(prefix="/api/basin")


@lru_cache
def basin_service() -> BasinRiskService:
    s = get_settings()
    firms = FirmsClient(s.firms_map_key, s.firms_cache_dir / "days") if s.firms_map_key else None
    return BasinRiskService(
        dem=CopernicusDemProvider(s.data_dir / "processed" / "cog" / "cochabamba_copernicus_dem_30m.tif"),
        precip=NasaPrecipProvider(
            s.data_dir / "raw" / "precip",
            earthdata_username=s.earthdata_username,
            earthdata_password=s.earthdata_password,
            earthdata_token=s.earthdata_token,
        ),
        nisar=NisarCmrProvider(s.data_dir / "manifests", s.ui_config_dir),
        firms_client=firms,
    )


@router.get("/overview")
async def overview(days: int = Query(60, ge=7, le=180)) -> dict:
    try:
        return await basin_service().overview(days=days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "basin_overview_error", "message": str(exc)}) from exc


@router.get("/point")
async def point(lon: float = Query(..., ge=-180, le=180), lat: float = Query(..., ge=-90, le=90)) -> dict:
    try:
        return await basin_service().point(lon=lon, lat=lat)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "basin_point_error", "message": str(exc)}) from exc


@router.get("/tiles/opera-dswx/{day}/{z}/{x}/{y}.png")
async def opera_dswx_tile(
    day: str,
    z: int,
    x: int,
    y: int,
    scope: Literal["basin", "all"] = "basin",
) -> Response:
    if not (0 <= z <= 12):
        raise HTTPException(status_code=400, detail="Zoom fuera de rango para OPERA DSWx-S1")
    png = await basin_service().sat_pipeline.get_opera_tile(day=day, z=z, x=x, y=y, scope=scope)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/tiles/nisar-basin/{day}/{z}/{x}/{y}.png")
async def nisar_basin_tile(
    day: str,
    z: int,
    x: int,
    y: int,
    scope: Literal["basin", "all"] = "basin",
) -> Response:
    if not (0 <= z <= 13):
        raise HTTPException(status_code=400, detail="Zoom fuera de rango para NISAR GCOV")
    png = await basin_service().sat_pipeline.get_nisar_tile(day=day, z=z, x=x, y=y, scope=scope)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/tiles/imerg-basin/{day}/{z}/{x}/{y}.png")
async def imerg_basin_tile(
    day: str,
    z: int,
    x: int,
    y: int,
    scope: Literal["basin", "all"] = "basin",
) -> Response:
    if not (0 <= z <= 12):
        raise HTTPException(status_code=400, detail="Zoom fuera de rango para GPM IMERG")
    png = await basin_service().sat_pipeline.get_imerg_tile(day=day, z=z, x=x, y=y, scope=scope)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=1800"},
    )


@router.get("/tiles/sar-change/{before_day}/{after_day}/{z}/{x}/{y}.png")
async def sar_change_tile(
    before_day: str,
    after_day: str,
    z: int,
    x: int,
    y: int,
    sensor: Literal["auto", "nisar", "opera"] = "auto",
) -> Response:
    if not (0 <= z <= 13):
        raise HTTPException(status_code=400, detail="Zoom fuera de rango para comparación SAR")
    png = await basin_service().render_sar_change_tile(
        before_day=before_day,
        after_day=after_day,
        z=z,
        x=x,
        y=y,
        sensor=sensor,
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/tiles/{layer}/{z}/{x}/{y}.png")
async def tile(
    layer: Literal["terrain", "slope", "susceptibility", "cota_drainage", "integrated_alert"],
    z: int,
    x: int,
    y: int,
) -> Response:
    if not (0 <= z <= 17):
        raise HTTPException(status_code=400, detail="Zoom fuera de rango")
    png = await basin_service().render_tile(layer=layer, z=z, x=x, y=y)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/bulletin")
async def bulletin() -> Response:
    md = await basin_service().bulletin_markdown()
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="boletin-preventivo-cochabamba.md"'},
    )
