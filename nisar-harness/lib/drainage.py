"""Drainage network on the globe grid -> corridor where flood/mudflow sediment is physically plausible.

Mud from a "mazamorra" or a river overflow is deposited next to the channel, not in the middle
of a field. Restricting the sediment hotspots to a corridor around channels removes agricultural
changes (harvest, tillage) that look identical in radar.

Sources (combined, both optional):
  * OpenStreetMap SIGNIFICANT waterways via Overpass - anywhere in Bolivia: every river, and
    streams only when named (named quebradas are the recognised torrenteras). Unnamed gullies,
    irrigation canals and drains are excluded: in farm valleys they cover almost everything and
    canals mark exactly the fields whose harvest/tillage we want to exclude.
  * GAMC "Drenaje e Influencia" WMS (official torrenteras of Cochabamba) - when the AOI touches it
The channel mask is rasterised on the run's globe grid and dilated by CORRIDOR_M.
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import requests
from PIL import Image
from rasterio import features
from rasterio.transform import from_bounds
from shapely.geometry import LineString, box, mapping

log = logging.getLogger("nisar.drainage")

CORRIDOR_M = 300  # half-width of the corridor around a channel
# Public Overpass instances fail now and then (502/504): try the main one, then a mirror.
OVERPASS_URLS = tuple(os.environ.get("OVERPASS_URLS", "https://overpass-api.de/api/interpreter,"
                                     "https://overpass.kumi.systems/api/interpreter").split(","))
OSM_WATERWAYS = ("river", "stream")
GAMC_WMS = "https://serviciosgamc.cochabamba.bo/api/gs/wms"
GAMC_DRAINAGE_SERVICE = "d4cea6e3-fc7f-482a-94ad-bd377df78886"
GAMC_DRAINAGE_BBOX = (-66.269936, -17.530591, -66.045853, -17.260142)


@dataclass
class Corridor:
    mask: np.ndarray | None  # bool (height, width) on the globe grid; None = no drainage data
    sources: list[str] = field(default_factory=list)
    buffer_m: int = CORRIDOR_M
    channels: dict[str, Any] | None = None  # OSM lines as GeoJSON (for the globe)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "applied": self.mask is not None,
            "sources": self.sources,
            "buffer_m": self.buffer_m,
            "pct_area_in_corridor": round(100 * float(self.mask.mean()), 1) if self.mask is not None else None,
            "errors": self.errors,
        }


def _osm_channels(bbox: tuple[float, ...]) -> dict[str, Any]:
    w, s, e, n = bbox
    kinds = "|".join(OSM_WATERWAYS)
    query = f'[out:json][timeout:60];way["waterway"~"^({kinds})$"]({s},{w},{n},{e});out geom;'
    errors = []
    for attempt, url in enumerate([u for u in OVERPASS_URLS for _ in range(2)]):
        try:
            resp = requests.post(url, data={"data": query}, timeout=90,
                                 headers={"User-Agent": "nisar-harness (hackathon research)"})
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            break
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url.split('/')[2]}: {exc.__class__.__name__}")
            time.sleep(2 * (attempt + 1))
    else:
        raise ConnectionError("; ".join(errors))
    features_ = []
    for way in elements:
        coords = [(p["lon"], p["lat"]) for p in way.get("geometry", [])]
        tags = way.get("tags", {})
        significant = tags.get("waterway") == "river" or bool(tags.get("name"))
        if len(coords) >= 2 and significant:
            features_.append({"type": "Feature", "geometry": mapping(LineString(coords)),
                              "properties": {"waterway": tags.get("waterway"), "name": tags.get("name")}})
    return {"type": "FeatureCollection", "features": features_}


def _gamc_channels(bbox: tuple[float, ...], width: int, height: int) -> np.ndarray | None:
    key = os.environ.get("GAMC_WMS_KEY")
    if not key or not box(*bbox).intersects(box(*GAMC_DRAINAGE_BBOX)):
        return None
    params = {"key": key, "service_id": GAMC_DRAINAGE_SERVICE, "SERVICE": "WMS", "VERSION": "1.1.1",
              "REQUEST": "GetMap", "LAYERS": "", "STYLES": "", "SRS": "EPSG:4326",
              "BBOX": ",".join(str(v) for v in bbox), "WIDTH": width, "HEIGHT": height,
              "FORMAT": "image/png", "TRANSPARENT": "true"}
    resp = requests.get(GAMC_WMS, params=params, timeout=60)
    resp.raise_for_status()
    rgba = np.array(Image.open(io.BytesIO(resp.content)).convert("RGBA"))
    return rgba[..., 3] > 0


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Square dilation by `radius` cells (separable running max via cumulative sums)."""
    if radius <= 0:
        return mask
    out = mask.astype(np.int32)
    for axis in (0, 1):
        padded = np.pad(out, [(radius + 1, radius) if a == axis else (0, 0) for a in range(2)])
        csum = np.cumsum(padded, axis=axis)
        hi = np.take(csum, np.arange(2 * radius + 1, csum.shape[axis]), axis=axis)
        lo = np.take(csum, np.arange(0, csum.shape[axis] - 2 * radius - 1), axis=axis)
        out = ((hi - lo) > 0).astype(np.int32)
    return out.astype(bool)


def build_corridor(grid: dict[str, Any], buffer_m: int = CORRIDOR_M) -> Corridor:
    """Channel corridor on the same lon/lat grid as the globe JSON (bbox, width, height)."""
    w, s, e, n = grid["bbox"]
    width, height = grid["width"], grid["height"]
    transform = from_bounds(w, s, e, n, width, height)
    channels = np.zeros((height, width), dtype=bool)
    corridor = Corridor(mask=None, buffer_m=buffer_m)

    try:
        fc = _osm_channels((w, s, e, n))
        if fc["features"]:
            channels |= features.rasterize(((f["geometry"], 1) for f in fc["features"]),
                                           out_shape=(height, width), transform=transform,
                                           all_touched=True, dtype="uint8").astype(bool)
            corridor.sources.append(f"OpenStreetMap ({len(fc['features'])} cauces)")
            corridor.channels = fc
    except Exception as exc:  # noqa: BLE001 - one source failing must not stop the other
        corridor.errors.append(f"OSM: {exc}")
        log.warning("Cauces OSM no disponibles: %s", exc)
    try:
        gamc = _gamc_channels((w, s, e, n), width, height)
        if gamc is not None and gamc.any():
            channels |= gamc
            corridor.sources.append("GAMC Drenaje e Influencia (torrenteras)")
    except Exception as exc:  # noqa: BLE001
        corridor.errors.append(f"GAMC: {exc}")
        log.warning("Drenaje GAMC no disponible: %s", exc)

    if channels.any():
        cell_m = min((e - w) * 111_320 * math.cos(math.radians((s + n) / 2)) / width, (n - s) * 110_570 / height)
        corridor.mask = _dilate(channels, max(1, round(buffer_m / cell_m)))
    return corridor


def write_channels(corridor: Corridor, path: Path) -> Path | None:
    if not corridor.channels:
        path.unlink(missing_ok=True)  # never leave channels from a previous attempt
        return None
    path.write_text(json.dumps(corridor.channels, separators=(",", ":")), encoding="utf-8")
    return path
