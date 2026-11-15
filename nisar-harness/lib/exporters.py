"""Multi-format exporters (GIS + web). Registry-based: add a format by adding a function to EXPORTERS."""
from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

from . import sar_physics as phys
from .scene import SarScene

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "matplotlib"))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

NODATA = -9999.0
CLASS_COLORS = {  # RGBA, index matches sar_physics.SCATTERING_CLASSES
    0: (30, 90, 200, 255),    # water / flood
    1: (200, 170, 120, 255),  # bare soil
    2: (40, 160, 60, 255),    # vegetation canopy
    3: (220, 40, 40, 255),    # urban double bounce
}

Exporter = Callable[[SarScene, Path, str], Path]


def _stretch(db: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    scaled = np.clip((db - vmin) / max(vmax - vmin, 1e-6), 0, 1)
    return (np.nan_to_num(scaled, nan=0.0) * 255).astype(np.uint8)


def _percentiles(db: np.ndarray, lo: float = 2, hi: float = 98) -> tuple[float, float]:
    v = db[np.isfinite(db)]
    return tuple(np.percentile(v, [lo, hi])) if v.size else (-25.0, 0.0)


def export_geotiff(scene: SarScene, out: Path, stem: str) -> Path:
    path = out / f"{stem}_gamma0_db.tif"
    rows, cols = scene.shape
    with rasterio.open(
        path, "w", driver="GTiff", height=rows, width=cols, count=len(scene.layers),
        dtype="float32", crs=f"EPSG:{scene.epsg}", transform=scene.transform,
        nodata=NODATA, compress="deflate", tiled=True,
    ) as dst:
        for band, (term, arr) in enumerate(scene.layers.items(), start=1):
            db = phys.to_db(arr)
            dst.write(np.where(np.isfinite(db), db, NODATA).astype(np.float32), band)
            dst.set_band_description(band, f"NISAR {term} gamma0 (dB)")
    return path


def export_visual_png(scene: SarScene, out: Path, stem: str) -> Path:
    path = out / f"{stem}_{scene.co_pol}_visual.png"
    db = phys.to_db(scene.layers[scene.co_pol])
    vmin, vmax = _percentiles(db, 3, 97)
    w, s, e, n = scene.bounds_lonlat
    fig, ax = plt.subplots(figsize=(10, 8), dpi=130)
    im = ax.imshow(db, cmap="gray", vmin=vmin, vmax=vmax, extent=(w, e, s, n), aspect="auto")
    ax.set_title(f"NISAR {scene.identification.radar_band}-band {scene.co_pol} γ0 · "
                 f"{(scene.identification.start_time or '')[:10]}", fontsize=10)
    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.04).set_label("Retrodispersión γ0 (dB)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def export_rgb_overlay(scene: SarScene, out: Path, stem: str) -> Path:
    """Transparent RGBA false colour (R=co, G=cross, B=co/cross) usable as a map overlay."""
    path = out / f"{stem}_RGB_falsocolor.png"
    co_db = phys.to_db(scene.layers[scene.co_pol])
    valid = np.isfinite(co_db)
    if scene.cross_pol:
        x_db = phys.to_db(scene.layers[scene.cross_pol])
        valid &= np.isfinite(x_db)
        rgb = np.dstack([
            _stretch(co_db, -22.0, 0.0),
            _stretch(x_db, -28.0, -8.0),
            _stretch(np.where(valid, co_db - x_db, 0.0), 2.0, 15.0),
        ])
    else:  # single-pol: perceptual colormap of co-pol
        vmin, vmax = _percentiles(co_db)
        rgb = (plt.get_cmap("turbo")(np.clip((co_db - vmin) / (vmax - vmin), 0, 1))[..., :3] * 255).astype(np.uint8)
    alpha = np.where(valid, 255, 0).astype(np.uint8)
    Image.fromarray(np.dstack([rgb, alpha]), "RGBA").save(path)
    return path


def export_classes_overlay(scene: SarScene, out: Path, stem: str) -> Path:
    path = out / f"{stem}_scattering_classes.png"
    classes, _ = scene.scattering_classes()
    rgba = np.zeros((*classes.shape, 4), dtype=np.uint8)
    for idx, color in CLASS_COLORS.items():
        rgba[classes == idx] = color
    Image.fromarray(rgba, "RGBA").save(path)
    return path


def export_histogram(scene: SarScene, out: Path, stem: str) -> Path:
    path = out / f"{stem}_histogram.png"
    th = phys.DEFAULT_THRESHOLDS
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=120)
    for term, arr in scene.layers.items():
        db = phys.to_db(arr)
        ax.hist(db[phys.clean_mask(db)], bins=80, density=True, alpha=0.55, label=term)
    for edge, label, color in zip(th.edges(), ("agua|suelo", "suelo|vegetación", "vegetación|urbano"),
                                  ("tab:blue", "tab:olive", "tab:red")):
        ax.axvline(edge, color=color, linestyle=":", label=f"{label} ({edge} dB)")
    ax.set_xlabel("Retrodispersión γ0 (dB)")
    ax.set_ylabel("Densidad")
    ax.set_title("Distribución de retrodispersión por polarización")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def export_kml(scene: SarScene, out: Path, stem: str) -> Path:
    path = out / f"{stem}.kml"
    overlay = out / f"{stem}_RGB_falsocolor.png"
    if not overlay.exists():
        export_rgb_overlay(scene, out, stem)
    w, s, e, n = scene.bounds_lonlat
    ident = scene.identification
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Folder>
    <name>NISAR {ident.radar_band}-band {scene.co_pol} · {(ident.start_time or '')[:10]}</name>
    <description>NISAR (NASA/ISRO) {scene.granule_id}</description>
    <GroundOverlay>
      <name>{scene.granule_id}</name>
      <Icon><href>{overlay.name}</href></Icon>
      <LatLonBox><north>{n}</north><south>{s}</south><east>{e}</east><west>{w}</west></LatLonBox>
    </GroundOverlay>
  </Folder>
</kml>
""", encoding="utf-8")
    return path


def export_geojson(scene: SarScene, out: Path, stem: str) -> Path:
    import json

    path = out / f"{stem}_footprint.geojson"
    w, s, e, n = scene.bounds_lonlat
    ident = scene.identification
    props = {
        "granule_id": scene.granule_id, "mission": "NISAR", "band": ident.radar_band,
        "orbit_direction": ident.orbit_direction, "acquired": ident.start_time,
        "epsg": scene.epsg, "polarizations": list(scene.layers),
        "pixel_spacing_m": scene.pixel_spacing_m,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    features = [{
        "type": "Feature",
        "properties": {**props, "role": "analyzed_area"},
        "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]},
    }]
    if ident.footprint:
        features.append({
            "type": "Feature",
            "properties": {**props, "role": "granule_footprint"},
            "geometry": {"type": "Polygon", "coordinates": [ident.footprint]},
        })
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8")
    return path


EXPORTERS: dict[str, Exporter] = {
    "tif": export_geotiff,
    "png": export_visual_png,
    "rgb": export_rgb_overlay,
    "classes": export_classes_overlay,
    "histogram": export_histogram,
    "kml": export_kml,
    "geojson": export_geojson,
}


def export_all(scene: SarScene, out_dir: Path, formats: list[str] | None = None) -> dict[str, Path]:
    selected = list(EXPORTERS) if not formats or "all" in formats else formats
    unknown = set(selected) - set(EXPORTERS)
    if unknown:
        raise ValueError(f"Formatos desconocidos: {sorted(unknown)}. Disponibles: {list(EXPORTERS)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = scene.granule_id
    return {fmt: EXPORTERS[fmt](scene, out_dir, stem) for fmt in selected}
