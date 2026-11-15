"""Sentinel-1 (OPERA L2 RTC-S1) reader: burst COGs streamed from AWS -> the same SarScene as NISAR.

For every burst that touches the AOI and every polarisation:
  1. open the remote COG (S3 in-region or signed HTTPS, see access.cog_candidates)
  2. read ONLY the AOI window, decimated by the multilook factor (GDAL picks COG overviews)
  3. reproject into one common UTM grid over the AOI and mosaic (first valid value wins)
The OPERA layover/shadow mask removes geometrically distorted pixels (steep slopes facing or
hidden from the radar), which is what produces false "urban" on mountain sides.
"""
from __future__ import annotations

import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import Polygon, box

from . import sar_physics as phys
from .access import GranuleSource, cog_candidates
from .gcov import Identification, PixelWindow, RadarParameters
from .scene import MIN_LINEAR_GAMMA0, LoadOptions, SarScene, _bounds_lonlat
from .sensors import SENTINEL1
from .settings import Settings

log = logging.getLogger("nisar.sentinel1")

INVALID_MASK_VALUES = (1, 2, 3)  # OPERA RTC mask: 0 valid, 1 shadow, 2 layover, 3 both (255 fill -> NaN on read)
GDAL_ENV = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
            "GDAL_HTTP_MULTIRANGE": "YES", "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES"}
MAX_WORKERS = 6
# Network reads run in parallel; rasterio's in-memory reprojection is not thread-safe -> serialised.
_REPROJECT_LOCK = threading.Lock()


def _utm_epsg(lon: float, lat: float) -> int:
    zone = math.floor((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone


def _target_grid(bbox: tuple[float, ...], target_pixels: int) -> tuple[int, Affine, int, int, int]:
    epsg = _utm_epsg((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", f"EPSG:{epsg}", *bbox, densify_pts=21)
    native = SENTINEL1.native_spacing_m
    looks = max(1, math.ceil(math.sqrt(((maxx - minx) / native) * ((maxy - miny) / native) / max(target_pixels, 1))))
    res = native * looks
    cols, rows = math.ceil((maxx - minx) / res), math.ceil((maxy - miny) / res)
    return epsg, Affine(res, 0, minx, 0, -res, maxy), rows, cols, looks


def _read_into(path: str, env: dict[str, str], dst: np.ndarray, dst_transform: Affine, dst_epsg: int,
               looks: int, nearest: bool) -> None:
    """Read the part of one COG that overlaps the destination grid and reproject it in place."""
    rows, cols = dst.shape
    dst_bounds = (dst_transform.c, dst_transform.f + dst_transform.e * rows,
                  dst_transform.c + dst_transform.a * cols, dst_transform.f)
    with rasterio.Env(**GDAL_ENV, **env), rasterio.open(path) as ds:
        b = transform_bounds(f"EPSG:{dst_epsg}", ds.crs, *dst_bounds, densify_pts=21)
        win = from_bounds(*b, ds.transform).intersection(Window(0, 0, ds.width, ds.height))
        win = win.round_offsets().round_lengths()
        if win.width < 1 or win.height < 1:
            return
        out_shape = (max(1, int(win.height // looks)), max(1, int(win.width // looks)))
        resampling = Resampling.nearest if nearest else Resampling.average
        src = ds.read(1, window=win, out_shape=out_shape, resampling=resampling).astype(np.float32)
        if ds.nodata is not None and np.isfinite(ds.nodata):
            # Fill (e.g. mask=255 outside the burst) must stay EMPTY so another burst can fill it.
            src[src == ds.nodata] = np.nan
        src_transform = ds.window_transform(win) @ Affine.scale(win.width / out_shape[1], win.height / out_shape[0])
        if not nearest:
            src[~(np.isfinite(src) & (src > MIN_LINEAR_GAMMA0))] = np.nan
        src_crs = ds.crs
    tmp = np.full(dst.shape, np.nan, dtype=np.float32)
    with _REPROJECT_LOCK:
        reproject(src, tmp, src_transform=src_transform, src_crs=src_crs, src_nodata=np.nan,
                  dst_transform=dst_transform, dst_crs=f"EPSG:{dst_epsg}", dst_nodata=np.nan,
                  resampling=Resampling.nearest if nearest else Resampling.bilinear)
    fill = np.isnan(dst) & np.isfinite(tmp)
    dst[fill] = tmp[fill]


def _open_and_read(urls: dict[str, Any], settings: Settings, prefer: str, *args: Any) -> str:
    errors = []
    for mode, path, env in cog_candidates(urls, settings, prefer):
        try:
            _read_into(path, env, *args)
            return mode
        except Exception as exc:  # noqa: BLE001 - try next access mode
            errors.append(f"{mode}: {exc}")
    raise ConnectionError("; ".join(errors) or "sin rutas de acceso")


def load_scene_sentinel1(src: GranuleSource, settings: Settings, opts: LoadOptions, prefer: str = "auto") -> SarScene:
    granule = src.granule
    if granule is None or not granule.assets:
        raise ValueError(f"{src.granule_id}: pasada Sentinel-1 sin bursts")
    bbox = tuple(opts.bbox) if opts.bbox else tuple(Polygon(granule.footprint).bounds)
    aoi = box(*bbox)
    bursts = [a for a in granule.assets if len(a.get("footprint") or []) >= 3
              and Polygon(a["footprint"]).buffer(0).intersects(aoi)]
    if not bursts:
        raise ValueError(f"{src.granule_id}: ningún burst toca el área")

    epsg, transform, rows, cols, looks = _target_grid(bbox, opts.target_pixels)
    log.info("%s: %d bursts, grilla %dx%d (%d m, multilook %dx%d)",
             src.granule_id, len(bursts), rows, cols, int(transform.a), looks, looks)
    layers = {term: np.full((rows, cols), np.nan, dtype=np.float32)
              for term in (SENTINEL1.co_term, SENTINEL1.cross_term)}
    mask = np.full((rows, cols), np.nan, dtype=np.float32)
    jobs = []
    for burst in bursts:
        for term, key in ((SENTINEL1.co_term, "VV"), (SENTINEL1.cross_term, "VH")):
            if burst.get(key):
                jobs.append((burst[key], layers[term], False))
        if burst.get("mask"):
            jobs.append((burst["mask"], mask, True))

    modes, errors = set(), []
    # Each job writes into its own destination array only where still empty; one lock-free pass
    # per array is safe because jobs on the same array run sequentially within a single worker.
    by_target: dict[int, list] = {}
    for urls, dst, nearest in jobs:
        by_target.setdefault(id(dst), []).append((urls, dst, nearest))

    def run(group: list) -> None:
        for urls, dst, nearest in group:
            try:
                modes.add(_open_and_read(urls, settings, prefer, dst, transform, epsg, looks, nearest))
            except Exception as exc:  # noqa: BLE001 - a missing burst only leaves a gap
                errors.append(str(exc))

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(by_target))) as pool:
        list(pool.map(run, by_target.values()))
    if not modes:
        raise ConnectionError(f"No se pudo leer ningún burst de {src.granule_id}: {errors[:1]}")
    if errors:
        log.warning("%s: %d lecturas fallaron (huecos en el mosaico)", src.granule_id, len(errors))

    invalid = np.isin(mask, INVALID_MASK_VALUES)
    raw_valid = {}
    for term, arr in layers.items():
        arr[invalid] = np.nan
        raw_valid[term] = round(float(np.isfinite(arr).mean()), 4)
        if looks == 1:
            layers[term] = phys.boxcar_filter(arr, 3)

    footprint_union = Polygon(granule.footprint).buffer(0) if len(granule.footprint) >= 3 else aoi
    return SarScene(
        granule_id=granule.granule_id,
        access_mode="+".join(sorted(modes)),
        identification=Identification(
            granule_id=granule.granule_id, mission="Sentinel-1", radar_band=SENTINEL1.band,
            orbit_direction=granule.orbit_direction, look_direction="Right",
            start_time=granule.time_start, end_time=granule.time_end,
            track=int(granule.track) if granule.track else None, frame=None,
            product_version="OPERA RTC-S1 v1.0", footprint=granule.footprint,
        ),
        radar=RadarParameters(
            frequency="C-band IW", center_frequency_hz=SENTINEL1.center_frequency_hz,
            wavelength_cm=SENTINEL1.wavelength_cm,
            near_incidence_deg=29.1, far_incidence_deg=46.0, mean_incidence_deg=37.6,  # IW swath nominal
            range_resolution_m=None, azimuth_resolution_m=None, range_bandwidth_mhz=None,
        ),
        epsg=epsg,
        native_spacing_m=SENTINEL1.native_spacing_m,
        window=PixelWindow(0, rows, 0, cols),
        looks=looks,
        transform=transform,
        bounds_lonlat=_bounds_lonlat(transform, rows, cols, epsg),
        aoi_bbox=opts.bbox,
        aoi_intersects=footprint_union.intersects(aoi),
        speckle_filter=f"multilook_average_{looks}x{looks}+mask_layover_shadow" if looks > 1
        else "boxcar_3x3+mask_layover_shadow",
        layers=layers,
        raw_valid_fraction=raw_valid,
    )
