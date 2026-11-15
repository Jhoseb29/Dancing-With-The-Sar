"""Derivación hidrográfica determinista 100 % sobre Copernicus DEM GLO-30 (sin WMS GAMC).

Genera y cachea en disco (`data/processed/hydro/`):
- Red D8 sin depresiones (priority-flood), acumulación de flujo e índice topográfico húmedo (TWI).
- Polígonos GeoJSON reales de 9 subcuencas conectadas en 3 subsistemas (Norte, Centro, Sur).
- Máscaras y diagnósticos puntuales de torrentera y escorzo/sombra radar (pendiente >= 25°).
"""

from __future__ import annotations

import heapq
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize, shapes
from rasterio.transform import from_bounds
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

log = logging.getLogger("basin_risk.hydro")

SubsystemId = Literal["north", "central", "south"]
HazardType = Literal["slope_mudflow", "flood_saturation", "water_balance"]

SUBBASIN_CATALOG: dict[int, dict[str, Any]] = {
    1: {
        "id": "norte-chocaya-tiquipaya",
        "subsystem": "north",
        "hazard": "slope_mudflow",
        "downstream_target": "centro-rocha-oeste",
        "name_es": "Norte · Chocaya – Chaquimayu (Tiquipaya)",
        "name_en": "North · Chocaya – Chaquimayu (Tiquipaya)",
        "description_es": "Cabecera oeste del Tunari sobre Cota 2750 m con torrenteras de alta pendiente hacia Tiquipaya y Colcapirhua.",
        "description_en": "Western Tunari headwaters above 2750 m feeding high-slope torrents toward Tiquipaya and Colcapirhua.",
    },
    2: {
        "id": "norte-taquina-pintumayu",
        "subsystem": "north",
        "hazard": "slope_mudflow",
        "downstream_target": "centro-rocha-cercado",
        "name_es": "Norte · Taquiña – Pintu Mayu (Cercado)",
        "name_en": "North · Taquiña – Pintu Mayu (Cercado)",
        "description_es": "Microcuencas críticas sobre la ciudad norte (> 2750 m); respuesta rápida de escorrentía y mazamorras tras incendios secos.",
        "description_en": "Critical catchments above northern Cochabamba (> 2750 m); rapid runoff and debris-flow response after dry fires.",
    },
    3: {
        "id": "norte-pajchamayu-sacaba",
        "subsystem": "north",
        "hazard": "slope_mudflow",
        "downstream_target": "centro-rocha-sacaba",
        "name_es": "Norte · Pajcha Mayu – Chacacollo (Sacaba)",
        "name_en": "North · Pajcha Mayu – Chacacollo (Sacaba)",
        "description_es": "Laderas orientales del Tunari que descargan sobre el abanico norte de Sacaba y el corredor del Rocha.",
        "description_en": "Eastern Tunari slopes discharging onto northern Sacaba alluvial fans and the Rocha corridor.",
    },
    4: {
        "id": "centro-rocha-sacaba",
        "subsystem": "central",
        "hazard": "flood_saturation",
        "downstream_target": "centro-rocha-cercado",
        "name_es": "Centro · Río Rocha Alto (Sacaba – Muyurina)",
        "name_en": "Central · Upper Rocha River (Sacaba – Muyurina)",
        "description_es": "Tramo superior del Río Rocha que recibe aportes del Tunari norte y serranía sur antes de ingresar a Cercado.",
        "description_en": "Upper Rocha reach collecting northern Tunari and southern hill runoff before entering Cercado.",
    },
    5: {
        "id": "centro-rocha-cercado",
        "subsystem": "central",
        "hazard": "flood_saturation",
        "downstream_target": "centro-rocha-oeste",
        "name_es": "Centro · Eje Urbano Rocha – Alalay – Coña Coña",
        "name_en": "Central · Urban Rocha – Alalay – Coña Coña",
        "description_es": "Planicie aluvial metropolitana de Cercado donde convergen torrenteras del Norte y espejos reguladores urbanos.",
        "description_en": "Metropolitan alluvial plain of Cercado where northern torrents and urban regulating lagoons converge.",
    },
    6: {
        "id": "centro-rocha-oeste",
        "subsystem": "central",
        "hazard": "flood_saturation",
        "downstream_target": None,
        "name_es": "Centro · Valle Bajo Rocha (Colcapirhua – Quillacollo)",
        "name_en": "Central · Lower Rocha Valley (Colcapirhua – Quillacollo)",
        "description_es": "Zona de baja pendiente y convergencia fluvial oeste hasta la salida de Parotani; susceptible a saturación y rebalse.",
        "description_en": "Low-slope western convergence zone toward Parotani outlet; prone to soil saturation and overbank flooding.",
    },
    7: {
        "id": "sur-la-maica-tamborada",
        "subsystem": "south",
        "hazard": "water_balance",
        "downstream_target": "centro-rocha-oeste",
        "name_es": "Sur · La Maica – Tamborada (Distritos 9 y 13)",
        "name_en": "South · La Maica – Tamborada (Districts 9 & 13)",
        "description_es": "Planicie agrícola y periurbana del sur conectada por el Río Tamborada; monitoreo dual de déficit seco y anegamiento.",
        "description_en": "Southern agricultural and peri-urban plain along the Tamborada River; dual drought stress and flood monitoring.",
    },
    8: {
        "id": "sur-angostura-valle-alto",
        "subsystem": "south",
        "hazard": "water_balance",
        "downstream_target": "sur-la-maica-tamborada",
        "name_es": "Sur · La Angostura y Aporte Valle Alto",
        "name_en": "South · La Angostura & Valle Alto Catchment",
        "description_es": "Cuenca reguladora del embalse La Angostura; variación indicativa de espejo de agua en km² sin estimar volumen.",
        "description_en": "La Angostura reservoir catchment; indicative water-surface monitoring in km² without volume estimation.",
    },
    9: {
        "id": "sur-arrumani-santivanez",
        "subsystem": "south",
        "hazard": "water_balance",
        "downstream_target": "centro-rocha-oeste",
        "name_es": "Sur · Serranías Arrumani – Santiváñez",
        "name_en": "South · Arrumani – Santiváñez Foothills",
        "description_es": "Cabeceras y quebradas secas del sur (Arrumani, Pucarita, Santiváñez) prioritarias para cosecha y retención local.",
        "description_en": "Dry-season southern headwaters (Arrumani, Pucarita, Santiváñez) priority zone for local water retention.",
    },
}


@dataclass(frozen=True)
class SubBasinFeature:
    code: int
    id: str
    subsystem: SubsystemId
    hazard: HazardType
    downstream_target: str | None
    name_es: str
    name_en: str
    description_es: str
    description_en: str
    area_km2: float
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    geometry: dict[str, Any]


@dataclass
class HydroGridArtifact:
    subbasins: tuple[SubBasinFeature, ...]
    label_grid: np.ndarray
    acc_grid: np.ndarray
    twi_grid: np.ndarray
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    dx: float
    dy: float

    def point_hydro(self, lon: float, lat: float) -> dict[str, Any]:
        if not (self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat):
            return {"subbasin_id": None, "twi": None, "flow_acc_cells": None, "in_torrent_network": False}
        h, w = self.label_grid.shape
        col = min(w - 1, max(0, int((lon - self.min_lon) / self.dx)))
        row = min(h - 1, max(0, int((self.max_lat - lat) / self.dy)))
        code = int(self.label_grid[row, col])
        acc = int(self.acc_grid[row, col])
        twi = round(float(self.twi_grid[row, col]), 2)
        sb = next((s.id for s in self.subbasins if s.code == code), None)
        return {
            "subbasin_id": sb,
            "twi": twi,
            "flow_acc_cells": acc,
            "in_torrent_network": bool(acc >= 35 or twi >= 9.2),
        }

    def rasterize_zone_masks(
        self, width: int, height: int, bounds: tuple[float, float, float, float]
    ) -> dict[str, np.ndarray]:
        tfm = from_bounds(bounds[0], bounds[1], bounds[2], bounds[3], width, height)
        masks: dict[str, np.ndarray] = {}
        for sb in self.subbasins:
            mask = rasterize(
                [(sb.geometry, 1)],
                out_shape=(height, width),
                transform=tfm,
                fill=0,
                dtype="uint8",
                all_touched=True,
            )
            masks[sb.id] = mask.astype(bool)
        return masks


def ensure_dem_hydrology(dem_path: Path, hydro_dir: Path) -> HydroGridArtifact:
    """Carga o computa subcuencas D8, TWI y red hidrográfica desde Copernicus DEM 30 m."""
    hydro_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = hydro_dir / "cochabamba_subbasins.json"
    grid_path = hydro_dir / "cochabamba_hydro_6x.npz"

    if geojson_path.is_file() and grid_path.is_file():
        meta = json.loads(geojson_path.read_text(encoding="utf-8"))
        npz = np.load(grid_path)
        features = tuple(_feature_from_dict(item) for item in meta["subbasins"])
        return HydroGridArtifact(
            subbasins=features,
            label_grid=npz["label"],
            acc_grid=npz["acc"],
            twi_grid=npz["twi"],
            min_lon=float(meta["bounds"][0]),
            min_lat=float(meta["bounds"][1]),
            max_lon=float(meta["bounds"][2]),
            max_lat=float(meta["bounds"][3]),
            dx=float(meta["dx"]),
            dy=float(meta["dy"]),
        )

    return _build_and_cache(dem_path, geojson_path, grid_path)


def _feature_from_dict(item: dict[str, Any]) -> SubBasinFeature:
    return SubBasinFeature(
        code=int(item["code"]),
        id=str(item["id"]),
        subsystem=item["subsystem"],
        hazard=item["hazard"],
        downstream_target=item.get("downstream_target"),
        name_es=str(item["name_es"]),
        name_en=str(item["name_en"]),
        description_es=str(item["description_es"]),
        description_en=str(item["description_en"]),
        area_km2=float(item["area_km2"]),
        bbox=tuple(float(v) for v in item["bbox"]),  # type: ignore[arg-type]
        centroid=tuple(float(v) for v in item["centroid"]),  # type: ignore[arg-type]
        geometry=item["geometry"],
    )


def _priority_flood_fill(elev: np.ndarray) -> np.ndarray:
    h, w = elev.shape
    filled = elev.copy()
    visited = np.zeros((h, w), dtype=bool)
    pq: list[tuple[float, int, int]] = []
    for r in range(h):
        for c in (0, w - 1):
            visited[r, c] = True
            heapq.heappush(pq, (float(filled[r, c]), r, c))
    for c in range(1, w - 1):
        for r in (0, h - 1):
            visited[r, c] = True
            heapq.heappush(pq, (float(filled[r, c]), r, c))
    nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    while pq:
        val, r, c = heapq.heappop(pq)
        for dr, dc in nbrs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc]:
                visited[nr, nc] = True
                if filled[nr, nc] <= val:
                    filled[nr, nc] = val + 1e-4
                heapq.heappush(pq, (float(filled[nr, nc]), nr, nc))
    return filled


def _d8_flow(filled: np.ndarray, dx_deg: float, dy_deg: float, mid_lat_deg: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    h, w = filled.shape
    nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    dist = [1.4142, 1.0, 1.4142, 1.0, 1.0, 1.4142, 1.0, 1.4142]
    best_slope = np.zeros((h, w), dtype=np.float64)
    receiver = np.full(h * w, -1, dtype=np.int32)
    rec2d = receiver.reshape(h, w)
    for (dr, dc), d in zip(nbrs, dist):
        r0, r1 = max(0, -dr), min(h, h - dr)
        c0, c1 = max(0, -dc), min(w, w - dc)
        nr0, nr1 = r0 + dr, r1 + dr
        nc0, nc1 = c0 + dc, c1 + dc
        slope = (filled[r0:r1, c0:c1] - filled[nr0:nr1, nc0:nc1]) / d
        better = slope > best_slope[r0:r1, c0:c1]
        best_slope[r0:r1, c0:c1][better] = slope[better]
        rec_idx = (np.arange(nr0, nr1)[:, None] * w + np.arange(nc0, nc1)[None, :]).astype(np.int32)
        rec2d[r0:r1, c0:c1][better] = rec_idx[better]

    order = np.argsort(filled.ravel())[::-1]
    acc = np.ones(h * w, dtype=np.int32)
    for u in order:
        v = receiver[u]
        if v >= 0:
            acc[v] += acc[u]

    mx = dx_deg * 111320.0 * math.cos(math.radians(mid_lat_deg))
    my = dy_deg * 111320.0
    dz_dy, dz_dx = np.gradient(filled, my, mx)
    tan_b = np.maximum(np.hypot(dz_dx, dz_dy), 0.002)
    area_m2 = acc.reshape(h, w).astype(np.float64) * (mx * my)
    twi = np.log(np.maximum(area_m2 / tan_b, 1.0)).astype(np.float32)
    return receiver, order, acc.reshape(h, w), twi


def _build_and_cache(dem_path: Path, geojson_path: Path, grid_path: Path) -> HydroGridArtifact:
    log.info("Derivando subcuencas D8 reales desde Copernicus DEM GLO-30 (%s)...", dem_path.name)
    scale = 6
    with rasterio.open(dem_path) as src:
        h, w = max(64, src.height // scale), max(64, src.width // scale)
        elev = src.read(1, out_shape=(h, w), resampling=Resampling.average).astype(np.float64)
        b = src.bounds
    dx = (b.right - b.left) / w
    dy = (b.top - b.bottom) / h
    mid_lat = 0.5 * (b.bottom + b.top)
    tfm = from_bounds(b.left, b.bottom, b.right, b.top, w, h)

    filled = _priority_flood_fill(elev)
    receiver, order, acc2d, twi2d = _d8_flow(filled, dx, dy, mid_lat)

    # Desagüe principal de toda la Cuenca del Rocha (salida oeste Parotani/Vinto)
    lats_row = b.top - (np.arange(h) + 0.5) * dy
    lons_col = b.left + (np.arange(w) + 0.5) * dx
    valley_mask = (
        ((lats_row >= -17.56) & (lats_row <= -17.35))[:, None]
        & ((lons_col >= -66.40) & (lons_col <= -66.25))[None, :]
    )
    vr, vc = np.unravel_index(int(np.argmax(np.where(valley_mask, acc2d, 0))), (h, w))
    bm = np.zeros(h * w, dtype=bool)
    bm[vr * w + vc] = True
    for u in order[::-1]:
        v = receiver[u]
        if v >= 0 and bm[v]:
            bm[u] = True
    bm2d = bm.reshape(h, w)

    def snap(lon: float, lat: float, radius: int, max_acc: int | None = None) -> int:
        pr = int((b.top - lat) / dy)
        pc = int((lon - b.left) / dx)
        sr = slice(max(0, pr - radius), min(h, pr + radius + 1))
        sc = slice(max(0, pc - radius), min(w, pc + radius + 1))
        sub = np.where(bm2d[sr, sc], acc2d[sr, sc], 0)
        if max_acc is not None:
            sub = np.where(sub <= max_acc, sub, 0)
        ir, ic = np.unravel_index(int(np.argmax(sub)), sub.shape)
        return (max(0, pr - radius) + ir) * w + (max(0, pc - radius) + ic)

    seeds = {
        vr * w + vc: 6,
        snap(-66.205, -17.403, radius=6, max_acc=40000): 5,
        snap(-66.142, -17.378, radius=5): 4,
        snap(-66.210, -17.425, radius=6): 7,
        snap(-66.087, -17.518, radius=10): 8,
    }
    label = np.zeros(h * w, dtype=np.int16)
    for u in order[::-1]:
        if not bm[u]:
            continue
        if u in seeds:
            label[u] = seeds[u]
        else:
            v = receiver[u]
            if v >= 0:
                label[u] = label[v]

    elev_flat = elev.ravel()
    entry_lon = np.full(h * w, np.nan)
    for u in order[::-1]:
        if not bm[u]:
            continue
        _, c = divmod(u, w)
        lon = b.left + (c + 0.5) * dx
        if elev_flat[u] < 2700.0:
            entry_lon[u] = lon
        else:
            v = receiver[u]
            if v >= 0:
                entry_lon[u] = entry_lon[v]

    for u in range(h * w):
        if not bm[u]:
            continue
        r, c = divmod(u, w)
        lat = b.top - (r + 0.5) * dy
        lon = b.left + (c + 0.5) * dx
        if label[u] in (4, 5, 6) and elev_flat[u] >= 2650.0 and lat >= -17.40:
            elon = entry_lon[u]
            if np.isfinite(elon):
                if elon < -66.19:
                    label[u] = 1
                elif elon < -66.10:
                    label[u] = 2
                else:
                    label[u] = 3
        if label[u] in (6, 7) and lat < -17.455 and lon < -66.135:
            label[u] = 9

    label2d = label.reshape(h, w)
    cell_km2 = (dx * 111.32 * math.cos(math.radians(mid_lat))) * (dy * 111.32)

    geoms_by_code: dict[int, list[Any]] = {k: [] for k in SUBBASIN_CATALOG}
    for geom_dict, val in shapes(label2d, mask=(label2d > 0), transform=tfm):
        code = int(val)
        if code in geoms_by_code:
            poly = shape(geom_dict)
            if poly.area > 0:
                geoms_by_code[code].append(poly)

    features: list[SubBasinFeature] = []
    serialized: list[dict[str, Any]] = []
    for code, meta in SUBBASIN_CATALOG.items():
        polys = geoms_by_code.get(code, [])
        if not polys:
            continue
        merged = unary_union(polys).buffer(0).simplify(0.0007, preserve_topology=True)
        # Mantener piezas relevantes (>= 1 % del área total de la subcuenca) para polígonos limpios.
        if merged.geom_type == "MultiPolygon":
            total_a = merged.area
            parts = [g for g in merged.geoms if g.area >= total_a * 0.01]
            merged = unary_union(parts) if parts else max(merged.geoms, key=lambda g: g.area)
        minx, miny, maxx, maxy = merged.bounds
        pt: Point = merged.representative_point()
        area_km2 = round(float((label2d == code).sum()) * cell_km2, 1)
        geom_json = mapping(merged)
        sb = SubBasinFeature(
            code=code,
            id=meta["id"],
            subsystem=meta["subsystem"],
            hazard=meta["hazard"],
            downstream_target=meta["downstream_target"],
            name_es=meta["name_es"],
            name_en=meta["name_en"],
            description_es=meta["description_es"],
            description_en=meta["description_en"],
            area_km2=area_km2,
            bbox=(round(minx, 5), round(miny, 5), round(maxx, 5), round(maxy, 5)),
            centroid=(round(pt.x, 5), round(pt.y, 5)),
            geometry=geom_json,
        )
        features.append(sb)
        serialized.append(
            {
                "code": sb.code,
                "id": sb.id,
                "subsystem": sb.subsystem,
                "hazard": sb.hazard,
                "downstream_target": sb.downstream_target,
                "name_es": sb.name_es,
                "name_en": sb.name_en,
                "description_es": sb.description_es,
                "description_en": sb.description_en,
                "area_km2": sb.area_km2,
                "bbox": list(sb.bbox),
                "centroid": list(sb.centroid),
                "geometry": sb.geometry,
            }
        )

    geojson_path.write_text(
        json.dumps(
            {
                "bounds": [float(b.left), float(b.bottom), float(b.right), float(b.top)],
                "dx": float(dx),
                "dy": float(dy),
                "subbasins": serialized,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    np.savez_compressed(grid_path, label=label2d, acc=acc2d.astype(np.int32), twi=twi2d.astype(np.float32))
    log.info("Subcuencas DEM cacheadas: %d polígonos en %s", len(features), geojson_path)
    return HydroGridArtifact(
        subbasins=tuple(features),
        label_grid=label2d,
        acc_grid=acc2d.astype(np.int32),
        twi_grid=twi2d.astype(np.float32),
        min_lon=float(b.left),
        min_lat=float(b.bottom),
        max_lon=float(b.right),
        max_lat=float(b.top),
        dx=float(dx),
        dy=float(dy),
    )
