"""Change hotspots between the oldest and newest take of a run (same globe grid, cell by cell).

Changes are RELATIVE: the scene-wide median shift is removed first (product-version
calibration offsets, uniform moisture), so only local changes become hotspots.
Rules are per theme and physical (L-band):
  * vegetation loss (fires / deforestation): vegetation cell whose HV drops >= 3 dB
  * new sediment (mudflows / "mazamorras", flood deposits): vegetation cell that becomes bare
    soil AND loses volume scattering (cross-pol drops >= 2 dB): mud buried the canopy/crops.
    Only inside the channel corridor (lib/drainage.py): away from channels it is agriculture.
  * new water (floods): cell becomes "water" AND HH darkens >= 3 dB (specular)
  * lost water: "water" cell that brightens >= 3 dB
  * new urban: cell becomes "urban" (double bounce) AND HH brightens >= 3 dB
  * generic: |HH change| >= 4 dB
Each cell is counted once: kinds are evaluated in the theme's priority order.
Output: GeoJSON points at cell centres (strongest first, capped) + a summary for the interpreter.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .drainage import Corridor
from .globe import decode, dequantise

MAX_POINTS = 3000
SEDIMENT_CROSS_DROP_DB = 2.0  # lower than plain vegetation loss: the class change is evidence too
WATER, SOIL, VEG, URBAN, NODATA = 0, 1, 2, 3, 255
CLASS_NAMES = {WATER: "agua", SOIL: "suelo", VEG: "vegetacion", URBAN: "urbano"}

THEME_KINDS: dict[str, tuple[str, ...]] = {
    "incendios": ("perdida_vegetacion",),
    "vegetacion": ("perdida_vegetacion",),
    "inundacion": ("nueva_agua", "nuevo_sedimento"),
    "cuenca_hidrica": ("nueva_agua", "nuevo_sedimento", "perdida_agua"),
    "urbano": ("nuevo_urbano",),
    "general": ("nueva_agua", "nuevo_sedimento", "perdida_vegetacion", "nuevo_urbano"),
}


def _layers(grid: dict[str, Any]) -> dict[str, np.ndarray | None]:
    w, h = grid["width"], grid["height"]
    cross = decode(grid.get("cross_db"), w, h)
    return {
        "classes": decode(grid["classes"], w, h),
        "co": dequantise(decode(grid["co_db"], w, h)),
        "cross": dequantise(cross) if cross is not None else None,
    }


def _relative(after: np.ndarray, before: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, float]:
    """Change minus the scene-wide median shift: removes calibration/product-version offsets
    and uniform moisture changes, so only *local* changes remain."""
    delta = after - before
    shift = float(np.nanmedian(delta[valid])) if valid.any() else 0.0
    return np.nan_to_num(delta - shift), round(shift, 2)


def _candidates(a: dict, b: dict) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], dict[str, float]]:
    """kind -> (mask, magnitude dB). A class transition only counts with a real local brightness change."""
    ca, cb = a["classes"], b["classes"]
    valid = (ca != NODATA) & (cb != NODATA)
    d_co, shift_co = _relative(b["co"], a["co"], valid)
    has_cross = a["cross"] is not None and b["cross"] is not None
    d_x, shift_x = _relative(b["cross"], a["cross"], valid) if has_cross else (None, None)

    biomass_drop = d_x if d_x is not None else d_co
    veg_loss = valid & (ca == VEG) & (biomass_drop <= -3.0)
    new_sediment = valid & (ca == VEG) & (cb == SOIL) & (biomass_drop <= -SEDIMENT_CROSS_DROP_DB)
    new_water = valid & (cb == WATER) & (ca != WATER) & (d_co <= -3.0)
    lost_water = valid & (ca == WATER) & (cb != WATER) & (d_co >= 3.0)
    new_urban = valid & (cb == URBAN) & (ca != URBAN) & (d_co >= 3.0)
    return {
        "perdida_vegetacion": (veg_loss, np.abs(biomass_drop)),
        "nuevo_sedimento": (new_sediment, np.abs(biomass_drop)),
        "nueva_agua": (new_water, np.abs(d_co)),
        "perdida_agua": (lost_water, np.abs(d_co)),
        "nuevo_urbano": (new_urban, np.abs(d_co)),
        "cambio": (valid & (np.abs(d_co) >= 4.0), np.abs(d_co)),
    }, {"co_db": shift_co, "cross_db": shift_x}


def detect(oldest: dict[str, Any], newest: dict[str, Any], theme: str,
           corridor: Corridor | None = None) -> dict[str, Any]:
    """`corridor` restricts sediment to the surroundings of channels (lib/drainage.py)."""
    if (oldest["width"], oldest["height"], oldest["bbox"]) != (newest["width"], newest["height"], newest["bbox"]):
        raise ValueError("Las grillas no coinciden: no se pueden comparar celda a celda")
    a, b = _layers(oldest), _layers(newest)
    kinds = THEME_KINDS.get(theme, THEME_KINDS["general"])
    cands, scene_shift = _candidates(a, b)
    if corridor is not None and corridor.mask is not None and corridor.mask.shape == a["classes"].shape:
        mask, mag = cands["nuevo_sedimento"]
        cands["nuevo_sedimento"] = (mask & corridor.mask, mag)

    w, s, e, n = newest["bbox"]
    width, height = newest["width"], newest["height"]
    cell_area_km2 = float((e - w) * 111.32 * np.cos(np.radians((s + n) / 2)) / width * (n - s) * 110.57 / height)
    valid_cells = int(((a["classes"] != NODATA) & (b["classes"] != NODATA)).sum())

    points: list[tuple[float, int, int, str]] = []
    summary: dict[str, Any] = {}
    taken = np.zeros_like(a["classes"], dtype=bool)
    for kind in kinds:
        mask, mag = cands[kind]
        mask = mask & ~taken  # one cell = one kind (theme priority order)
        taken |= mask
        count = int(mask.sum())
        summary[kind] = {"cells": count, "area_km2": round(count * cell_area_km2, 2),
                         "pct_of_area": round(100 * count / max(valid_cells, 1), 2)}
        rows, cols = np.nonzero(mask)
        points += [(float(mag[r, c]), int(r), int(c), kind) for r, c in zip(rows, cols)]

    points.sort(key=lambda p: p[0], reverse=True)
    features = []
    for magnitude, r, c, kind in points[:MAX_POINTS]:
        lon = w + (c + 0.5) * (e - w) / width
        lat = n - (r + 0.5) * (n - s) / height
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
            "properties": {
                "kind": kind,
                "magnitude_db": round(magnitude, 1),
                "intensity": round(min(magnitude / 10.0, 1.0), 2),
                "from": CLASS_NAMES.get(int(a["classes"][r, c])),
                "to": CLASS_NAMES.get(int(b["classes"][r, c])),
            },
        })
    return {
        "type": "FeatureCollection",
        "summary": {
            "from_date": oldest.get("date"), "to_date": newest.get("date"), "theme": theme,
            "cell_area_km2": round(float(cell_area_km2), 4), "kinds": summary,
            "scene_shift_db": scene_shift,
            "sediment_corridor": (corridor.summary() if corridor is not None
                                  else {"applied": False, "sources": [], "errors": ["no solicitado"]}),  # removed before thresholding (calibration / uniform moisture)
            "points_shown": len(features), "points_total": len(points),
        },
        "features": features,
    }


def write_hotspots(globe_paths: list[Path], theme: str, out: Path,
                   corridor: Corridor | None = None) -> dict[str, Any] | None:
    """globe_paths sorted oldest -> newest. Returns the summary (or None with < 2 takes)."""
    if len(globe_paths) < 2:
        return None
    oldest, newest = (json.loads(p.read_text(encoding="utf-8")) for p in (globe_paths[0], globe_paths[-1]))
    fc = detect(oldest, newest, theme, corridor)
    out.write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    return fc["summary"]
