"""Compact, render-ready grids for the web globe (no images: the browser colours the data).

Every date of a run is resampled onto the SAME regular lon/lat grid over the AOI, so
takes can be swapped, overlaid and compared cell by cell (hotspots) without reprojection.

File format (``*_globe.json``)::

    {
      "version": 1, "date": "YYYY-MM-DD", "bbox": [w, s, e, n], "width": W, "height": H,
      "classes": "<base64 uint8, row-major north->south; 0 water,1 soil,2 vegetation,3 urban,255 nodata>",
      "co_db":    "<base64 uint8 quantised dB>",  "co_pol": "HHHH",
      "cross_db": "<base64 uint8 quantised dB>|null", "cross_pol": "HVHV|null",
      "db_encoding": {"offset": -35, "scale": 0.2, "nodata": 255}   # dB = offset + value*scale
    }
"""
from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer

from .scene import SarScene

MAX_SIDE = 400  # cells on the longer side (~1 MB per date for three layers)
DB_OFFSET, DB_SCALE, NODATA = -35.0, 0.2, 255  # 0..250 -> -35..+15 dB


def grid_shape(bbox: tuple[float, float, float, float], max_side: int = MAX_SIDE) -> tuple[int, int]:
    """(width, height) with square-ish cells on the ground (cos(lat) correction)."""
    w, s, e, n = bbox
    width_km = (e - w) * math.cos(math.radians((s + n) / 2))
    height_km = n - s
    if width_km >= height_km:
        return max_side, max(1, round(max_side * height_km / width_km))
    return max(1, round(max_side * width_km / height_km)), max_side


def _lookup(scene: SarScene, bbox: tuple[float, ...], width: int, height: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Row/col index into the scene arrays for every grid cell centre (+ in-bounds mask)."""
    w, s, e, n = bbox
    lons = w + (np.arange(width) + 0.5) * (e - w) / width
    lats = n - (np.arange(height) + 0.5) * (n - s) / height
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    to_scene = Transformer.from_crs("EPSG:4326", f"EPSG:{scene.epsg}", always_xy=True)
    xs, ys = to_scene.transform(lon_grid, lat_grid)
    cols, rows = ~scene.transform * (xs, ys)
    cols, rows = np.floor(cols).astype(np.int64), np.floor(rows).astype(np.int64)
    rows_n, cols_n = scene.shape
    inside = (rows >= 0) & (rows < rows_n) & (cols >= 0) & (cols < cols_n)
    return np.clip(rows, 0, rows_n - 1), np.clip(cols, 0, cols_n - 1), inside


def _quantise_db(db: np.ndarray) -> np.ndarray:
    q = np.round((db - DB_OFFSET) / DB_SCALE)
    q = np.where(np.isfinite(q), np.clip(q, 0, 250), NODATA)
    return q.astype(np.uint8)


def _b64(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr, dtype=np.uint8).tobytes()).decode("ascii")


def decode(b64: str | None, width: int, height: int) -> np.ndarray | None:
    if not b64:
        return None
    return np.frombuffer(base64.b64decode(b64), dtype=np.uint8).reshape(height, width)


def dequantise(q: np.ndarray) -> np.ndarray:
    return np.where(q == NODATA, np.nan, DB_OFFSET + q.astype(np.float32) * DB_SCALE)


def build_grid(scene: SarScene, bbox: tuple[float, float, float, float] | None = None,
               max_side: int = MAX_SIDE) -> dict[str, Any]:
    bbox = tuple(bbox or scene.aoi_bbox or scene.bounds_lonlat)
    width, height = grid_shape(bbox, max_side)
    rows, cols, inside = _lookup(scene, bbox, width, height)

    def sample(arr: np.ndarray) -> np.ndarray:
        out = arr[rows, cols].astype(np.float32)
        out[~inside] = np.nan
        return out

    classes_full, method = scene.scattering_classes()
    classes = classes_full[rows, cols].astype(np.int16)
    classes[~inside | (classes < 0)] = NODATA
    co, cross = scene.co_pol, scene.cross_pol
    return {
        "version": 1,
        "granule_id": scene.granule_id,
        "date": (scene.identification.start_time or "")[:10],
        "bbox": [round(v, 6) for v in bbox],
        "width": width,
        "height": height,
        "classification_method": method,
        "classes": _b64(classes.astype(np.uint8)),
        "co_pol": co,
        "co_db": _b64(_quantise_db(sample(scene.clean_db(co)))),
        "cross_pol": cross,
        "cross_db": _b64(_quantise_db(sample(scene.clean_db(cross)))) if cross else None,
        "db_encoding": {"offset": DB_OFFSET, "scale": DB_SCALE, "nodata": NODATA},
    }


def export_globe_json(scene: SarScene, out: Path, stem: str) -> Path:
    path = out / f"{stem}_globe.json"
    path.write_text(json.dumps(build_grid(scene), separators=(",", ":")), encoding="utf-8")
    return path
