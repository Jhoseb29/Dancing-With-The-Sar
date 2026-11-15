"""Copernicus DEM GLO-30 real (AWS Open Data público, sin credenciales).

Descarga por ventana (/vsicurl/) únicamente el área de la cuenca de Cochabamba
desde los COGs públicos `S18_00_W067_00` y `S18_00_W066_00`, guarda un GeoTIFF
local comprimido en `data/processed/cog/` y genera:
- Estadísticas reales de elevación, pendiente y Cota 2750 por zona o punto.
- Teselas PNG EPSG:3857 bajo demanda: `terrain` (Terrain-RGB para 3D MapLibre),
  `slope` (pendiente en grados) y `susceptibility` (pendiente + concavidad TPI + lluvia).
"""

from __future__ import annotations

import io
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds

from modules.basin_risk.adapters.dem_hydrology import HydroGridArtifact, ensure_dem_hydrology
from modules.basin_risk.domain.zones import BASIN_BBOX, COTA_URBANA_M

log = logging.getLogger("basin_risk.dem")

COPERNICUS_URLS = (
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_S18_00_W067_00_DEM/Copernicus_DSM_COG_10_S18_00_W067_00_DEM.tif",
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_S18_00_W066_00_DEM/Copernicus_DSM_COG_10_S18_00_W066_00_DEM.tif",
)

# Margen ligero para derivadas limpias en los bordes de la cuenca
_CLIP_BBOX = (
    BASIN_BBOX[0] - 0.01,
    BASIN_BBOX[1] - 0.01,
    BASIN_BBOX[2] + 0.01,
    BASIN_BBOX[3] + 0.01,
)


def _blank_tile() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


_BLANK_PNG = _blank_tile()


def _boxcar_mean(arr: np.ndarray, radius: int = 4) -> np.ndarray:
    """Media móvil NaN-aware con imagen integral (O(N)) para calcular TPI topográfico."""
    size = radius * 2 + 1
    valid = np.isfinite(arr)
    vals = np.pad(np.where(valid, arr, 0.0).astype(np.float64), radius, mode="edge")
    cnts = np.pad(valid.astype(np.float64), radius, mode="edge")

    def wsum(a: np.ndarray) -> np.ndarray:
        c = np.pad(a.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        return c[size:, size:] - c[:-size, size:] - c[size:, :-size] + c[:-size, :-size]

    s, n = wsum(vals), wsum(cnts)
    return np.where(n > 0, s / np.maximum(n, 1.0), arr).astype(np.float32)


@dataclass
class DemGrid:
    elevation: np.ndarray
    slope_deg: np.ndarray
    tpi_m: np.ndarray
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    dx: float
    dy: float

    @property
    def height(self) -> int:
        return int(self.elevation.shape[0])

    @property
    def width(self) -> int:
        return int(self.elevation.shape[1])


class CopernicusDemProvider:
    def __init__(self, cog_path: Path, hydro_dir: Path | None = None) -> None:
        self._cog_path = cog_path
        self._hydro_dir = hydro_dir or (cog_path.parent.parent / "hydro")
        self._lock = threading.Lock()
        self._grid: DemGrid | None = None
        self._hydro: HydroGridArtifact | None = None
        self._poly_stats_cache: dict[str, dict[str, float]] | None = None

    def ensure_hydrology(self) -> HydroGridArtifact:
        if self._hydro is not None:
            return self._hydro
        self.ensure_loaded()
        with self._lock:
            if self._hydro is None:
                self._hydro = ensure_dem_hydrology(self._cog_path, self._hydro_dir)
            return self._hydro

    def all_polygon_stats(self) -> dict[str, dict[str, float]]:
        """Calcula y cachea estadísticas 30 m exactas sobre el polígono real de cada subcuenca."""
        if self._poly_stats_cache is not None:
            return self._poly_stats_cache
        g = self.ensure_loaded()
        hydro = self.ensure_hydrology()
        bounds = (g.min_lon, g.min_lat, g.max_lon, g.max_lat)
        tfm = from_bounds(*bounds, g.width, g.height)
        shapes_iter = [(sb.geometry, sb.code) for sb in hydro.subbasins]
        labels = rasterize(
            shapes_iter,
            out_shape=(g.height, g.width),
            transform=tfm,
            fill=0,
            dtype="uint8",
            all_touched=False,
        )
        valid_dem = np.isfinite(g.elevation) & np.isfinite(g.slope_deg)
        stats: dict[str, dict[str, float]] = {}
        for sb in hydro.subbasins:
            mask = (labels == sb.code) & valid_dem
            if not mask.any():
                stats[sb.id] = self.zone_stats(sb.bbox)
                continue
            ev = g.elevation[mask]
            sl = g.slope_deg[mask]
            hydro_mask = hydro.label_grid == sb.code
            twi_vals = hydro.twi_grid[hydro_mask] if hydro_mask.any() else np.array([0.0])
            acc_vals = hydro.acc_grid[hydro_mask] if hydro_mask.any() else np.array([0])
            torrent_pct = float(100.0 * ((acc_vals >= 35) | (twi_vals >= 9.2)).mean())
            stats[sb.id] = {
                "elevation_min_m": round(float(ev.min()), 1),
                "elevation_mean_m": round(float(ev.mean()), 1),
                "elevation_max_m": round(float(ev.max()), 1),
                "slope_mean_deg": round(float(sl.mean()), 1),
                "slope_p90_deg": round(float(np.percentile(sl, 90)), 1),
                "steep_pct_gt20": round(float(100.0 * (sl >= 20.0).mean()), 1),
                "steep_pct_gt25": round(float(100.0 * (sl >= 25.0).mean()), 1),
                "steep_pct_gt30": round(float(100.0 * (sl >= 30.0).mean()), 1),
                "low_slope_pct_lt5": round(float(100.0 * (sl < 5.0).mean()), 1),
                "above_2750_pct": round(float(100.0 * (ev >= COTA_URBANA_M).mean()), 1),
                "twi_p90": round(float(np.percentile(twi_vals, 90)), 2),
                "torrent_density_pct": round(torrent_pct, 2),
            }
        self._poly_stats_cache = stats
        return stats

    def ensure_loaded(self) -> DemGrid:
        if self._grid is not None:
            return self._grid
        with self._lock:
            if self._grid is not None:
                return self._grid
            if not self._cog_path.is_file():
                self._download_and_clip()
            self._grid = self._load_local()
            return self._grid

    def _download_and_clip(self) -> None:
        log.info("Descargando recorte Copernicus DEM GLO-30 para Cuenca de Cochabamba...")
        self._cog_path.parent.mkdir(parents=True, exist_ok=True)
        min_lon, min_lat, max_lon, max_lat = _CLIP_BBOX
        step = 1.0 / 3600.0  # 1 arcsec (~30 m)
        width = int(round((max_lon - min_lon) / step))
        height = int(round((max_lat - min_lat) / step))
        mosaic = np.full((height, width), np.nan, dtype=np.float32)
        dst_transform = from_bounds(min_lon, min_lat, max_lon, max_lat, width, height)

        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
            AWS_NO_SIGN_REQUEST="YES",
        ):
            for url in COPERNICUS_URLS:
                with rasterio.open(f"/vsicurl/{url}") as src:
                    b = src.bounds
                    iw = max(min_lon, b.left)
                    is_ = max(min_lat, b.bottom)
                    ie = min(max_lon, b.right)
                    in_ = min(max_lat, b.top)
                    if ie <= iw or in_ <= is_:
                        continue
                    win = window_from_bounds(iw, is_, ie, in_, src.transform).round_offsets().round_lengths()
                    data = src.read(1, window=win).astype(np.float32)
                    if src.nodata is not None:
                        data[data == src.nodata] = np.nan
                    wb = rasterio.windows.bounds(win, src.transform)
                    col0 = max(0, int(round((wb[0] - min_lon) / step)))
                    row0 = max(0, int(round((max_lat - wb[3]) / step)))
                    h_slice = min(data.shape[0], height - row0)
                    w_slice = min(data.shape[1], width - col0)
                    if h_slice > 0 and w_slice > 0:
                        mosaic[row0 : row0 + h_slice, col0 : col0 + w_slice] = data[:h_slice, :w_slice]

        tmp = self._cog_path.with_suffix(".tmp.tif")
        with rasterio.open(
            tmp,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=dst_transform,
            compress="LZW",
            tiled=True,
            nodata=np.nan,
        ) as dst:
            dst.write(mosaic, 1)
        tmp.replace(self._cog_path)
        log.info("Copernicus DEM GLO-30 cacheado en %s (%dx%d)", self._cog_path, width, height)

    def _load_local(self) -> DemGrid:
        with rasterio.open(self._cog_path) as src:
            elev = src.read(1).astype(np.float32)
            bounds = src.bounds
            dx = (bounds.right - bounds.left) / src.width
            dy = (bounds.top - bounds.bottom) / src.height

        lat_mid = 0.5 * (bounds.bottom + bounds.top)
        meters_x = dx * 111320.0 * math.cos(math.radians(lat_mid))
        meters_y = dy * 111320.0
        dz_dy, dz_dx = np.gradient(elev, meters_y, meters_x)
        slope_deg = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype(np.float32)
        # TPI positivo = fondo de quebrada/torrentera/depresión donde converge escorrentía.
        tpi_m = (_boxcar_mean(elev, radius=5) - elev).astype(np.float32)
        return DemGrid(
            elevation=elev,
            slope_deg=slope_deg,
            tpi_m=tpi_m,
            min_lon=float(bounds.left),
            min_lat=float(bounds.bottom),
            max_lon=float(bounds.right),
            max_lat=float(bounds.top),
            dx=float(dx),
            dy=float(dy),
        )

    def zone_stats(self, bbox: tuple[float, float, float, float]) -> dict[str, float]:
        g = self.ensure_loaded()
        c0 = max(0, int((bbox[0] - g.min_lon) / g.dx))
        c1 = min(g.width, int((bbox[2] - g.min_lon) / g.dx))
        r0 = max(0, int((g.max_lat - bbox[3]) / g.dy))
        r1 = min(g.height, int((g.max_lat - bbox[1]) / g.dy))
        elev = g.elevation[r0:r1, c0:c1]
        slope = g.slope_deg[r0:r1, c0:c1]
        valid = np.isfinite(elev) & np.isfinite(slope)
        if not valid.any():
            return {}
        ev = elev[valid]
        sl = slope[valid]
        return {
            "elevation_min_m": round(float(ev.min()), 1),
            "elevation_mean_m": round(float(ev.mean()), 1),
            "elevation_max_m": round(float(ev.max()), 1),
            "slope_mean_deg": round(float(sl.mean()), 1),
            "slope_p90_deg": round(float(np.percentile(sl, 90)), 1),
            "steep_pct_gt20": round(float(100.0 * (sl >= 20.0).mean()), 1),
            "steep_pct_gt25": round(float(100.0 * (sl >= 25.0).mean()), 1),
            "steep_pct_gt30": round(float(100.0 * (sl >= 30.0).mean()), 1),
            "low_slope_pct_lt5": round(float(100.0 * (sl < 5.0).mean()), 1),
            "above_2750_pct": round(float(100.0 * (ev >= COTA_URBANA_M).mean()), 1),
        }

    def point_diagnostics(self, lon: float, lat: float) -> dict[str, Any] | None:
        g = self.ensure_loaded()
        if not (g.min_lon <= lon <= g.max_lon and g.min_lat <= lat <= g.max_lat):
            return None
        col = min(g.width - 1, max(0, int((lon - g.min_lon) / g.dx)))
        row = min(g.height - 1, max(0, int((g.max_lat - lat) / g.dy)))
        elev = float(g.elevation[row, col])
        slope = float(g.slope_deg[row, col])
        tpi = float(g.tpi_m[row, col])
        if not math.isfinite(elev):
            return None
        hydro_diag = self.ensure_hydrology().point_hydro(lon, lat)
        return {
            "elevation_m": round(elev, 1),
            "slope_deg": round(slope, 1),
            "tpi_m": round(tpi, 1),
            "above_cota_2750": elev >= COTA_URBANA_M,
            "drainage_channel_hint": bool(
                hydro_diag.get("in_torrent_network") or tpi >= 4.0 or (slope < 3.0 and elev < 2620.0)
            ),
            "sar_terrain_caution": slope >= 25.0,
            "hydro": hydro_diag,
        }

    def render_tile(self, layer: str, z: int, x: int, y: int, rain_factor: float = 0.5) -> bytes:
        g = self.ensure_loaded()
        n = 2**z
        lon_w = x / n * 360.0 - 180.0
        lon_e = (x + 1) / n * 360.0 - 180.0
        lat_n = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
        lat_s = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))

        if lon_e < g.min_lon or lon_w > g.max_lon or lat_n < g.min_lat or lat_s > g.max_lat:
            return _BLANK_PNG

        xs = (x + (np.arange(256, dtype=np.float64) + 0.5) / 256.0) / n * 360.0 - 180.0
        ys_norm = (y + (np.arange(256, dtype=np.float64) + 0.5) / 256.0) / n
        ys = np.degrees(np.arctan(np.sinh(math.pi * (1.0 - 2.0 * ys_norm))))

        cols = np.floor((xs - g.min_lon) / g.dx).astype(np.int32)
        rows = np.floor((g.max_lat - ys) / g.dy).astype(np.int32)
        in_x = (cols >= 0) & (cols < g.width)
        in_y = (rows >= 0) & (rows < g.height)
        if not (in_x.any() and in_y.any()):
            return _BLANK_PNG

        cols_clip = np.clip(cols, 0, g.width - 1)
        rows_clip = np.clip(rows, 0, g.height - 1)
        inside = in_y[:, None] & in_x[None, :]

        if layer == "terrain":
            elev = g.elevation[np.ix_(rows_clip, cols_clip)]
            rgba = _encode_terrain_rgb(elev, inside)
        elif layer == "slope":
            slope = g.slope_deg[np.ix_(rows_clip, cols_clip)]
            rgba = _colorize_slope(slope, inside)
        elif layer == "susceptibility":
            elev = g.elevation[np.ix_(rows_clip, cols_clip)]
            slope = g.slope_deg[np.ix_(rows_clip, cols_clip)]
            tpi = g.tpi_m[np.ix_(rows_clip, cols_clip)]
            rgba = _colorize_susceptibility(elev, slope, tpi, inside, rain_factor)
        elif layer == "cota_drainage":
            elev = g.elevation[np.ix_(rows_clip, cols_clip)]
            slope = g.slope_deg[np.ix_(rows_clip, cols_clip)]
            tpi = g.tpi_m[np.ix_(rows_clip, cols_clip)]
            rgba = _colorize_cota_drainage(elev, slope, tpi, inside)
        else:
            return _BLANK_PNG

        buf = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=False)
        return buf.getvalue()


def _encode_terrain_rgb(elev: np.ndarray, inside: np.ndarray) -> np.ndarray:
    """Codificación Mapbox Terrain-RGB: height(m) = -10000 + (R*65536 + G*256 + B)*0.1."""
    safe = np.where(inside & np.isfinite(elev), elev, 2550.0)
    encoded = np.clip(np.rint((safe + 10000.0) * 10.0), 0, 16777215).astype(np.uint32)
    rgba = np.zeros((256, 256, 4), dtype=np.uint8)
    rgba[..., 0] = (encoded >> 16) & 0xFF
    rgba[..., 1] = (encoded >> 8) & 0xFF
    rgba[..., 2] = encoded & 0xFF
    rgba[..., 3] = 255
    return rgba


def _colorize_slope(slope: np.ndarray, inside: np.ndarray) -> np.ndarray:
    rgba = np.zeros((256, 256, 4), dtype=np.uint8)
    valid = inside & np.isfinite(slope) & (slope >= 6.0)
    if not valid.any():
        return rgba
    # 6..15° ámbar suave, 15..25° naranja, >25° rojo carmesí (zona crítica Tunari / escorzo SAR)
    t = np.clip((slope - 6.0) / 28.0, 0.0, 1.0)
    rgba[..., 0] = np.where(valid, (255 * np.clip(0.95 + 0.05 * t, 0, 1)).astype(np.uint8), 0)
    rgba[..., 1] = np.where(valid, (255 * np.clip(0.75 - 0.70 * t, 0, 1)).astype(np.uint8), 0)
    rgba[..., 2] = np.where(valid, (255 * np.clip(0.05 + 0.12 * (1 - t), 0, 1)).astype(np.uint8), 0)
    rgba[..., 3] = np.where(valid, (110 + 115 * t).astype(np.uint8), 0)
    return rgba


def _colorize_susceptibility(
    elev: np.ndarray,
    slope: np.ndarray,
    tpi: np.ndarray,
    inside: np.ndarray,
    rain_factor: float,
) -> np.ndarray:
    """Mapa bivariado: laderas/torrenteras (ámbar-rojo) vs. convergencia/inundación de valle (cian-azul)."""
    rgba = np.zeros((256, 256, 4), dtype=np.uint8)
    valid = inside & np.isfinite(elev) & np.isfinite(slope)
    if not valid.any():
        return rgba

    rf = 0.65 + 0.55 * float(np.clip(rain_factor, 0.0, 1.0))
    # 1) Susceptibilidad de ladera / torrentera (pendiente >= 14° o quebrada empinada TPI > 3 m)
    slope_idx = np.clip((slope - 14.0) / 20.0, 0.0, 1.0) * np.where(tpi > 1.5, 1.25, 0.9) * rf
    slope_idx = np.clip(slope_idx, 0.0, 1.0)

    # 2) Susceptibilidad de anegamiento en valle (pendiente < 4°, depresión TPI > 1.2 m, cota < 2680 m)
    flood_idx = (
        np.clip((4.0 - slope) / 4.0, 0.0, 1.0)
        * np.clip((tpi - 0.5) / 4.0, 0.0, 1.0)
        * np.where(elev < 2680.0, 1.0, 0.15)
        * rf
    )
    flood_idx = np.clip(flood_idx, 0.0, 1.0)

    is_slope = valid & (slope_idx >= 0.18) & (slope_idx >= flood_idx)
    is_flood = valid & (flood_idx >= 0.18) & (~is_slope)

    if is_slope.any():
        t = slope_idx[is_slope]
        rgba[is_slope, 0] = 255
        rgba[is_slope, 1] = np.clip(180 - 150 * t, 20, 220).astype(np.uint8)
        rgba[is_slope, 2] = 24
        rgba[is_slope, 3] = np.clip(95 + 135 * t, 90, 230).astype(np.uint8)

    if is_flood.any():
        t = flood_idx[is_flood]
        rgba[is_flood, 0] = 20
        rgba[is_flood, 1] = np.clip(180 + 50 * t, 140, 240).astype(np.uint8)
        rgba[is_flood, 2] = 255
        rgba[is_flood, 3] = np.clip(95 + 135 * t, 90, 230).astype(np.uint8)

    return rgba


def _colorize_cota_drainage(
    elev: np.ndarray,
    slope: np.ndarray,
    tpi: np.ndarray,
    inside: np.ndarray,
) -> np.ndarray:
    """Traza Cota 2750 m física (verde) y vaguadas/torrenteras (cian) desde el DEM 30 m."""
    rgba = np.zeros((256, 256, 4), dtype=np.uint8)
    valid = inside & np.isfinite(elev) & np.isfinite(slope)
    if not valid.any():
        return rgba

    # 1) Torrenteras y vaguadas (TPI positivo fuerte en quebradas o valle bajo)
    is_channel = valid & ((tpi >= 4.0) | ((tpi >= 2.2) & (slope >= 6.0)))
    if is_channel.any():
        strength = np.clip((tpi[is_channel] - 2.0) / 10.0, 0.25, 1.0)
        rgba[is_channel, 0] = 48
        rgba[is_channel, 1] = 215
        rgba[is_channel, 2] = 245
        rgba[is_channel, 3] = (120 + 115 * strength).astype(np.uint8)

    # 2) Contorno físico Cota 2750 m (prioridad visual sobre torrenteras al cruzar)
    is_cota = valid & (np.abs(elev - COTA_URBANA_M) <= 8.0)
    if is_cota.any():
        rgba[is_cota, 0] = 86
        rgba[is_cota, 1] = 235
        rgba[is_cota, 2] = 140
        rgba[is_cota, 3] = 225

    return rgba
