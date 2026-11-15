"""Load an analysis-ready SAR scene: AOI crop + multilook (speckle reduction) per polarization.

Reading is strip-wise and chunk-friendly so it works the same for local files
and HTTP/S3 streaming. Multilooking (block mean in linear power) is the
physically correct way to both downsample and reduce speckle.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import h5py
import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine

from . import gcov
from . import sar_physics as phys
from .gcov import Grid, Identification, PixelWindow, RadarParameters

log = logging.getLogger("nisar.scene")

STRIP_ROWS = 1024
MIN_VALID_FRACTION = 0.5
# Below -40 dB (1e-4 linear) gamma0 is not a measurement: it is fill / outside-swath padding
# (seen as ~1e-14 at swath edges). It must not enter the multilook average.
MIN_LINEAR_GAMMA0 = 1e-4


@dataclass
class LoadOptions:
    bbox: tuple[float, float, float, float] | None = None
    frequency: str = "auto"  # auto | frequencyA | frequencyB
    target_pixels: int = 2_000_000  # analysis resolution after multilook
    max_read_pixels: int = 8_000_000  # per layer, keeps S3/HTTPS streaming fast


@dataclass
class SarScene:
    granule_id: str
    access_mode: str
    identification: Identification
    radar: RadarParameters
    epsg: int
    native_spacing_m: float
    window: PixelWindow
    looks: int
    transform: Affine
    bounds_lonlat: tuple[float, float, float, float]  # west, south, east, north
    aoi_bbox: tuple[float, float, float, float] | None
    aoi_intersects: bool
    speckle_filter: str
    layers: dict[str, np.ndarray] = field(default_factory=dict)  # linear gamma0
    raw_valid_fraction: dict[str, float] = field(default_factory=dict)

    @property
    def co_pol(self) -> str | None:
        return next((t for t in gcov.CO_POL_TERMS if t in self.layers), None)

    @property
    def cross_pol(self) -> str | None:
        return next((t for t in gcov.CROSS_POL_TERMS if t in self.layers), None)

    @property
    def pixel_spacing_m(self) -> float:
        return self.native_spacing_m * self.looks

    @property
    def shape(self) -> tuple[int, int]:
        return next(iter(self.layers.values())).shape

    def clean_db(self, term: str) -> np.ndarray:
        """Gamma0 in dB with NoData and radiometric outliers set to NaN."""
        db = phys.to_db(self.layers[term])
        db[~phys.clean_mask(db)] = np.nan
        return db

    @property
    def thresholds(self) -> phys.ScatteringThresholds:
        return phys.thresholds_for(self.identification.radar_band)

    def scattering_classes(self) -> tuple[np.ndarray, str]:
        cross = self.clean_db(self.cross_pol) if self.cross_pol else None
        classes, method = phys.classify(self.clean_db(self.co_pol), cross, self.thresholds)
        return classes, f"{method}_{self.identification.radar_band}_band"


def load_scene(h5: h5py.File, granule_id: str, access_mode: str, opts: LoadOptions) -> SarScene:
    grids = gcov.list_grids(h5)
    if not grids:
        raise ValueError(f"{granule_id}: no contiene grillas GCOV con términos de covarianza")

    grid, window, intersects = _select_grid(grids, opts, opts.max_read_pixels)
    looks = max(1, math.ceil(math.sqrt(window.pixels / max(opts.target_pixels, 1))))
    log.info(
        "%s: %s ventana %dx%d px (%s m), multilook %dx%d",
        granule_id, grid.frequency, *window.shape, grid.dx, looks, looks,
    )

    layers, raw_valid = {}, {}
    ds_root = h5[f"{gcov.GRIDS_PATH}/{grid.frequency}"]
    for term in grid.terms:
        arr, frac = _read_multilooked(ds_root[term], window, looks)
        layers[term] = phys.boxcar_filter(arr, 3) if looks == 1 else arr
        raw_valid[term] = frac

    transform = _transform(grid, window, looks)
    rows, cols = next(iter(layers.values())).shape
    return SarScene(
        granule_id=granule_id,
        access_mode=access_mode,
        identification=gcov.read_identification(h5, granule_id),
        radar=gcov.read_radar_parameters(h5, grid.frequency),
        epsg=grid.epsg,
        native_spacing_m=abs(grid.dx),
        window=window,
        looks=looks,
        transform=transform,
        bounds_lonlat=_bounds_lonlat(transform, rows, cols, grid.epsg),
        aoi_bbox=opts.bbox,
        aoi_intersects=intersects,
        speckle_filter=f"multilook_boxcar_{looks}x{looks}" if looks > 1 else "boxcar_3x3",
        layers=layers,
        raw_valid_fraction=raw_valid,
    )


def _select_grid(grids: list[Grid], opts: LoadOptions, budget: int) -> tuple[Grid, PixelWindow, bool]:
    """Finest grid whose AOI window fits the read budget; otherwise the coarsest."""
    candidates = grids if opts.frequency == "auto" else [g for g in grids if g.frequency == opts.frequency]
    if not candidates:
        raise ValueError(f"Frecuencia {opts.frequency} no disponible: {[g.frequency for g in grids]}")
    choice = None
    for grid in candidates:
        window = gcov.window_for_bbox(grid, opts.bbox) if opts.bbox else None
        intersects = window is not None
        window = window or gcov.full_window(grid)
        choice = (grid, window, intersects)
        if window.pixels <= budget:
            break
    if opts.bbox and not choice[2]:
        log.warning("El AOI no intersecta el gránulo: se analiza el frame completo")
    return choice


def _read_multilooked(ds: h5py.Dataset, win: PixelWindow, looks: int) -> tuple[np.ndarray, float]:
    """Strip-wise block mean of valid (finite, >0) linear pixels. Returns (array, raw valid fraction)."""
    out_rows, out_cols = win.shape[0] // looks, win.shape[1] // looks
    out = np.full((out_rows, out_cols), np.nan, dtype=np.float32)
    strip = looks * max(1, STRIP_ROWS // looks)
    col_end = win.col0 + out_cols * looks
    valid_total = 0
    for r in range(0, out_rows * looks, strip):
        r_end = min(r + strip, out_rows * looks)
        block = ds[win.row0 + r: win.row0 + r_end, win.col0: col_end].astype(np.float32)
        valid = np.isfinite(block) & (block > MIN_LINEAR_GAMMA0)
        valid_total += int(valid.sum())
        h = (r_end - r) // looks
        sums = np.where(valid, block, 0).reshape(h, looks, out_cols, looks).sum(axis=(1, 3))
        counts = valid.reshape(h, looks, out_cols, looks).sum(axis=(1, 3))
        min_count = MIN_VALID_FRACTION * looks * looks
        out[r // looks: r // looks + h] = np.where(counts >= min_count, sums / np.maximum(counts, 1), np.nan)
    read_pixels = out_rows * looks * out_cols * looks
    return out, round(valid_total / max(read_pixels, 1), 4)


def _transform(grid: Grid, win: PixelWindow, looks: int) -> Affine:
    left = float(grid.x[win.col0]) - grid.dx / 2
    top = float(grid.y[win.row0]) - grid.dy / 2
    return Affine(grid.dx * looks, 0.0, left, 0.0, grid.dy * looks, top)


def _bounds_lonlat(transform: Affine, rows: int, cols: int, epsg: int) -> tuple[float, float, float, float]:
    to_wgs84 = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    t = np.linspace(0, 1, 11)
    px = np.concatenate([t * cols, t * cols, np.zeros(11), np.full(11, cols)])
    py = np.concatenate([np.zeros(11), np.full(11, rows), t * rows, t * rows])
    xs, ys = transform * (px, py)
    lons, lats = to_wgs84.transform(xs, ys)
    return (round(float(np.min(lons)), 6), round(float(np.min(lats)), 6),
            round(float(np.max(lons)), 6), round(float(np.max(lats)), 6))
