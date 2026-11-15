"""Cochabamba's 15 districts as polygons, rebuilt from the GAMC WMS (the API only serves images).

1. GetMap of "Límite Distritos" in EPSG:4326: semi-transparent fill (alpha ~38) + opaque borders.
2. Fill pixels -> connected regions -> polygons (borders separate them).
3. Each region is named with GetFeatureInfo at an interior point (Distrito, Comuna).
Done once and cached in data/districts.geojson (pass refresh=True to rebuild).
"""
from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image
from rasterio import features
from rasterio.transform import from_bounds
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

from .settings import HARNESS_DIR

log = logging.getLogger("alerts.districts")

WMS = "https://serviciosgamc.cochabamba.bo/api/gs/wms"
SERVICE_ID = "7eb13092-bf0e-493b-aae6-03c43eedda2c"  # Límite Distritos (proyecto 02)
BBOX = (-66.280703, -17.53119, -66.06952, -17.257306)
WIDTH = 1600
CACHE = HARNESS_DIR / "data" / "districts.geojson"
MIN_PIXELS = 1500  # discard slivers between borders


def _wms(params: dict[str, Any]) -> requests.Response:
    base = {"key": os.environ["GAMC_WMS_KEY"], "service_id": SERVICE_ID, "SERVICE": "WMS",
            "VERSION": "1.1.1", "LAYERS": "", "SRS": "EPSG:4326"}
    resp = requests.get(WMS, params={**base, **params}, timeout=60)
    resp.raise_for_status()
    return resp


def _name_at(lon: float, lat: float) -> dict[str, Any]:
    d = 0.0005
    resp = _wms({"REQUEST": "GetFeatureInfo", "QUERY_LAYERS": "", "BBOX": f"{lon - d},{lat - d},{lon + d},{lat + d}",
                 "WIDTH": 11, "HEIGHT": 11, "X": 5, "Y": 5, "INFO_FORMAT": "application/json", "FEATURE_COUNT": 1})
    feats = resp.json().get("features", [])
    return feats[0]["properties"] if feats else {}


def build() -> dict[str, Any]:
    w, s, e, n = BBOX
    height = round(WIDTH * (n - s) / (e - w))
    png = _wms({"REQUEST": "GetMap", "STYLES": "", "BBOX": f"{w},{s},{e},{n}", "WIDTH": WIDTH, "HEIGHT": height,
                "FORMAT": "image/png", "TRANSPARENT": "true"}).content
    alpha = np.array(Image.open(io.BytesIO(png)).convert("RGBA"))[..., 3]
    fill = ((alpha > 0) & (alpha < 120)).astype(np.uint8)  # fill is translucent, borders opaque
    transform = from_bounds(w, s, e, n, WIDTH, height)
    px_deg = (e - w) / WIDTH

    by_district: dict[str, list] = {}
    meta: dict[str, dict[str, Any]] = {}
    for geom, _ in features.shapes(fill, mask=fill.astype(bool), transform=transform, connectivity=4):
        poly = shape(geom)
        if poly.area / px_deg**2 < MIN_PIXELS:
            continue
        poly = Polygon(poly.exterior)  # drop holes left by labels/symbols painted over the fill
        poly = poly.buffer(2 * px_deg)  # close the gap left by the border line
        props = _name_at(*poly.representative_point().coords[0])
        name = props.get("Distrito")
        if not name:
            continue
        by_district.setdefault(name, []).append(poly)
        meta[name] = props
    feats = []
    for name, polys in sorted(by_district.items(), key=lambda kv: int("".join(filter(str.isdigit, kv[0])) or 0)):
        geom = unary_union(polys).simplify(px_deg, preserve_topology=True)
        feats.append({"type": "Feature", "geometry": mapping(geom),
                      "properties": {"id": name, "distrito": name, "comuna": meta[name].get("Comuna"),
                                     "bbox": [round(v, 5) for v in geom.bounds],
                                     "centro": _label_point(geom)}})
    return {"type": "FeatureCollection", "source": "GAMC WMS Límite Distritos (reconstruido)", "features": feats}


def _label_point(geom) -> list[float]:
    """Interior point for the map label (a centroid can fall outside a concave district)."""
    p = geom.representative_point()
    return [round(p.x, 5), round(p.y, 5)]


def load(refresh: bool = False) -> list[dict[str, Any]]:
    if refresh or not CACHE.exists():
        fc = build()
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
        log.info("Distritos reconstruidos: %d", len(fc["features"]))
    return json.loads(CACHE.read_text(encoding="utf-8"))["features"]


def path() -> Path:
    return CACHE
