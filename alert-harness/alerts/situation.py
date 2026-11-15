"""City-wide context the monitor publishes next to the district levels (output/monitor/):

  rain.json   last 24 h of IMERG every 30 min over the city and its catchments (mm/h per 0.1° cell),
              24 h accumulation, the strongest burst and the rain over each torrent basin
              -> the web animates it as rain columns and shows it per basin.
  radar.json  last / next estimated radar pass (NISAR, Sentinel-1) -> "we can verify on <date>".

Both are plain data; wording lives in the web.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import basins as basins_mod
from . import districts as districts_mod
from .radar_schedule import schedule
from .settings import Settings
from .sources.imerg_hh import Grid, halfhourly, peaks

log = logging.getLogger("alerts.situation")

RAIN_MARGIN_DEG = 0.25  # catchments above the city (Tunari) feed its torrents
HOURS = 24


def city_bbox(margin: float = 0.0) -> tuple[float, float, float, float]:
    b = np.array([f["properties"]["bbox"] for f in districts_mod.load()])
    return (round(b[:, 0].min() - margin, 3), round(b[:, 1].min() - margin, 3),
            round(b[:, 2].max() + margin, 3), round(b[:, 3].max() + margin, 3))


def _cell_mask(grid: Grid, bbox: list[float]) -> np.ndarray:
    lon = np.array(grid.lons)[:, None]
    lat = np.array(grid.lats)[None, :]
    # cells whose 0.1° square touches the bbox
    return (lon + 0.05 >= bbox[0]) & (lon - 0.05 <= bbox[2]) & (lat + 0.05 >= bbox[1]) & (lat - 0.05 <= bbox[3])


def _bursts(grid: Grid, areas: list[tuple[str, list[float]]], with_series: bool) -> dict[str, dict[str, Any]]:
    """Per area: strongest 30-min rate (any touching cell), when, areal 24 h total (and the series)."""
    if not grid.slots:
        return {}
    cube = np.array([[[np.nan if v is None else v for v in row] for row in s.rate_mm_h] for s in grid.slots])
    out = {}
    for area_id, bbox in areas:
        cells = np.where(_cell_mask(grid, bbox)[None], cube, np.nan).reshape(len(cube), -1)
        if np.all(np.isnan(cells)):
            continue
        series = np.nanmax(cells, axis=1)  # strongest cell per slot
        mean = np.nanmean(cells, axis=1)  # areal mean per slot
        k = int(np.nanargmax(series))
        out[area_id] = {"max_mm_h": round(float(series[k]), 1), "cuando": grid.slots[k].start,
                        "acumulado_24h_mm": round(float(np.nansum(mean) * 0.5), 1)}
        if with_series:
            out[area_id]["serie_mm_h"] = [round(float(v), 1) for v in series]
    return out


def district_bursts(grid: Grid) -> dict[str, dict[str, Any]]:
    return _bursts(grid, [(f["properties"]["id"], f["properties"]["bbox"]) for f in districts_mod.load()], False)


def basin_bursts(grid: Grid) -> dict[str, dict[str, Any]]:
    try:
        feats = basins_mod.load()
    except Exception:  # noqa: BLE001 - basins are optional context
        return {}
    return _bursts(grid, [(f["properties"]["id"], f["properties"]["bbox"]) for f in feats], True)


def rain_last_hours(st: Settings, now: datetime) -> tuple[dict[str, Any], Grid]:
    end = now.replace(minute=30 if now.minute >= 30 else 0, second=0, microsecond=0)
    grid = halfhourly(city_bbox(RAIN_MARGIN_DEG), end - timedelta(hours=HOURS), end,
                      st.earthdata_token, st.output_dir / "cache")
    cube = np.array([[[np.nan if v is None else v for v in row] for row in s.rate_mm_h] for s in grid.slots]) \
        if grid.slots else np.zeros((0, len(grid.lons), len(grid.lats)))
    total = np.nansum(cube, axis=0) * 0.5 if len(cube) else np.zeros((len(grid.lons), len(grid.lats)))
    return {
        "actualizado": now.isoformat(),
        "fuente": "NASA GPM IMERG (media hora, 0,1°)",
        "productos": sorted({s.product for s in grid.slots}),
        "lons": grid.lons, "lats": grid.lats, "celda_grados": 0.1,
        "slots": [{"inicio": s.start, "producto": s.product, "mm_h": s.rate_mm_h} for s in grid.slots],
        "acumulado_mm": [[round(float(v), 1) for v in row] for row in total],
        "pico": peaks(grid),
        "esperadas": HOURS * 2,
        "cuencas": basin_bursts(grid),  # what the satellite saw over each torrent basin
    }, grid


def publish(st: Settings, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """Write rain.json and radar.json; return the per-district bursts for the monitor."""
    now = now or datetime.now(timezone.utc)
    mon = st.output_dir / "monitor"
    mon.mkdir(parents=True, exist_ok=True)
    bursts: dict[str, dict[str, Any]] = {}
    try:
        rain, grid = rain_last_hours(st, now)
        _write(mon / "rain.json", rain)
        bursts = district_bursts(grid)
    except Exception as exc:  # noqa: BLE001 - context must never stop the alerts
        log.warning("Lluvia por media hora no disponible: %s", exc)
    try:
        _write(mon / "radar.json", {"actualizado": now.isoformat(), **schedule(city_bbox(), now.date())})
    except Exception as exc:  # noqa: BLE001
        log.warning("Calendario radar no disponible: %s", exc)
    return bursts


def _write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
