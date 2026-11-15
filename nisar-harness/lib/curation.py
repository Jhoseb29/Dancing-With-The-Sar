"""Turn a SarScene into the curated metrics contract consumed by the interpreter and the UI."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from . import sar_physics as phys
from .regions import bbox_overlap_fraction, matching_regions, season_for
from .scene import SarScene

SCHEMA_VERSION = "2.0"


def curate(scene: SarScene) -> dict[str, Any]:
    co = scene.co_pol
    if co is None:
        raise ValueError(f"{scene.granule_id}: sin polarización co-polar (HHHH/VVVV)")

    co_db = phys.to_db(scene.layers[co])
    finite = np.isfinite(co_db)
    clean = phys.clean_mask(co_db)
    total = co_db.size
    cross = scene.cross_pol

    classes, method = scene.scattering_classes()
    per_pol = {term: phys.distribution(scene.clean_db(term)) for term in scene.layers}
    indices = (
        phys.polarimetric_indices(scene.layers[co], scene.layers[cross])
        if cross else {"rvi_mean": None, "rvi_median": None, "cross_pol_ratio_mean_db": None}
    )
    ident = scene.identification
    acq = _parse_time(ident.start_time)
    regions = matching_regions(scene.aoi_bbox or scene.bounds_lonlat)

    return {
        "schema_version": SCHEMA_VERSION,
        "curated_at": datetime.now(timezone.utc).isoformat(),
        "granule_id": scene.granule_id,
        "acquisition": {
            "start_time": ident.start_time,
            "end_time": ident.end_time,
            "orbit_pass_direction": ident.orbit_direction,
            "look_direction": ident.look_direction,
            "track": ident.track,
            "frame": ident.frame,
            "product_version": ident.product_version,
            "season": season_for(acq.month, regions[0]["key"] if regions else None) if acq else None,
        },
        "spatial_reference": {
            "epsg": scene.epsg,
            "native_pixel_spacing_m": scene.native_spacing_m,
            "analysis_pixel_spacing_m": scene.pixel_spacing_m,
            "analysis_shape": list(scene.shape),
            "analyzed_bounds_lonlat": list(scene.bounds_lonlat),
            "granule_footprint_lonlat": ident.footprint,
            "aoi_bbox": list(scene.aoi_bbox) if scene.aoi_bbox else None,
            "aoi_intersects_granule": scene.aoi_intersects,
            "aoi_covered_fraction": (
                bbox_overlap_fraction(scene.aoi_bbox, scene.bounds_lonlat) if scene.aoi_bbox else None
            ),
            "regions": regions,
        },
        "radar_physics": {
            "band": ident.radar_band,
            "frequency_grid": scene.radar.frequency,
            "center_frequency_hz": scene.radar.center_frequency_hz,
            "wavelength_cm": scene.radar.wavelength_cm,
            "incidence_angle": {
                "near_deg": scene.radar.near_incidence_deg,
                "far_deg": scene.radar.far_incidence_deg,
                "mean_deg": scene.radar.mean_incidence_deg,
            },
            "range_resolution_m": scene.radar.range_resolution_m,
            "azimuth_resolution_m": scene.radar.azimuth_resolution_m,
            "polarizations": list(scene.layers),
            "primary_polarization": co,
            "cross_polarization": cross,
        },
        "data_quality": {
            "access_mode": scene.access_mode,
            "raw_valid_fraction": scene.raw_valid_fraction,
            "analysis_pixels_total": int(total),
            "analysis_pixels_valid": int(finite.sum()),
            "valid_pixels_pct": round(100.0 * finite.sum() / max(total, 1), 2),
            "outliers_suppressed_count": int((finite & ~clean).sum()),
            "speckle_filter_applied": scene.speckle_filter,
            "equivalent_looks_added": scene.looks ** 2,
        },
        "polarimetric_indices": indices,
        "physical_scattering_breakdown": phys.scattering_breakdown(classes),
        "classification": {"method": method, "thresholds_db": phys.thresholds_dict()},
        "statistical_distribution_db": phys.distribution(co_db[clean]),
        "per_polarization_db": per_pol,
    }


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:19])
    except ValueError:
        return None
