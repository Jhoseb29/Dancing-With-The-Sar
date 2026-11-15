"""Estadísticas y focos de incendios (OpenSpec 09, fire-stats). Cifras reales de NASA FIRMS,
filtradas por el lugar real (polígono de Bolivia o bbox de Cochabamba)."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from modules.events.adapters.firms_client import MAX_DAYS, FirmsClient, FirmsError, FirmsRateLimited, to_float
from modules.events.domain.places import Place, PlaceResolver

MAX_RANGE_DAYS = 731
GRID_ANCHOR = date(2000, 1, 1)
# Un solo hilo para el trabajo de CPU (parseo y filtro): el event loop siempre conserva tiempo.
_CPU = ThreadPoolExecutor(max_workers=1, thread_name_prefix="firms-cpu")


class FireStatsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FireStatsService:
    def __init__(self, firms: FirmsClient, places: PlaceResolver, counts_cache: Path) -> None:
        self._firms = firms
        self._places = places
        self._counts_cache = counts_cache

    async def stats(self, place_id: str, start: date, end: date) -> dict[str, Any]:
        place = self._check(place_id, start, end)
        # Bloques de 5 días alineados a una grilla fija (cualquier rango reutiliza la caché),
        # partidos en el cambio SP → NRT para no perder días de ninguna fuente.
        try:
            sp_end = await self._firms.sp_end()
        except FirmsError as err:
            raise FireStatsError("firms_error", str(err)) from err
        windows = []
        cursor = start - timedelta(days=(start - GRID_ANCHOR).days % MAX_DAYS)
        today = date.today()
        while cursor <= end:
            block_end = min(cursor + timedelta(days=MAX_DAYS - 1), today)
            if sp_end and cursor <= sp_end < block_end:
                windows.append((cursor, (sp_end - cursor).days + 1))
                windows.append((sp_end + timedelta(days=1), (block_end - sp_end).days))
            else:
                windows.append((cursor, (block_end - cursor).days + 1))
            cursor += timedelta(days=MAX_DAYS)

        async def window_counts(window: tuple[date, int]) -> dict[str, int]:
            """Focos por día dentro del lugar para un bloque; se cachea solo el conteo (pocos bytes)."""
            first, days = window
            source = await self._firms.source_for(first)
            cache_file = self._counts_cache / place_id / f"{source}_{first.isoformat()}_{days}.json"
            if cache_file.exists():
                return json.loads(cache_file.read_text(encoding="utf-8"))
            rows = await self._firms.area(source, place.bbox, first, days, cache=False)
            # Filtro espacial fuera del event loop (decenas de miles de puntos).
            counts = await asyncio.get_running_loop().run_in_executor(_CPU, _count_by_day, rows, place)
            if self._firms.cacheable(first, days):
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(counts), encoding="utf-8")
            return dict(counts)

        try:
            chunks = await asyncio.gather(*(window_counts(w) for w in windows))
        except FirmsRateLimited as err:
            # Los bloques ya descargados quedan en caché: el próximo intento continúa desde ahí.
            raise FireStatsError("firms_rate_limited", str(err)) from err
        except FirmsError as err:
            raise FireStatsError("firms_error", str(err)) from err

        per_day: Counter[str] = Counter()
        for counts in chunks:
            for day, count in counts.items():
                if start.isoformat() <= day <= end.isoformat():
                    per_day[day] += count

        monthly: Counter[str] = Counter()
        for day, count in per_day.items():
            monthly[day[:7]] += count
        months = _month_range(start, end)
        peak = max(per_day.items(), key=lambda kv: kv[1]) if per_day else None
        return {
            "place": place_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total": sum(per_day.values()),
            "monthly": [{"month": m, "count": monthly.get(m, 0)} for m in months],
            "peak_day": {"date": peak[0], "count": peak[1]} if peak else None,
            "source": "NASA FIRMS · VIIRS 375 m (NOAA-20), procesamiento estándar o casi tiempo real según la fecha",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    async def day(self, place_id: str, day: date) -> dict[str, Any]:
        place = self._check(place_id, day, day)
        try:
            source = await self._firms.source_for(day)
            rows = await self._firms.area(source, place.bbox, day, 1)
        except FirmsRateLimited as err:
            raise FireStatsError("firms_rate_limited", str(err)) from err
        except FirmsError as err:
            raise FireStatsError("firms_error", str(err)) from err

        features = await asyncio.get_running_loop().run_in_executor(_CPU, _features, rows, place, day.isoformat())
        return {
            "place": place_id,
            "date": day.isoformat(),
            "count": len(features),
            "source": f"NASA FIRMS · {source}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "geojson": {"type": "FeatureCollection", "features": features},
        }

    def _check(self, place_id: str, start: date, end: date):
        if not self._firms.configured:
            raise FireStatsError("firms_not_configured", "FIRMS_MAP_KEY no está configurada en el backend.")
        place = self._places.get(place_id)
        if place is None:
            raise FireStatsError("unknown_place", f"Lugar desconocido: {place_id}")
        today = date.today()
        if start > end or end > today:
            raise FireStatsError("bad_range", "Rango inválido: el inicio debe ser anterior al fin y no puede haber fechas futuras.")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise FireStatsError("bad_range", "El rango máximo es de 2 años.")
        return place


def _valid_points(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[float], list[float]]:
    kept, lons, lats = [], [], []
    for row in rows:
        lon, lat = to_float(row, "longitude"), to_float(row, "latitude")
        if lon is not None and lat is not None and row.get("acq_date"):
            kept.append(row)
            lons.append(lon)
            lats.append(lat)
    return kept, lons, lats


def _count_by_day(rows: list[dict[str, str]], place: Place) -> dict[str, int]:
    kept, lons, lats = _valid_points(rows)
    if not kept:
        return {}
    mask = place.contains_many(lons, lats)
    return dict(Counter(row["acq_date"] for row, inside in zip(kept, mask) if inside))


def _features(rows: list[dict[str, str]], place: Place, day: str) -> list[dict[str, Any]]:
    kept, lons, lats = _valid_points([r for r in rows if r.get("acq_date") == day])
    if not kept:
        return []
    mask = place.contains_many(lons, lats)
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
            "properties": {"frp": to_float(row, "frp"), "confidence": row.get("confidence"), "acq_time": row.get("acq_time")},
        }
        for row, lon, lat, inside in zip(kept, lons, lats, mask)
        if inside
    ]


def _month_range(start: date, end: date) -> list[str]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months
