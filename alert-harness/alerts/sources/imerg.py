"""Daily IMERG rainfall over a bbox, fetched as a tiny OPeNDAP subset (~26 KB/day, not 27 MB).

Product choice per day (latency vs quality):
  Final (GPM_3IMERGDF, gauge-calibrated, ~3.5 months late)  -> historical days
  Late  (GPM_3IMERGDL, ~14 h)                               -> recent days
  Early (GPM_3IMERGDE, ~4 h)                                -> today/yesterday
Grid: 0.1° (~10 km). Each day is cached on disk so evaluation loops never re-download.
"""
from __future__ import annotations

import io
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import h5py
import numpy as np
import requests

log = logging.getLogger("alerts.imerg")

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
PRODUCTS = ("GPM_3IMERGDF", "GPM_3IMERGDL", "GPM_3IMERGDE")  # preference order
FILL = -9999.0


@dataclass
class DayRain:
    day: str
    product: str
    max_mm: float | None  # wettest cell of the area
    mean_mm: float | None  # areal mean
    cells: int


def _indices(bbox: tuple[float, ...]) -> tuple[int, int, int, int]:
    w, s, e, n = bbox
    i0, i1 = math.floor((w + 180) / 0.1), math.floor((e + 180) / 0.1)
    j0, j1 = math.floor((s + 90) / 0.1), math.floor((n + 90) / 0.1)
    return max(i0, 0), min(i1, 3599), max(j0, 0), min(j1, 1799)


def _opendap_url(product: str, day: str) -> str | None:
    params = {"short_name": product, "version": "07", "page_size": 1,
              "temporal": f"{day}T00:00:00Z,{day}T23:59:59Z"}
    entries = requests.get(CMR, params=params, timeout=30).json()["feed"]["entry"]
    if not entries:
        return None
    return next((l["href"] for l in entries[0]["links"] if "opendap" in l["href"].lower()), None)


def _fetch_day(day: str, bbox: tuple[float, ...], token: str, cache: Path) -> DayRain:
    key = cache / f"imerg_{day}_{'_'.join(f'{v:.3f}' for v in bbox)}.json"
    if key.exists():
        return DayRain(**json.loads(key.read_text()))
    i0, i1, j0, j1 = _indices(bbox)
    for product in PRODUCTS:
        url = _opendap_url(product, day)
        if not url:
            continue
        ce = f"/precipitation[0][{i0}:{i1}][{j0}:{j1}]"
        resp = requests.get(f"{url}.dap.nc4", params={"dap4.ce": ce},
                            headers={"Authorization": f"Bearer {token}"}, timeout=90)
        resp.raise_for_status()
        with h5py.File(io.BytesIO(resp.content)) as f:
            p = f["precipitation"][:].astype(float).ravel()
        p = p[p > FILL / 2]
        result = DayRain(day, product, round(float(p.max()), 2) if p.size else None,
                         round(float(p.mean()), 2) if p.size else None, int(p.size))
        cache.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps(result.__dict__))
        return result
    return DayRain(day, "sin_dato", None, None, 0)


def daily_series(bbox: tuple[float, ...], start: date, end: date, token: str, cache: Path) -> list[DayRain]:
    days = [(start + timedelta(d)).isoformat() for d in range((end - start).days + 1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        out = list(pool.map(lambda d: _fetch_day(d, bbox, token, cache), days))
    missing = sum(r.max_mm is None for r in out)
    if missing:
        log.warning("IMERG: %d/%d días sin dato", missing, len(out))
    return out
