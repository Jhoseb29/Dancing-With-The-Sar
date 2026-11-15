"""Terrain from Copernicus DEM GLO-30 (public AWS bucket, no credentials): slope statistics.

Tiles are 1°x1° COGs named after their SW corner; only the AOI window of each is read.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge

TILE_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/"
            "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif")
GDAL_ENV = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif"}


@dataclass
class Terrain:
    mean_slope_deg: float
    steep_fraction_pct: float
    relief_m: float
    mean_elevation_m: float
    steep_threshold_deg: float
    tiles: list[str]


def _tiles(bbox: tuple[float, ...]) -> list[str]:
    w, s, e, n = bbox
    urls = []
    for lat in range(math.floor(s), math.floor(n - 1e-9) + 1):
        for lon in range(math.floor(w), math.floor(e - 1e-9) + 1):
            la = f"{'S' if lat < 0 else 'N'}{abs(lat):02d}"
            lo = f"{'W' if lon < 0 else 'E'}{abs(lon):03d}"
            urls.append(TILE_URL.format(lat=la, lon=lo))
    return urls


def terrain_stats(bbox: tuple[float, ...], steep_deg: float, cache: Path) -> Terrain:
    key = cache / f"dem_{'_'.join(f'{v:.3f}' for v in bbox)}_{steep_deg}.json"
    if key.exists():
        return Terrain(**json.loads(key.read_text()))
    urls = _tiles(bbox)
    with rasterio.Env(**GDAL_ENV):
        datasets = [rasterio.open("/vsicurl/" + u) for u in urls]
        try:
            mosaic, transform = merge(datasets, bounds=bbox)
        finally:
            for ds in datasets:
                ds.close()
    z = mosaic[0].astype(float)
    z[z < -100] = np.nan
    lat = (bbox[1] + bbox[3]) / 2
    dy = abs(transform.e) * 110_570
    dx = transform.a * 111_320 * math.cos(math.radians(lat))
    gy, gx = np.gradient(z, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    ok = np.isfinite(slope)
    result = Terrain(
        mean_slope_deg=round(float(np.nanmean(slope)), 2),
        steep_fraction_pct=round(100 * float(np.mean(slope[ok] > steep_deg)), 2),
        relief_m=round(float(np.nanmax(z) - np.nanmin(z)), 1),
        mean_elevation_m=round(float(np.nanmean(z)), 1),
        steep_threshold_deg=steep_deg,
        tiles=[u.rsplit("/", 1)[1] for u in urls],
    )
    cache.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps(result.__dict__))
    return result
