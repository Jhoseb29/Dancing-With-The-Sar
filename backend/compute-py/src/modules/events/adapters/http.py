"""Endpoints de eventos (contrato fire-stats.schema.json)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query

from config.settings import get_settings
from modules.events.adapters.firms_client import FirmsClient
from modules.events.application.fire_stats import FireStatsError, FireStatsService
from modules.events.domain.places import PlaceResolver

router = APIRouter(prefix="/api/events")

_STATUS = {"firms_not_configured": 503, "firms_rate_limited": 429, "firms_error": 502, "unknown_place": 400, "bad_range": 400}


@lru_cache
def fire_service() -> FireStatsService:
    settings = get_settings()
    return FireStatsService(
        FirmsClient(settings.firms_map_key, settings.firms_cache_dir / "days"),
        PlaceResolver(settings.ui_config_dir),
        settings.firms_cache_dir / "counts",
    )


def _raise(err: FireStatsError) -> None:
    raise HTTPException(status_code=_STATUS.get(err.code, 500), detail={"code": err.code, "message": err.message})


@router.get("/fires/stats")
async def fire_stats(place: str = Query(...), start: date = Query(...), end: date = Query(...)) -> dict:
    try:
        return await fire_service().stats(place, start, end)
    except FireStatsError as err:
        _raise(err)
        raise


@router.get("/fires")
async def fires_day(place: str = Query(...), date_: date = Query(..., alias="date")) -> dict:
    try:
        return await fire_service().day(place, date_)
    except FireStatsError as err:
        _raise(err)
        raise
