"""Turn the class grid of a take into geographic OBJECTS (vector polygons) for the web globe.

Each connected patch of one scattering class (a lagoon, an urban patch, a bare/burnt area,
a forest block) becomes a polygon with its own statistics, so the globe can draw it as part
of the terrain (fills, 3D extrusions, clickable) instead of an image laid on top.

Steps: majority filter (removes speckle) -> polygonize -> drop tiny patches ->
smooth (round buffer in/out) + simplify -> per-object stats (area, mean HH/HV).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from rasterio import features
from rasterio.transform import from_bounds
from shapely.geometry import mapping, shape

from .globe import NODATA, build_grid, decode, dequantise
from .scene import SarScene

CLASS_KEYS = {0: "water", 1: "soil", 2: "vegetation", 3: "urban"}
# Minimum patch size (cells) per class: small lagoons and urban blocks matter, small soil/forest specks don't.
MIN_CELLS = {0: 3, 1: 12, 2: 40, 3: 8}
SMOOTH = 0.45  # buffer distance in cells for rounded, natural edges
SIMPLIFY = 0.35  # Douglas-Peucker tolerance in cells


def _majority(classes: np.ndarray) -> np.ndarray:
    """3x3 mode filter (ignores nodata) to remove single-cell speckle before vectorising."""
    h, w = classes.shape
    padded = np.pad(classes, 1, mode="edge")
    counts = np.zeros((4, h, w), dtype=np.uint8)
    for dy in range(3):
        for dx in range(3):
            window = padded[dy:dy + h, dx:dx + w]
            for c in range(4):
                counts[c] += window == c
    out = counts.argmax(axis=0).astype(np.uint8)
    out[(classes == NODATA) | (counts.max(axis=0) == 0)] = NODATA
    return out


def build_objects(grid: dict[str, Any]) -> dict[str, Any]:
    w, s, e, n = grid["bbox"]
    width, height = grid["width"], grid["height"]
    classes = _majority(decode(grid["classes"], width, height))
    co = dequantise(decode(grid["co_db"], width, height))
    cross_q = decode(grid.get("cross_db"), width, height)
    cross = dequantise(cross_q) if cross_q is not None else None

    transform = from_bounds(w, s, e, n, width, height)
    cell_deg = (e - w) / width
    km_per_deg_lon = 111.32 * math.cos(math.radians((s + n) / 2))
    cell_km2 = (e - w) / width * km_per_deg_lon * (n - s) / height * 110.57

    feats = []
    for geom, value in features.shapes(classes, mask=classes != NODATA, transform=transform, connectivity=8):
        cls = int(value)
        poly = shape(geom)
        cells = poly.area / (cell_deg * (n - s) / height)
        if cells < MIN_CELLS.get(cls, 10):
            continue
        smooth = poly.buffer(SMOOTH * cell_deg, quad_segs=2).buffer(-SMOOTH * cell_deg, quad_segs=2)
        smooth = smooth.simplify(SIMPLIFY * cell_deg, preserve_topology=True)
        if smooth.is_empty:
            continue
        # Stats over the cells this patch covers.
        mask = features.geometry_mask([geom], (height, width), transform, invert=True)
        feats.append({
            "type": "Feature",
            "geometry": mapping(smooth),
            "properties": {
                "class_id": cls,
                "class": CLASS_KEYS[cls],
                "cells": round(cells),
                "area_km2": round(cells * cell_km2, 3),
                "co_db": _mean(co, mask),
                "cross_db": _mean(cross, mask) if cross is not None else None,
            },
        })
    # Big patches first: the frontend draws them underneath the small ones.
    feats.sort(key=lambda f: f["properties"]["area_km2"], reverse=True)
    return {"type": "FeatureCollection", "date": grid.get("date"), "bbox": grid["bbox"], "features": feats}


def _mean(arr: np.ndarray | None, mask: np.ndarray) -> float | None:
    if arr is None:
        return None
    vals = arr[mask]
    vals = vals[np.isfinite(vals)]
    return round(float(vals.mean()), 1) if vals.size else None


def _write(fc: dict[str, Any], path: Path) -> Path:
    # 5 decimals ≈ 1 m: enough for 100 m+ cells, keeps the file small.
    text = json.dumps(fc, separators=(",", ":"))
    path.write_text(_round_coords(text), encoding="utf-8")
    return path


def _round_coords(text: str) -> str:
    import re

    return re.sub(r"(-?\d+\.\d{5})\d+", r"\1", text)


def export_objects(scene: SarScene, out: Path, stem: str) -> Path:
    return _write(build_objects(build_grid(scene)), out / f"{stem}_objects.geojson")


def objects_from_globe_file(globe_path: Path, out_path: Path) -> Path:
    """Regenerate objects from an existing *_globe.json (no AWS access needed)."""
    return _write(build_objects(json.loads(globe_path.read_text(encoding="utf-8"))), out_path)
