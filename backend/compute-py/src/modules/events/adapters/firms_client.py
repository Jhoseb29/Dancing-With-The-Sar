"""Adaptador NASA FIRMS (API `area`, CSV). Máx. 5 días por petición; caché en disco por bloque.

Formato verificado (firms.modaps.eosdis.nasa.gov/api/area, 2026-11-14):
  /api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE}/{YYYY-MM-DD}
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("events.firms")

BASE_URL = "https://firms.modaps.eosdis.nasa.gov"
MAX_DAYS = 5
SENSOR = "VIIRS_NOAA20"  # VIIRS 375 m a bordo de NOAA-20
# Un hilo para parseo/caché: el event loop no compite con muchos hilos por el GIL.
_IO = ThreadPoolExecutor(max_workers=1, thread_name_prefix="firms-io")
KEEP_FIELDS = ("latitude", "longitude", "acq_date", "acq_time", "frp", "confidence")


class FirmsError(RuntimeError):
    pass


class FirmsRateLimited(FirmsError):
    """FIRMS: se superaron las 5000 transacciones por 10 minutos de la MAP_KEY."""


class FirmsClient:
    def __init__(self, map_key: str, cache_dir: Path, concurrency: int = 6) -> None:
        self._key = map_key
        self._cache_dir = cache_dir
        self._semaphore = asyncio.Semaphore(concurrency)
        self._availability: dict[str, tuple[date, date]] | None = None
        self._availability_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        # Un solo cliente reutilizado: crear uno por petición (contexto TLS) cuesta CPU en el event loop.
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=90, limits=httpx.Limits(max_connections=8))
        return self._client

    async def sp_end(self) -> date | None:
        """Último día con procesamiento estándar (SP); después solo hay NRT."""
        sp = (await self._get_availability()).get(f"{SENSOR}_SP")
        return sp[1] if sp else None

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def source_for(self, day: date) -> str:
        """Procesamiento estándar (SP) cuando existe para ese día; si no, casi tiempo real (NRT)."""
        availability = await self._get_availability()
        sp = availability.get(f"{SENSOR}_SP")
        if sp and sp[0] <= day <= sp[1]:
            return f"{SENSOR}_SP"
        return f"{SENSOR}_NRT"

    async def area(
        self,
        source: str,
        bbox: tuple[float, float, float, float],
        start: date,
        days: int,
        cache: bool = True,
    ) -> list[dict[str, str]]:
        """Focos del área. Solo se conservan los campos que usa el proyecto (sin datos innecesarios)."""
        if days < 1 or days > MAX_DAYS:
            raise ValueError("days debe estar entre 1 y 5")
        area = ",".join(f"{v:.6f}" for v in bbox)
        cache_file = self._cache_path(source, area, start, days) if cache else None
        if cache_file is not None and cache_file.exists():
            return await asyncio.get_running_loop().run_in_executor(_IO, lambda: json.loads(cache_file.read_text(encoding="utf-8")))

        url = f"{BASE_URL}/api/area/csv/{self._key}/{source}/{area}/{days}/{start.isoformat()}"
        async with self._semaphore:
            response = await self._http().get(url)
        if response.status_code != 200:
            if "transaction limit" in response.text.lower():
                raise FirmsRateLimited("FIRMS: límite de transacciones de la MAP_KEY alcanzado; reintentar en unos minutos")
            raise FirmsError(f"FIRMS respondió {response.status_code}")
        # Decodificar y parsear fuera del event loop (respuestas de varios MB).
        rows = await asyncio.get_running_loop().run_in_executor(_IO, _parse_csv, response.content)

        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.get_running_loop().run_in_executor(_IO, cache_file.write_text, json.dumps(rows), "utf-8")
        return rows

    def cacheable(self, start: date, days: int) -> bool:
        """No cachear bloques que incluyen los últimos días (NRT todavía cambia)."""
        return (date.today() - start).days >= days + 2

    def _cache_path(self, source: str, area: str, start: date, days: int) -> Path | None:
        if not self.cacheable(start, days):
            return None
        digest = hashlib.sha1(f"{source}|{area}|{start}|{days}".encode()).hexdigest()[:20]
        return self._cache_dir / source / f"{start.isoformat()}_{days}_{digest}.json"

    async def _get_availability(self) -> dict[str, tuple[date, date]]:
        if self._availability is not None:
            return self._availability
        async with self._availability_lock:
            if self._availability is not None:
                return self._availability
            return await self._load_availability()

    async def _load_availability(self) -> dict[str, tuple[date, date]]:
        url = f"{BASE_URL}/api/data_availability/csv/{self._key}/ALL"
        response = await self._http().get(url)
        if response.status_code != 200:
            raise FirmsError(f"FIRMS data_availability respondió {response.status_code}")
        availability: dict[str, tuple[date, date]] = {}
        for row in csv.DictReader(io.StringIO(response.text)):
            try:
                availability[row["data_id"]] = (date.fromisoformat(row["min_date"]), date.fromisoformat(row["max_date"]))
            except (KeyError, ValueError):
                continue
        log.info("FIRMS disponibilidad: %s", {k: (str(v[0]), str(v[1])) for k, v in availability.items() if k.startswith(SENSOR)})
        self._availability = availability
        return availability


def _parse_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8", errors="replace")
    if text.lstrip().lower().startswith(("invalid", "error")):
        raise FirmsError(f"FIRMS: {text.strip()[:120]}")
    return [{k: row.get(k, "") for k in KEEP_FIELDS} for row in csv.DictReader(io.StringIO(text))]


def to_float(row: dict[str, Any], key: str) -> float | None:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
