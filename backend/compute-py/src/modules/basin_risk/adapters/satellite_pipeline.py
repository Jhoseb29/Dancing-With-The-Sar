"""Pipeline de procesamiento satelital acotado a la Cuenca de Cochabamba.

En lugar de superponer teselas crudas continentales de NASA GIBS encima del mapa:
1. Recorta estrictamente las imágenes de OPERA DSWx-S1, NISAR GCOV y GPM IMERG al
   polígono de la Cuenca de Cochabamba (cuando `scope="basin"`), eliminando franjas
   externas sobre Sudamérica.
2. Filtra píxeles opacos no hídricos (blanco/gris GIBS en OPERA) y ruido speckle (`3×3`).
3. Clasifica el radar banda L (NISAR GCOV) en categorías hidrológicas legibles
   alineadas con la física polarimétrica del ancla (`nisar-harness/lib/sar_physics.py`)
   y lee corridas HDF5 del ancla si existen en `nisar-harness/output/`.
4. Fusiona Copernicus DEM (30 m) + Cota 2750 m + lluvia NASA + agua real OPERA DSWx-S1
   en un producto único de Alerta Integrada (`integrated_alert`).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import httpx
import numpy as np
from PIL import Image

from config.settings import get_settings
from modules.basin_risk.adapters.copernicus_dem import DemGrid, _BLANK_PNG
from modules.basin_risk.adapters.dem_hydrology import HydroGridArtifact
from modules.basin_risk.domain.zones import BASIN_BBOX, COTA_URBANA_M

log = logging.getLogger("basin_risk.pipeline")

TileScope = Literal["basin", "all"]
_DAY_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")

_OPERA_TEMPLATE = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "OPERA_L3_Dynamic_Surface_Water_Extent-Sentinel-1/default/"
    "{day}/GoogleMapsCompatible_Level12/{z}/{y}/{x}.png"
)
_NISAR_TEMPLATE = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "NISAR_L2_Geocoded_Polarimetric_Covariance/default/"
    "{day}/GoogleMapsCompatible_Level13/{z}/{y}/{x}.png"
)
_IMERG_TEMPLATE = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "IMERG_Precipitation_Rate/default/"
    "{day}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png"
)


# ------------------------------------------------------------------ WebMercator & recorte
def tile_lonlat_axes(z: int, x: int, y: int, size: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """Centros de píxel (lon[size], lat[size]) EPSG:4326 de una tesela WebMercator."""
    n = float(1 << z)
    px = (np.arange(size, dtype=np.float64) + 0.5) / size
    lons = (x + px) / n * 360.0 - 180.0
    yt = y + px
    lats = np.degrees(np.arctan(np.sinh(math.pi * (1.0 - 2.0 * yt / n))))
    return lons, lats


def tile_intersects_bbox(z: int, x: int, y: int, bbox: tuple[float, float, float, float] = BASIN_BBOX) -> bool:
    n = float(1 << z)
    w_tile = x / n * 360.0 - 180.0
    e_tile = (x + 1) / n * 360.0 - 180.0
    n_tile = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    s_tile = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
    bw, bs, be, bn = bbox
    return not (e_tile < bw or w_tile > be or n_tile < bs or s_tile > bn)


def bbox_pixel_mask(z: int, x: int, y: int, bbox: tuple[float, float, float, float] = BASIN_BBOX) -> np.ndarray:
    lons, lats = tile_lonlat_axes(z, x, y)
    bw, bs, be, bn = bbox
    in_lon = (lons >= bw) & (lons <= be)
    in_lat = (lats >= bs) & (lats <= bn)
    return in_lat[:, None] & in_lon[None, :]


def _boxcar3(arr: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Media móvil 3×3 NaN-aware en 2D para reducir moteado/speckle sin librería externa."""
    vp = np.pad(valid.astype(np.float32), 1, mode="edge")
    ap = np.pad(np.where(valid, arr, 0.0).astype(np.float32), 1, mode="edge")
    num = np.zeros_like(arr, dtype=np.float32)
    den = np.zeros_like(arr, dtype=np.float32)
    h, w = arr.shape
    for dy in range(3):
        for dx in range(3):
            num += ap[dy : dy + h, dx : dx + w]
            den += vp[dy : dy + h, dx : dx + w]
    return np.where(den > 0, num / np.maximum(den, 1.0), 0.0)


# ------------------------------------------------------------------ Procesadores por píxel
def filter_opera_water_png(raw: bytes, mask: np.ndarray | None = None) -> bytes:
    """Limpia fondo blanco/gris GIBS y ruido aislado de 1 píxel en OPERA DSWx-S1."""
    with Image.open(io.BytesIO(raw)) as img:
        rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8).copy()

    r = rgba[..., 0].astype(np.int16)
    g = rgba[..., 1].astype(np.int16)
    b = rgba[..., 2].astype(np.int16)
    chroma = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    is_water = (rgba[..., 3] > 0) & (chroma > 20)
    if mask is not None:
        is_water &= mask

    # Elimina motas aisladas de 1 píxel (exige ≥ 1 vecino agua en ventana 3×3)
    vp = np.pad(is_water.astype(np.uint8), 1, mode="constant")
    neighbors = (
        vp[:-2, :-2] + vp[:-2, 1:-1] + vp[:-2, 2:]
        + vp[1:-1, :-2] + vp[1:-1, 2:]
        + vp[2:, :-2] + vp[2:, 1:-1] + vp[2:, 2:]
    )
    keep = is_water & (neighbors >= 1)
    if not bool(np.any(keep)):
        return _BLANK_PNG

    rgba[~keep, 3] = 0
    out = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(out, format="PNG")
    return out.getvalue()


def _classify_nisar_rgb(rgba: np.ndarray, mask: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Reclasifica GIBS NISAR RGB tras suavizado anti-speckle 3×3.

    Devuelve (out_rgba, class_idx): 0=agua/suelo_liso, 1=vegetacion_cross_pol, 2=urbano_roca, 3=suelo_neutro, -1=fuera.
    """
    valid = rgba[..., 3] > 0
    if mask is not None:
        valid &= mask
    classes = np.full(valid.shape, -1, dtype=np.int8)
    out = np.zeros((*valid.shape, 4), dtype=np.uint8)
    if not bool(np.any(valid)):
        return out, classes

    r = _boxcar3(rgba[..., 0], valid)
    g = _boxcar3(rgba[..., 1], valid)

    is_specular = valid & (r < 78.0) & (g < 84.0)
    is_canopy = valid & ~is_specular & ((g - r) >= 16.0) & (g >= 105.0)
    is_urban_rough = valid & ~is_specular & ~is_canopy & (r >= 152.0) & ((r - g) >= 16.0)
    is_bare = valid & ~is_specular & ~is_canopy & ~is_urban_rough

    classes[is_bare] = 3
    classes[is_canopy] = 1
    classes[is_urban_rough] = 2
    classes[is_specular] = 0

    out[is_bare] = (176, 164, 146, 48)       # terreno seco neutro casi transparente
    out[is_canopy] = (54, 168, 108, 128)     # vegetación / ladera húmeda Tunari
    out[is_urban_rough] = (232, 134, 58, 160)  # urbano / doble rebote en valle y borde
    out[is_specular] = (32, 152, 238, 224)   # agua / superficie lisa saturada
    return out, classes


def process_nisar_png(raw: bytes, mask: np.ndarray | None = None) -> bytes:
    """Convierte GIBS NISAR neón en una lectura hidrológica limpia acotada al área de estudio."""
    with Image.open(io.BytesIO(raw)) as img:
        rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
    out, _ = _classify_nisar_rgb(rgba, mask=mask)
    if not bool(np.any(out[..., 3] > 0)):
        return _BLANK_PNG
    buf = io.BytesIO()
    Image.fromarray(out, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def process_imerg_rgba(rgba: np.ndarray, mask: np.ndarray | None = None) -> bytes:
    """Aplica máscara de cuenca y atenúa opacidad de lluvia IMERG."""
    out = rgba.copy()
    if mask is not None:
        out[~mask, 3] = 0
    has_rain = out[..., 3] > 0
    if not bool(np.any(has_rain)):
        return _BLANK_PNG
    out[has_rain, 3] = np.clip(out[has_rain, 3].astype(np.float32) * 0.72, 0, 190).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(out, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def compute_sar_change_png(
    before_raw: bytes,
    after_raw: bytes,
    mask: np.ndarray | None = None,
    steep_mask: np.ndarray | None = None,
) -> bytes:
    """Calcula cambio radiométrico SAR (antes vs. después) mitigando escorzo >= 25°."""
    with Image.open(io.BytesIO(before_raw)) as ib, Image.open(io.BytesIO(after_raw)) as ia:
        b_rgba = np.asarray(ib.convert("RGBA"), dtype=np.uint8)
        a_rgba = np.asarray(ia.convert("RGBA"), dtype=np.uint8)

    overlap = (b_rgba[..., 3] > 0) & (a_rgba[..., 3] > 0)
    if mask is not None:
        overlap &= mask
    if not bool(np.any(overlap)):
        return _BLANK_PNG

    b_luma = _boxcar3(
        0.3 * b_rgba[..., 0] + 0.59 * b_rgba[..., 1] + 0.11 * b_rgba[..., 2], overlap
    )
    a_luma = _boxcar3(
        0.3 * a_rgba[..., 0] + 0.59 * a_rgba[..., 1] + 0.11 * a_rgba[..., 2], overlap
    )
    b_pol = _boxcar3(b_rgba[..., 2].astype(np.float32) - b_rgba[..., 0].astype(np.float32), overlap)
    a_pol = _boxcar3(a_rgba[..., 2].astype(np.float32) - a_rgba[..., 0].astype(np.float32), overlap)

    dluma = a_luma - b_luma
    dpol = a_pol - b_pol

    # Agua/saturación nueva: caída especular o aumento fuerte de respuesta azul/especular.
    wet_gain = overlap & ((dluma <= -24.0) | (dpol >= 20.0))
    # Disturbio / doble rebote / aumento de humedad en suelo o vegetación.
    rough_gain = overlap & ~wet_gain & ((dluma >= 24.0) | (np.abs(dpol) >= 26.0))

    rgba = np.zeros((*overlap.shape, 4), dtype=np.uint8)
    rgba[wet_gain] = (0, 212, 255, 220)
    rgba[rough_gain] = (245, 158, 11, 200)

    if steep_mask is not None:
        caution = steep_mask & (wet_gain | rough_gain)
        if bool(np.any(caution)):
            # Atenúa y distingue zonas con pendiente >= 25° donde el escorzo SAR resta certeza.
            rgba[caution] = (192, 132, 252, 84)

    if not bool(np.any(rgba[..., 3] > 0)):
        return _BLANK_PNG
    out = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(out, format="PNG")
    return out.getvalue()


def compute_opera_delta_png(
    before_png: bytes,
    after_png: bytes,
    mask: np.ndarray | None = None,
    steep_mask: np.ndarray | None = None,
) -> bytes:
    """Diferencia de agua superficial OPERA DSWx-S1 entre fecha base y fecha reciente."""
    if before_png == _BLANK_PNG and after_png == _BLANK_PNG:
        return _BLANK_PNG
    a_arr = (
        np.asarray(Image.open(io.BytesIO(after_png)).convert("RGBA"), dtype=np.uint8)
        if after_png != _BLANK_PNG
        else None
    )
    b_arr = (
        np.asarray(Image.open(io.BytesIO(before_png)).convert("RGBA"), dtype=np.uint8)
        if before_png != _BLANK_PNG
        else None
    )
    h, w = a_arr.shape[:2] if a_arr is not None else b_arr.shape[:2]  # type: ignore[union-attr]
    if b_arr is None:
        b_arr = np.zeros((h, w, 4), dtype=np.uint8)
    if a_arr is None:
        a_arr = np.zeros((h, w, 4), dtype=np.uint8)

    b_w = b_arr[..., 3] > 0
    a_w = a_arr[..., 3] > 0
    if mask is not None:
        b_w &= mask
        a_w &= mask

    expanded = a_w & ~b_w
    receded = b_w & ~a_w
    permanent = a_w & b_w

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[permanent] = (37, 99, 235, 120)  # espejo permanente atenuado
    rgba[expanded] = (0, 224, 255, 235)   # nueva expansión/anomalía
    rgba[receded] = (245, 158, 11, 200)   # retroceso / déficit superficial

    if steep_mask is not None:
        caution = steep_mask & (expanded | receded)
        rgba[caution] = (192, 132, 252, 84)

    if not bool(np.any(rgba[..., 3] > 0)):
        return _BLANK_PNG
    out = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(out, format="PNG")
    return out.getvalue()


# ------------------------------------------------------------------ Orquestador de teselas y caché
class BasinSatellitePipeline:
    """Descarga bajo demanda, procesa y cachea teselas satelitales + estadísticas de Cochabamba."""

    def __init__(self, cache_root: Path, harness_output_dir: Path, missing_ttl_s: float = 300.0) -> None:
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.harness_output_dir = harness_output_dir
        self.missing_ttl_s = missing_ttl_s
        self._missing: dict[str, float] = {}

    async def get_opera_tile(self, day: str, z: int, x: int, y: int, scope: TileScope = "basin") -> bytes:
        if not _DAY_RE.match(day) or not (0 <= z <= 12) or not self._in_bounds(z, x, y):
            return _BLANK_PNG
        if scope == "basin" and not tile_intersects_bbox(z, x, y, BASIN_BBOX):
            return _BLANK_PNG

        cache_file = self.cache_root / "opera" / f"{scope}_{day}_{z}_{x}_{y}.png"
        if cache_file.is_file():
            return cache_file.read_bytes()

        raw = await self._fetch_raw(_OPERA_TEMPLATE.format(day=day, z=z, x=x, y=y), f"opera:{day}:{z}:{x}:{y}")
        if raw is None:
            return _BLANK_PNG

        mask = bbox_pixel_mask(z, x, y, BASIN_BBOX) if scope == "basin" else None
        processed = filter_opera_water_png(raw, mask=mask)
        self._write_cache(cache_file, processed)
        return processed

    async def get_nisar_tile(self, day: str, z: int, x: int, y: int, scope: TileScope = "basin") -> bytes:
        if not _DAY_RE.match(day) or not (0 <= z <= 13) or not self._in_bounds(z, x, y):
            return _BLANK_PNG
        if scope == "basin" and not tile_intersects_bbox(z, x, y, BASIN_BBOX):
            return _BLANK_PNG

        cache_file = self.cache_root / "nisar" / f"{scope}_{day}_{z}_{x}_{y}.png"
        if cache_file.is_file():
            return cache_file.read_bytes()

        raw = await self._fetch_raw(_NISAR_TEMPLATE.format(day=day, z=z, x=x, y=y), f"nisar:{day}:{z}:{x}:{y}")
        if raw is None:
            return _BLANK_PNG

        mask = bbox_pixel_mask(z, x, y, BASIN_BBOX) if scope == "basin" else None
        processed = process_nisar_png(raw, mask=mask)
        self._write_cache(cache_file, processed)
        return processed

    async def get_imerg_tile(self, day: str, z: int, x: int, y: int, scope: TileScope = "basin") -> bytes:
        if not _DAY_RE.match(day) or not (0 <= z <= 12) or not self._in_bounds(z, x, y):
            return _BLANK_PNG
        if scope == "basin" and not tile_intersects_bbox(z, x, y, BASIN_BBOX):
            return _BLANK_PNG

        cache_file = self.cache_root / "imerg" / f"{scope}_{day}_{z}_{x}_{y}.png"
        if cache_file.is_file():
            return cache_file.read_bytes()

        # IMERG en GIBS llega hasta z=6; para z > 6 remuestreamos bilinealmente la tesela padre.
        src_z = min(z, 6)
        shift = z - src_z
        sx, sy = x >> shift, y >> shift
        raw = await self._fetch_raw(_IMERG_TEMPLATE.format(day=day, z=src_z, x=sx, y=sy), f"imerg:{day}:{src_z}:{sx}:{sy}")
        if raw is None:
            return _BLANK_PNG

        with Image.open(io.BytesIO(raw)) as img:
            base = img.convert("RGBA")
            if shift > 0:
                span = 256 >> min(shift, 7)
                if span < 1:
                    span = 1
                sub_x = (x - (sx << shift)) * 256 / (1 << shift)
                sub_y = (y - (sy << shift)) * 256 / (1 << shift)
                sub_w = 256.0 / (1 << shift)
                crop = base.crop((sub_x, sub_y, sub_x + sub_w, sub_y + sub_w)).resize((256, 256), Image.Resampling.BILINEAR)
                rgba = np.asarray(crop, dtype=np.uint8)
            else:
                rgba = np.asarray(base, dtype=np.uint8)

        mask = bbox_pixel_mask(z, x, y, BASIN_BBOX) if scope == "basin" else None
        processed = process_imerg_rgba(rgba, mask=mask)
        self._write_cache(cache_file, processed)
        return processed

    async def get_sar_change_tile(
        self,
        before_day: str,
        after_day: str,
        z: int,
        x: int,
        y: int,
        dem_grid: DemGrid | None = None,
        sensor: Literal["auto", "nisar", "opera"] = "auto",
    ) -> bytes:
        """Compara radar antes vs. después en cuenca aplicando máscara DEM >= 25°."""
        if not (_DAY_RE.match(before_day) and _DAY_RE.match(after_day)) or not (0 <= z <= 13) or not self._in_bounds(z, x, y):
            return _BLANK_PNG
        if not tile_intersects_bbox(z, x, y, BASIN_BBOX):
            return _BLANK_PNG

        cache_file = self.cache_root / "sar_change" / f"{sensor}_{before_day}_{after_day}_{z}_{x}_{y}.png"
        if cache_file.is_file():
            return cache_file.read_bytes()

        mask = bbox_pixel_mask(z, x, y, BASIN_BBOX)
        steep_mask: np.ndarray | None = None
        if dem_grid is not None:
            lons, lats = tile_lonlat_axes(z, x, y)
            cols = np.clip(((lons - dem_grid.min_lon) / dem_grid.dx).astype(np.int32), 0, dem_grid.width - 1)
            rows = np.clip(((dem_grid.max_lat - lats) / dem_grid.dy).astype(np.int32), 0, dem_grid.height - 1)
            rr, cc = np.meshgrid(rows, cols, indexing="ij")
            steep_mask = dem_grid.slope_deg[rr, cc] >= 25.0

        result = _BLANK_PNG
        if sensor in ("auto", "nisar"):
            raw_b, raw_a = await asyncio.gather(
                self._fetch_raw(_NISAR_TEMPLATE.format(day=before_day, z=z, x=x, y=y), f"nisar:{before_day}:{z}:{x}:{y}"),
                self._fetch_raw(_NISAR_TEMPLATE.format(day=after_day, z=z, x=x, y=y), f"nisar:{after_day}:{z}:{x}:{y}"),
            )
            if raw_b is not None and raw_a is not None:
                result = compute_sar_change_png(raw_b, raw_a, mask=mask, steep_mask=steep_mask)

        if result == _BLANK_PNG and sensor in ("auto", "opera") and z <= 12:
            b_op, a_op = await asyncio.gather(
                self.get_opera_tile(before_day, z, x, y, scope="basin"),
                self.get_opera_tile(after_day, z, x, y, scope="basin"),
            )
            result = compute_opera_delta_png(b_op, a_op, mask=mask, steep_mask=steep_mask)

        self._write_cache(cache_file, result)
        return result

    # ------------------------------------------------------------------ Fusión multi-sensor 30 m
    async def render_integrated_alert_tile(
        self,
        dem_grid: DemGrid,
        rain_factor: float,
        z: int,
        x: int,
        y: int,
        opera_day: str | None,
    ) -> bytes:
        """Fusiona DEM 30m (torrenteras > 2750m + Cota 2750) + lluvia + agua real OPERA DSWx-S1."""
        if not tile_intersects_bbox(z, x, y, BASIN_BBOX):
            return _BLANK_PNG

        lons, lats = tile_lonlat_axes(z, x, y)
        mask = bbox_pixel_mask(z, x, y, BASIN_BBOX)

        # Muestreo rápido sobre grilla Copernicus DEM (1 arcsec)
        cols = np.clip(((lons - dem_grid.min_lon) / dem_grid.dx).astype(np.int32), 0, dem_grid.width - 1)
        rows = np.clip(((dem_grid.max_lat - lats) / dem_grid.dy).astype(np.int32), 0, dem_grid.height - 1)
        rr, cc = np.meshgrid(rows, cols, indexing="ij")

        elev = dem_grid.elevation[rr, cc]
        slope = dem_grid.slope_deg[rr, cc]
        tpi = dem_grid.tpi_m[rr, cc]

        valid = mask & np.isfinite(elev) & np.isfinite(slope)
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        if not bool(np.any(valid)):
            return _BLANK_PNG

        rf = float(np.clip(rain_factor, 0.25, 1.0))

        # 1) Llanura aluvial inundable bajo 2750 m (depresiones suaves donde converge escurrimiento)
        valley_flood = valid & (elev < COTA_URBANA_M) & (slope <= 4.5) & (tpi >= 1.4)
        if bool(np.any(valley_flood)):
            intensity = np.clip((tpi[valley_flood] - 1.2) / 5.0 * (0.5 + 0.5 * rf), 0.25, 1.0)
            rgba[valley_flood, 0] = 44
            rgba[valley_flood, 1] = 152
            rgba[valley_flood, 2] = 238
            rgba[valley_flood, 3] = (85 + 95 * intensity).astype(np.uint8)

        # 2) Quebradas y torrenteras críticas de ladera (> 2720 m o pendiente >= 16°)
        torrent_risk = (
            valid
            & (elev >= COTA_URBANA_M - 30.0)
            & (((slope >= 18.0) & (tpi >= 1.6)) | (slope >= 27.0))
        )
        if bool(np.any(torrent_risk)):
            score = np.clip(
                ((slope[torrent_risk] - 16.0) / 18.0) * 0.65 + np.clip(tpi[torrent_risk], 0.0, 8.0) / 8.0 * 0.35,
                0.0,
                1.0,
            ) * (0.55 + 0.45 * rf)
            # Naranja cálido -> rojo urgente según severidad física
            rgba[torrent_risk, 0] = np.clip(242 - 8 * score, 220, 248).astype(np.uint8)
            rgba[torrent_risk, 1] = np.clip(175 - 125 * score, 48, 185).astype(np.uint8)
            rgba[torrent_risk, 2] = 46
            rgba[torrent_risk, 3] = np.clip(115 + 115 * score, 100, 232).astype(np.uint8)

        # 3) Contorno físico operativo Cota 2750 m
        cota_line = valid & (np.abs(elev - COTA_URBANA_M) <= 8.0)
        if bool(np.any(cota_line)):
            rgba[cota_line] = (128, 242, 174, 225)

        # 4) Fusión directa con detecciones reales OPERA DSWx-S1 (Sentinel-1 30 m)
        if opera_day and _DAY_RE.match(opera_day) and z >= 7:
            oz = min(z, 12)
            oshift = z - oz
            ox, oy = x >> oshift, y >> oshift
            opera_bytes = await self.get_opera_tile(opera_day, oz, ox, oy, scope="basin")
            if opera_bytes != _BLANK_PNG:
                with Image.open(io.BytesIO(opera_bytes)) as img:
                    ob = img.convert("RGBA")
                    if oshift > 0:
                        sx = (x - (ox << oshift)) * 256 / (1 << oshift)
                        sy = (y - (oy << oshift)) * 256 / (1 << oshift)
                        sw = 256.0 / (1 << oshift)
                        ob = ob.crop((sx, sy, sx + sw, sy + sw)).resize((256, 256), Image.Resampling.NEAREST)
                    oarr = np.asarray(ob, dtype=np.uint8)
                has_w = mask & (oarr[..., 3] > 0)
                if bool(np.any(has_w)):
                    is_veg_wet = has_w & (oarr[..., 1] > oarr[..., 2])
                    is_open_w = has_w & ~is_veg_wet
                    rgba[is_veg_wet] = (24, 212, 164, 215)
                    rgba[is_open_w] = (0, 224, 255, 240)

        if not bool(np.any(rgba[..., 3] > 0)):
            return _BLANK_PNG
        out = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(out, format="PNG")
        return out.getvalue()

    # ------------------------------------------------------------------ Cuantificación real para /overview
    async def summarize_basin_satellites(
        self,
        opera_day: str | None,
        nisar_day: str | None,
        hydro: HydroGridArtifact | None = None,
        baseline_opera_day: str | None = None,
    ) -> dict[str, Any]:
        """Cuantifica agua OPERA (km² por polígono de subcuenca), clases NISAR y corridas HDF5 del ancla."""
        opera_task = (
            self._quantify_opera(opera_day, hydro=hydro, baseline_day=baseline_opera_day)
            if opera_day
            else asyncio.sleep(0, result=None)
        )
        nisar_task = self._quantify_nisar(nisar_day) if nisar_day else asyncio.sleep(0, result=None)
        opera_stats, nisar_stats = await asyncio.gather(opera_task, nisar_task)
        anchor = self._inspect_anchor_outputs()
        return {
            "scope": "Cuenca de Cochabamba (recorte estricto)",
            "opera_dswx": opera_stats,
            "nisar_basin": nisar_stats,
            "anchor_harness": anchor,
        }

    async def _quantify_opera(
        self,
        day: str,
        hydro: HydroGridArtifact | None = None,
        baseline_day: str | None = None,
    ) -> dict[str, Any]:
        z = 10
        xs, ys = range(322, 326), range(561, 564)
        coords = [(x, y) for y in ys for x in xs]
        curr_task = asyncio.gather(*(self.get_opera_tile(day, z, x, y, scope="basin") for x, y in coords))
        has_base = bool(baseline_day and baseline_day != day)
        base_task = (
            asyncio.gather(*(self.get_opera_tile(baseline_day, z, x, y, scope="basin") for x, y in coords))  # type: ignore[arg-type]
            if has_base
            else asyncio.sleep(0, result=[_BLANK_PNG] * len(coords))
        )
        tiles, base_tiles = await asyncio.gather(curr_task, base_task)

        px_size_km = (40075.017 * math.cos(math.radians(17.45))) / (1024.0 * 256.0)
        px_area_km2 = px_size_km * px_size_km

        open_px = 0
        veg_px = 0
        subbasin_ids = [s.id for s in hydro.subbasins] if hydro else []
        zone_curr_px: dict[str, int] = {sid: 0 for sid in subbasin_ids}
        zone_base_px: dict[str, int] = {sid: 0 for sid in subbasin_ids}
        zone_anom_px: dict[str, int] = {sid: 0 for sid in subbasin_ids}

        n = float(1 << z)
        for (tx, ty), raw, braw in zip(coords, tiles, base_tiles):
            if raw == _BLANK_PNG and braw == _BLANK_PNG:
                continue
            arr = (
                np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"), dtype=np.uint8)
                if raw != _BLANK_PNG
                else np.zeros((256, 256, 4), dtype=np.uint8)
            )
            barr = (
                np.asarray(Image.open(io.BytesIO(braw)).convert("RGBA"), dtype=np.uint8)
                if braw != _BLANK_PNG
                else np.zeros((256, 256, 4), dtype=np.uint8)
            )
            valid = arr[..., 3] > 0
            bvalid = barr[..., 3] > 0
            if bool(np.any(valid)):
                veg_mask = valid & (arr[..., 1] > arr[..., 2])
                open_mask = valid & ~veg_mask
                open_px += int(open_mask.sum())
                veg_px += int(veg_mask.sum())

            if hydro:
                w_t = tx / n * 360.0 - 180.0
                e_t = (tx + 1) / n * 360.0 - 180.0
                n_t = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ty / n))))
                s_t = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (ty + 1) / n))))
                poly_masks = hydro.rasterize_zone_masks(256, 256, (w_t, s_t, e_t, n_t))
                anom_mask = (valid & ~bvalid) if has_base else (valid & (arr[..., 1] > arr[..., 2]))
                for sid, zmask in poly_masks.items():
                    zone_curr_px[sid] += int((valid & zmask).sum())
                    zone_base_px[sid] += int((bvalid & zmask).sum())
                    zone_anom_px[sid] += int((anom_mask & zmask).sum())

        by_zone_surface: dict[str, dict[str, float]] = {}
        for sid in subbasin_ids:
            curr_km2 = round(zone_curr_px[sid] * px_area_km2, 3)
            base_km2 = round(zone_base_px[sid] * px_area_km2, 3) if has_base else round(zone_curr_px[sid] * px_area_km2, 3)
            anom_km2 = round(zone_anom_px[sid] * px_area_km2, 3)
            by_zone_surface[sid] = {
                "opera_water_km2": curr_km2,
                "baseline_dry_km2": base_km2,
                "water_anomaly_km2": anom_km2,
            }

        return {
            "date": day,
            "baseline_date": baseline_day if has_base else None,
            "open_water_km2": round(open_px * px_area_km2, 2),
            "inundated_veg_km2": round(veg_px * px_area_km2, 2),
            "total_water_km2": round((open_px + veg_px) * px_area_km2, 2),
            "by_zone_km2": {sid: v["opera_water_km2"] for sid, v in by_zone_surface.items()},
            "by_zone_surface": by_zone_surface,
        }

    async def _quantify_nisar(self, day: str) -> dict[str, Any]:
        z = 9
        coords = [(x, y) for y in (280, 281) for x in (161, 162)]
        tiles = await asyncio.gather(*(self.get_nisar_tile(day, z, x, y, scope="basin") for x, y in coords))

        total_basin_px = 0
        covered_px = 0
        specular_px = 0
        canopy_px = 0
        urban_px = 0

        for (tx, ty), raw in zip(coords, tiles):
            bmask = bbox_pixel_mask(z, tx, ty, BASIN_BBOX)
            total_basin_px += int(bmask.sum())
            if raw == _BLANK_PNG:
                continue
            with Image.open(io.BytesIO(raw)) as img:
                arr = np.asarray(img.convert("RGBA"), dtype=np.uint8)
            vis = bmask & (arr[..., 3] > 0)
            covered_px += int(vis.sum())
            # Coincide exactamente con los 4 colores de _classify_nisar_rgb
            specular_px += int((vis & (arr[..., 2] >= 200)).sum())
            canopy_px += int((vis & (arr[..., 0] <= 90) & (arr[..., 1] >= 150)).sum())
            urban_px += int((vis & (arr[..., 0] >= 200) & (arr[..., 1] <= 150)).sum())

        cov_pct = round(100.0 * covered_px / max(total_basin_px, 1), 1)
        denom = max(covered_px, 1)
        return {
            "date": day,
            "basin_coverage_pct": cov_pct,
            "classes_pct": {
                "specular_water": round(100.0 * specular_px / denom, 1),
                "vegetation_canopy": round(100.0 * canopy_px / denom, 1),
                "urban_double_bounce": round(100.0 * urban_px / denom, 1),
                "bare_soil": round(100.0 * max(covered_px - specular_px - canopy_px - urban_px, 0) / denom, 1),
            },
        }

    def _inspect_anchor_outputs(self) -> dict[str, Any]:
        """Revisa si el ancla `nisar-harness` tiene corridas HDF5 cacheadas sobre Cochabamba."""
        if not self.harness_output_dir.is_dir():
            return {"status": "standby", "runs_count": 0, "latest_metrics": None}

        metrics_files = sorted(
            self.harness_output_dir.glob("*/granules/*/curated_metrics.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for mf in metrics_files:
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                bounds = data.get("spatial_reference", {}).get("analyzed_bounds_lonlat")
                if not bounds or len(bounds) != 4:
                    continue
                w, s, e, n = bounds
                bw, bs, be, bn = BASIN_BBOX
                if not (e < bw or w > be or n < bs or s > bn):
                    return {
                        "status": "ready",
                        "runs_count": len(metrics_files),
                        "latest_metrics": {
                            "granule_id": data.get("granule_id"),
                            "date": (data.get("acquisition", {}).get("start_time") or "")[:10],
                            "classes_pct": data.get("physical_scattering_breakdown"),
                            "polarimetric_indices": data.get("polarimetric_indices"),
                        },
                    }
            except Exception:
                continue
        return {"status": "standby", "runs_count": len(metrics_files), "latest_metrics": None}

    async def _fetch_raw(self, url: str, key: str) -> bytes | None:
        miss = self._missing.get(key)
        if miss is not None and (time.monotonic() - miss) < self.missing_ttl_s:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or not resp.content:
            if len(self._missing) > 4096:
                self._missing.clear()
            self._missing[key] = time.monotonic()
            return None
        return resp.content

    @staticmethod
    def _in_bounds(z: int, x: int, y: int) -> bool:
        lim = 1 << z
        return 0 <= x < lim and 0 <= y < lim

    @staticmethod
    def _write_cache(path: Path, data: bytes) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError:
            pass


@lru_cache
def get_satellite_pipeline() -> BasinSatellitePipeline:
    """Instancia única del pipeline satelital acotado a la Cuenca de Cochabamba."""
    settings = get_settings()
    return BasinSatellitePipeline(
        cache_root=settings.data_dir / "raw" / "basin_tiles",
        harness_output_dir=settings.harness_output_dir,
    )

