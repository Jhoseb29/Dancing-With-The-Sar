"""Deterministic change detection between the oldest and newest analysed dates.

The interpreter receives ready-made deltas + comparability flags instead of
having to subtract numbers itself (cheaper and never wrong).
"""
from __future__ import annotations

from typing import Any

# Minimum |delta| considered meaningful (below ≈ radiometric/classification noise)
SIGNIFICANT = {"pct": 3.0, "db": 1.0, "rvi": 0.05}


def flat_metrics(m: dict[str, Any]) -> dict[str, float | None]:
    """One flat dict per date with the numbers the themes talk about."""
    flat: dict[str, float | None] = dict(m.get("physical_scattering_breakdown", {}))
    flat["mean_db"] = m.get("statistical_distribution_db", {}).get("mean_db")
    flat["rvi_mean"] = m.get("polarimetric_indices", {}).get("rvi_mean")
    flat["cross_pol_ratio_mean_db"] = m.get("polarimetric_indices", {}).get("cross_pol_ratio_mean_db")
    for term, dist in (m.get("per_polarization_db") or {}).items():
        flat[f"{term}_mean_db"] = dist.get("mean_db")
    radar = m.get("radar_physics", {})
    for alias, term in (("co_mean_db", radar.get("primary_polarization")), ("cross_mean_db", radar.get("cross_polarization"))):
        if term and f"{term}_mean_db" in flat:
            flat[alias] = flat[f"{term}_mean_db"]
    return flat


def _kind(key: str) -> str:
    if key.endswith("_pct"):
        return "pct"
    if key.startswith("rvi"):
        return "rvi"
    return "db"


def compare(oldest: dict[str, Any], newest: dict[str, Any]) -> dict[str, Any]:
    a, b = flat_metrics(oldest), flat_metrics(newest)
    deltas, significant = {}, []
    for key in sorted(set(a) & set(b)):
        if a[key] is None or b[key] is None:
            continue
        d = round(b[key] - a[key], 3)
        deltas[key] = {"before": a[key], "after": b[key], "delta": d}
        if abs(d) >= SIGNIFICANT[_kind(key)]:
            significant.append(key)

    acq_a, acq_b = oldest["acquisition"], newest["acquisition"]
    same_geometry = (acq_a.get("track"), acq_a.get("orbit_pass_direction")) == \
                    (acq_b.get("track"), acq_b.get("orbit_pass_direction"))
    same_version = acq_a.get("product_version") == acq_b.get("product_version")
    caveats = []
    if not same_geometry:
        caveats.append("Distinta órbita/track: diferencias de geometría de observación, no solo del terreno.")
    if not same_version:
        caveats.append(f"Versiones de producto distintas ({acq_a.get('product_version')} → "
                       f"{acq_b.get('product_version')}): parte del cambio puede ser calibración.")
    co_shift = [deltas[k]["delta"] for k in ("co_mean_db", "cross_mean_db") if k in deltas]
    if len(co_shift) >= 2 and all(abs(x) >= 0.8 for x in co_shift) and max(co_shift) - min(co_shift) < 0.5:
        caveats.append("Desplazamiento casi uniforme en todas las polarizaciones: típico de calibración o "
                       "humedad generalizada, no de un cambio localizado.")
    return {
        "from_date": (acq_a.get("start_time") or "")[:10],
        "to_date": (acq_b.get("start_time") or "")[:10],
        "comparable": same_geometry,
        "deltas": deltas,
        "significant_changes": significant,
        "caveats": caveats,
        "significance_thresholds": SIGNIFICANT,
    }


def change_summary(metrics_by_date: list[dict[str, Any]]) -> dict[str, Any] | None:
    """metrics_by_date sorted oldest -> newest."""
    if len(metrics_by_date) < 2:
        return None
    return compare(metrics_by_date[0], metrics_by_date[-1])
