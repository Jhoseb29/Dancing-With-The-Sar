"""Lugares para filtrar eventos: bbox de places.json y polígono real de Bolivia (Natural Earth).

El filtro es vectorizado (shapely 2) porque un bloque de FIRMS sobre el bbox de Bolivia
trae decenas de miles de focos (incluye zonas de Brasil): un bucle Python bloquearía el servidor.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import shapely
from shapely.geometry import shape

BBox = tuple[float, float, float, float]

_BOLIVIA_GEOJSON = Path(__file__).resolve().parents[1] / "data" / "bolivia_ne50m.geojson"


@dataclass(frozen=True)
class Place:
    id: str
    bbox: BBox
    geometry: shapely.Geometry | None = None  # None = usar solo bbox

    def contains_many(self, lons: Sequence[float], lats: Sequence[float]) -> np.ndarray:
        """Máscara booleana de los puntos dentro del lugar."""
        x = np.asarray(lons, dtype=float)
        y = np.asarray(lats, dtype=float)
        min_lon, min_lat, max_lon, max_lat = self.bbox
        mask = (x >= min_lon) & (x <= max_lon) & (y >= min_lat) & (y <= max_lat)
        if self.geometry is not None and mask.any():
            idx = np.flatnonzero(mask)
            mask[idx] = shapely.contains_xy(self.geometry, x[idx], y[idx])
        return mask

    def contains(self, lon: float, lat: float) -> bool:
        return bool(self.contains_many([lon], [lat])[0])


class PlaceResolver:
    def __init__(self, ui_config_dir: Path) -> None:
        data = json.loads((ui_config_dir / "places.json").read_text(encoding="utf-8"))
        self._bboxes = {p["id"]: tuple(p["bbox"]) for p in data["places"]}
        geometry = json.loads(_BOLIVIA_GEOJSON.read_text(encoding="utf-8"))["features"][0]["geometry"]
        self._bolivia = shape(geometry)
        shapely.prepare(self._bolivia)

    def get(self, place_id: str) -> Place | None:
        bbox = self._bboxes.get(place_id)
        if bbox is None:
            return None
        return Place(place_id, bbox, self._bolivia if place_id == "bolivia" else None)  # type: ignore[arg-type]
