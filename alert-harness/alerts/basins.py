"""Cochabamba's torrent basins as vectors with terrain facts, so the web can draw and explain them.

The GAMC API only serves images, so (as with the districts):
  1. GetMap of "Cuencas de influencia": each basin in one flat translucent colour, opaque borders.
  2. Same-colour connected pixels -> polygons; each one is named with GetFeatureInfo (EPSG:3857).
  3. Per basin, from Copernicus DEM 30 m: area, elevation range, mean slope, % steep slopes and the
     Melton ratio R = relief / sqrt(area) (both in km). R > 0.6 identifies basins able to produce
     debris flows (mazamorras); 0.3–0.6 torrential floods; < 0.3 ordinary floods
     (Melton 1965; Wilford et al. 2004).
  4. If a nisar-harness run saw new sediment inside a basin, its area is attached (radar evidence).
Built once and cached in data/basins.geojson (refresh=True to rebuild).
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio import features
from rasterio.merge import merge
from rasterio.transform import from_bounds
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.geometry import Point

from .settings import HARNESS_DIR
from .sources.dem import GDAL_ENV, _tiles

log = logging.getLogger("alerts.basins")

WMS = "https://serviciosgamc.cochabamba.bo/api/gs/wms"
SERVICE_ID = "02ddf5a6-4d80-4ed3-8c73-b531b0574e81"  # Cuencas de influencia (proyecto 02)
BBOX = (-66.280703, -17.53119, -66.06952, -17.257306)
WIDTH = 1600
MIN_PIXELS = 400
STEEP_DEG = 25.0
SKIP_NAMES = {"Intercuencas y areas de aporte"}  # the urban valley floor, not a torrent basin
CACHE = HARNESS_DIR / "data" / "basins.geojson"
NISAR_RUNS = HARNESS_DIR.parent / "nisar-harness" / "output" / "runs"


def _wms(params: dict[str, Any]) -> requests.Response:
    base = {"key": os.environ["GAMC_WMS_KEY"], "service_id": SERVICE_ID, "SERVICE": "WMS",
            "VERSION": "1.1.1", "LAYERS": "", "QUERY_LAYERS": ""}
    resp = requests.get(WMS, params={**base, **params}, timeout=60)
    resp.raise_for_status()
    return resp


def _to3857(lon: float, lat: float) -> tuple[float, float]:
    return lon * 20037508.34 / 180, math.log(math.tan((90 + lat) * math.pi / 360)) * 20037508.34 / math.pi


def _name_at(lon: float, lat: float) -> str | None:
    x, y = _to3857(lon, lat)
    d = 15  # metres: small enough to hit only the basin under the point
    feats = _wms({"REQUEST": "GetFeatureInfo", "SRS": "EPSG:3857", "BBOX": f"{x - d},{y - d},{x + d},{y + d}",
                  "WIDTH": 11, "HEIGHT": 11, "X": 5, "Y": 5, "INFO_FORMAT": "application/json",
                  "FEATURE_COUNT": 1}).json().get("features", [])
    return feats[0]["properties"].get("Nombre") if feats else None


def _polygons() -> dict[str, Any]:
    w, s, e, n = BBOX
    height = round(WIDTH * (n - s) / (e - w))
    png = _wms({"REQUEST": "GetMap", "SRS": "EPSG:4326", "STYLES": "", "BBOX": f"{w},{s},{e},{n}",
                "WIDTH": WIDTH, "HEIGHT": height, "FORMAT": "image/png", "TRANSPARENT": "true"}).content
    rgba = np.array(Image.open(io.BytesIO(png)).convert("RGBA")).astype(np.int32)
    rgb = rgba[..., :3]
    alpha = rgba[..., 3]
    fill = (alpha > 60) & (alpha < 120)  # fill is translucent (alpha ~89); border lines are opaque
    labels = (rgb[..., 0] // 8) * 1024 + (rgb[..., 1] // 8) * 32 + rgb[..., 2] // 8 + 1
    labels = np.where(fill, labels, 0).astype(np.int32)
    transform = from_bounds(w, s, e, n, WIDTH, height)
    px_deg = (e - w) / WIDTH

    by_name: dict[str, list] = {}
    for geom, _ in features.shapes(labels, mask=fill, transform=transform, connectivity=4):
        poly = shape(geom)
        if poly.area / px_deg**2 < MIN_PIXELS:
            continue
        poly = Polygon(poly.exterior)  # drop holes left by labels/symbols painted over the fill
        name = _name_at(*poly.representative_point().coords[0])
        if not name or name in SKIP_NAMES:
            continue
        by_name.setdefault(name, []).append(poly.buffer(1.5 * px_deg))
    return {name: unary_union(polys).simplify(px_deg, preserve_topology=True) for name, polys in by_name.items()}


def _dem() -> tuple[np.ndarray, np.ndarray, Any]:
    with rasterio.Env(**GDAL_ENV):
        datasets = [rasterio.open("/vsicurl/" + u) for u in _tiles(BBOX)]
        try:
            mosaic, transform = merge(datasets, bounds=BBOX)
        finally:
            for ds in datasets:
                ds.close()
    z = mosaic[0].astype(float)
    z[z < -100] = np.nan
    lat = (BBOX[1] + BBOX[3]) / 2
    gy, gx = np.gradient(z, abs(transform.e) * 110_570, transform.a * 111_320 * math.cos(math.radians(lat)))
    return z, np.degrees(np.arctan(np.hypot(gx, gy))), transform


def _melton_class(r: float) -> str:
    return "mazamorra" if r > 0.6 else "crecida_torrencial" if r > 0.3 else "inundacion"


def _radar_sediment(polys: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Newest nisar-harness run with new-sediment points inside each basin -> area (km²) and dates."""
    names = list(polys)
    tree = STRtree([polys[n] for n in names])
    found: dict[str, dict[str, Any]] = {}
    for run in sorted(NISAR_RUNS.glob("*/hotspots.geojson"), reverse=True):
        try:
            fc = json.loads(run.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary = fc.get("summary", {})
        cell = summary.get("cell_area_km2") or 0
        counts: dict[str, int] = {}
        for f in fc.get("features", []):
            if f["properties"].get("kind") != "nuevo_sedimento":
                continue
            pt = Point(f["geometry"]["coordinates"])
            for i in tree.query(pt, predicate="within"):
                counts[names[i]] = counts.get(names[i], 0) + 1
        for name, n in counts.items():
            found.setdefault(name, {"area_km2": round(n * cell, 3), "desde": summary.get("from_date"),
                                    "hasta": summary.get("to_date"), "corrida": run.parent.name})
    return found


def build() -> dict[str, Any]:
    polys = _polygons()
    z, slope, transform = _dem()
    sediment = _radar_sediment(polys)
    feats = []
    for name, geom in sorted(polys.items()):
        mask = features.geometry_mask([mapping(geom)], z.shape, transform, invert=True)
        zz, ss = z[mask], slope[mask]
        ok = np.isfinite(ss)
        if not ok.any():
            continue
        lat = geom.centroid.y
        area_km2 = geom.area * 111.32 * 110.57 * math.cos(math.radians(lat))
        relief_km = float(np.nanmax(zz) - np.nanmin(zz)) / 1000
        melton = relief_km / math.sqrt(area_km2)
        p = geom.representative_point()
        feats.append({"type": "Feature", "geometry": mapping(geom), "properties": {
            "id": name, "nombre": name.removeprefix("C. ").strip(),
            "area_km2": round(area_km2, 2),
            "cota_min_m": round(float(np.nanmin(zz))), "cota_max_m": round(float(np.nanmax(zz))),
            "pendiente_media_grados": round(float(np.nanmean(ss)), 1),
            "ladera_fuerte_pct": round(100 * float(np.mean(ss[ok] > STEEP_DEG)), 1),
            "melton": round(melton, 2), "tipo": _melton_class(melton),
            "sedimento_radar": sediment.get(name),
            "centro": [round(p.x, 5), round(p.y, 5)],
            "bbox": [round(v, 5) for v in geom.bounds],
        }})
    log.info("Cuencas vectorizadas: %d", len(feats))
    return {"type": "FeatureCollection",
            "source": "GAMC WMS Cuencas de influencia (reconstruido) + Copernicus DEM GLO-30 + nisar-harness",
            "features": feats}


def load(refresh: bool = False) -> list[dict[str, Any]]:
    if refresh or not CACHE.exists():
        fc = build()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return json.loads(CACHE.read_text(encoding="utf-8"))["features"]


def path() -> Path:
    return CACHE
