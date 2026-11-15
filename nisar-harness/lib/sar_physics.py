"""Deterministic SAR physics: dB conversion, speckle filtering, scattering classes, polarimetric indices."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

DB_VALID_RANGE = (-35.0, 15.0)  # outside -> radiometric outlier (noise floor / saturation)


@dataclass(frozen=True)
class ScatteringThresholds:
    """Heuristic L-band gamma0 thresholds (dB).

    single-pol (co only): water < water_max <= soil < soil_max <= vegetation < vegetation_max <= double bounce
    dual-pol (co + cross) decision tree, which separates dense forest (high co AND high cross) from urban:
        water   : co < water_co_max_dual and cross < water_cross_max (specular; tuned on Cochabamba lakes)
        urban   : co >= vegetation_max and co - cross >= urban_co_cross_min  (dihedral, little depolarisation)
        vegetation: cross >= vegetation_cross_min                     (volume scattering depolarises)
        soil    : everything else                                     (surface scattering)
    """
    water_max: float = -18.0
    soil_max: float = -12.0
    vegetation_max: float = -6.0
    water_co_max_dual: float = -15.0
    water_cross_max: float = -22.0
    vegetation_cross_min: float = -18.0
    urban_co_cross_min: float = 10.0

    def edges(self) -> list[float]:
        return [self.water_max, self.soil_max, self.vegetation_max]


SCATTERING_CLASSES = ("water_flood", "bare_soil", "vegetation_canopy", "urban_double_bounce")
DEFAULT_THRESHOLDS = ScatteringThresholds()


def to_db(linear: np.ndarray) -> np.ndarray:
    out = np.full(linear.shape, np.nan, dtype=np.float32)
    ok = np.isfinite(linear) & (linear > 0)
    out[ok] = 10.0 * np.log10(linear[ok])
    return out


def boxcar_filter(arr: np.ndarray, size: int = 3) -> np.ndarray:
    """NaN-aware moving average (integral image, O(N))."""
    if arr.ndim != 2 or min(arr.shape) < size:
        return arr
    pad = size // 2
    valid = np.isfinite(arr)
    vals = np.pad(np.where(valid, arr, 0.0).astype(np.float64), pad, mode="reflect")
    cnts = np.pad(valid.astype(np.float64), pad, mode="reflect")

    def window_sum(a: np.ndarray) -> np.ndarray:
        c = np.pad(a.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        return c[size:, size:] - c[:-size, size:] - c[size:, :-size] + c[:-size, :-size]

    s, n = window_sum(vals), window_sum(cnts)
    out = np.where(n > 0, s / np.maximum(n, 1), np.nan).astype(np.float32)
    out[~valid] = np.nan
    return out


def classify(co_db: np.ndarray, cross_db: np.ndarray | None = None,
             th: ScatteringThresholds = DEFAULT_THRESHOLDS) -> tuple[np.ndarray, str]:
    """Per-pixel class index 0..3 (see SCATTERING_CLASSES), -1 invalid. Returns (classes, method)."""
    if cross_db is None:
        classes = np.digitize(co_db, th.edges()).astype(np.int8)
        classes[~np.isfinite(co_db)] = -1
        return classes, "single_pol_threshold"
    valid = np.isfinite(co_db) & np.isfinite(cross_db)
    classes = np.full(co_db.shape, -1, dtype=np.int8)
    classes[valid] = 1
    classes[valid & (cross_db >= th.vegetation_cross_min)] = 2
    classes[valid & (co_db >= th.vegetation_max) & (co_db - cross_db >= th.urban_co_cross_min)] = 3
    classes[valid & (co_db < th.water_co_max_dual) & (cross_db < th.water_cross_max)] = 0
    return classes, "dual_pol_decision_tree"


def clean_mask(db: np.ndarray) -> np.ndarray:
    lo, hi = DB_VALID_RANGE
    return np.isfinite(db) & (db >= lo) & (db <= hi)


def distribution(db_values: np.ndarray) -> dict[str, float]:
    v = db_values[np.isfinite(db_values)]
    if v.size == 0:
        return {}
    p05, p25, p50, p75, p95 = np.percentile(v, [5, 25, 50, 75, 95])
    return {
        "mean_db": round(float(v.mean()), 2),
        "median_db": round(float(p50), 2),
        "std_dev_db": round(float(v.std()), 2),
        "p05_db": round(float(p05), 2),
        "p25_db": round(float(p25), 2),
        "p75_db": round(float(p75), 2),
        "p95_db": round(float(p95), 2),
    }


def scattering_breakdown(classes: np.ndarray) -> dict[str, float]:
    total = max(int((classes >= 0).sum()), 1)
    return {
        f"{name}_pct": round(100.0 * int((classes == i).sum()) / total, 2)
        for i, name in enumerate(SCATTERING_CLASSES)
    }


def polarimetric_indices(co: np.ndarray, cross: np.ndarray) -> dict[str, float | None]:
    """Dual-pol RVI = 4·σx / (σco + σx) in [0, 1]; CPR = σx/σco in dB."""
    ok = np.isfinite(co) & np.isfinite(cross) & (co > 0) & (cross > 0)
    if not ok.any():
        return {"rvi_mean": None, "rvi_median": None, "cross_pol_ratio_mean_db": None}
    c, x = co[ok].astype(np.float64), cross[ok].astype(np.float64)
    rvi = np.clip(4.0 * x / (c + x), 0.0, 1.0)
    cpr_db = 10.0 * np.log10(np.clip(x / c, 1e-4, 10.0))
    return {
        "rvi_mean": round(float(rvi.mean()), 3),
        "rvi_median": round(float(np.median(rvi)), 3),
        "cross_pol_ratio_mean_db": round(float(cpr_db.mean()), 2),
    }


def thresholds_dict(th: ScatteringThresholds = DEFAULT_THRESHOLDS) -> dict[str, float]:
    return asdict(th)
