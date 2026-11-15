"""Half-hourly IMERG (mm/h) over a bbox: the 30–60 min storms that trigger Cochabamba's floods.

Daily totals hide them (80 mm spread over a day vs 25 mm in 40 min), so this module returns the
full 30-min grid per slot. Same OPeNDAP subset trick as the daily module (~18 KB per slot).

Products (preference order): Final HH (gauge-calibrated, ~3.5 months late), Late HH (~14 h),
Early HH (~4 h). One CMR query per product and day lists all 48 slots.
"""
from __future__ import annotations

import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h5py
import numpy as np
import requests

from .imerg import CMR, FILL, _get_with_retry, _indices

log = logging.getLogger("alerts.imerg_hh")

PRODUCTS = ("GPM_3IMERGHH", "GPM_3IMERGHHL", "GPM_3IMERGHHE")
STABLE_AFTER = timedelta(days=3)


@dataclass
class Slot:
    start: str  # UTC ISO, slot start
    product: str
    rate_mm_h: list[list[float | None]]  # [lon][lat]


@dataclass
class Grid:
    lons: list[float]  # cell centres
    lats: list[float]
    slots: list[Slot]


def _day_urls(product: str, day: str) -> dict[str, str]:
    params = {"short_name": product, "version": "07", "page_size": 60, "sort_key": "start_date",
              "temporal": f"{day}T00:00:00Z,{day}T23:59:59Z"}
    entries = requests.get(CMR, params=params, timeout=30).json()["feed"]["entry"]
    out = {}
    for e in entries:
        url = next((l["href"] for l in e["links"] if "opendap" in l["href"].lower()), None)
        if url:
            out[e["time_start"][:16]] = url  # 'YYYY-MM-DDTHH:MM'
    return out


def _catalog(start: datetime, end: datetime) -> dict[str, tuple[str, str]]:
    """slot start 'YYYY-MM-DDTHH:MM' -> (product, opendap url), best product available."""
    days = sorted({(start + timedelta(hours=h)).date().isoformat()
                   for h in range(0, int((end - start).total_seconds() // 3600) + 1)} | {end.date().isoformat()})
    best: dict[str, tuple[str, str]] = {}
    for product in reversed(PRODUCTS):  # worst first, better products overwrite
        for day in days:
            for slot, url in _day_urls(product, day).items():
                best[slot] = (product, url)
    return best


def _fetch(slot: str, product: str, url: str, bbox: tuple[float, ...], token: str, cache: Path) -> Slot:
    key = cache / f"imerghh_{slot.replace(':', '')}_{'_'.join(f'{v:.3f}' for v in bbox)}.json"
    if key.exists():
        cached = json.loads(key.read_text())
        if cached["product"] == product or cached["product"] == "GPM_3IMERGHH":
            return Slot(**cached)
    i0, i1, j0, j1 = _indices(bbox)
    resp = _get_with_retry(f"{url}.dap.nc4", {"dap4.ce": f"/Grid/precipitation[0][{i0}:{i1}][{j0}:{j1}]"}, token)
    with h5py.File(io.BytesIO(resp.content)) as f:
        p = f["Grid/precipitation"][0].astype(float)
    grid = [[None if v < FILL / 2 else round(float(v), 2) for v in row] for row in p]
    out = Slot(slot, product, grid)
    stable = product == "GPM_3IMERGHH" or (
        datetime.now(timezone.utc) - datetime.fromisoformat(slot + ":00+00:00") > STABLE_AFTER)
    if stable:
        cache.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps(asdict(out)))
    return out


def halfhourly(bbox: tuple[float, ...], start: datetime, end: datetime, token: str, cache: Path) -> Grid:
    """All available 30-min slots with start in [start, end) (UTC)."""
    catalog = _catalog(start, end)
    wanted = sorted(s for s in catalog
                    if start <= datetime.fromisoformat(s + ":00+00:00") < end)
    with ThreadPoolExecutor(max_workers=8) as pool:
        slots = list(pool.map(lambda s: _fetch(s, *catalog[s], bbox, token, cache), wanted))
    i0, i1, j0, j1 = _indices(bbox)
    lons = [round(-180 + 0.1 * i + 0.05, 2) for i in range(i0, i1 + 1)]
    lats = [round(-90 + 0.1 * j + 0.05, 2) for j in range(j0, j1 + 1)]
    expected = int((end - start).total_seconds() // 1800)
    if len(slots) < expected:
        log.info("IMERG HH: %d/%d medias horas disponibles (latencia del producto)", len(slots), expected)
    return Grid(lons, lats, slots)


def peaks(grid: Grid) -> dict[str, float | str | None]:
    """Peak 30-min rate and peak 1-h accumulation (any cell), with when it happened."""
    if not grid.slots:
        return {"max_30min_mm_h": None, "max_1h_mm": None, "cuando": None, "medias_horas": 0}
    cube = np.array([[[np.nan if v is None else v for v in row] for row in s.rate_mm_h] for s in grid.slots])
    per_slot = np.nanmax(cube.reshape(len(grid.slots), -1), axis=1)
    hour = cube[1:] * 0.5 + cube[:-1] * 0.5 if len(cube) > 1 else cube * 0.5  # mm in 60 min
    hour_max = np.nanmax(hour.reshape(len(hour), -1), axis=1)
    k = int(np.nanargmax(per_slot))
    return {"max_30min_mm_h": round(float(per_slot[k]), 2),
            "max_1h_mm": round(float(np.nanmax(hour_max)), 2),
            "cuando": grid.slots[k].start, "medias_horas": len(grid.slots)}
