"""Which granules to analyse: best AOI coverage first, then the widest comparable time baseline.

Rules (deterministic):
  1. Coverage = area(footprint ∩ AOI) / area(AOI), from the CMR footprint polygon.
  2. Granules are grouped by acquisition geometry (track + pass direction): only takes from
     the same geometry are comparable pixel by pixel.
  3. The chosen group is the one whose takes cover the AOI best (dual-pol preferred, so HV
     and RVI exist), ties broken by the most recent acquisition.
  4. Inside the group: one date -> the newest; N dates -> newest + oldest (widest baseline,
     e.g. before/after a fire season) + evenly spaced takes in between.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .catalog import Granule

COVERAGE_STEP = 0.1  # coverages within 10 % are considered equivalent (then recency decides)


@dataclass
class Choice:
    granules: list[Granule]
    coverage: dict[str, float]  # granule_id -> fraction of the AOI covered
    group: str  # "track 060 Ascending"


def coverage(granule: Granule, aoi: tuple[float, float, float, float] | None) -> float:
    if not aoi:
        return 1.0
    area = box(*aoi)
    try:
        if granule.assets:  # Sentinel-1: union of the real burst footprints (no convex-hull overestimate)
            footprint = unary_union([Polygon(a["footprint"]).buffer(0) for a in granule.assets
                                     if len(a.get("footprint") or []) >= 3])
        elif len(granule.footprint) >= 3:
            footprint = Polygon(granule.footprint).buffer(0)
        else:
            return 0.0
    except ValueError:
        return 0.0
    return round(footprint.intersection(area).area / area.area, 3) if area.area else 0.0


def _evenly(items: list[Granule], count: int) -> list[Granule]:
    """items newest-first -> newest, oldest and evenly spaced in between (newest first)."""
    if count <= 1 or len(items) <= 1:
        return items[:1]
    if len(items) <= count:
        return items
    idx = sorted({round(i * (len(items) - 1) / (count - 1)) for i in range(count)})
    return [items[i] for i in idx]


def choose(granules: list[Granule], count: int, aoi: tuple[float, float, float, float] | None,
           ids: list[str] | None = None) -> Choice:
    cover = {g.granule_id: coverage(g, aoi) for g in granules}
    if ids:
        picked = [g for g in granules if g.granule_id in ids]
        return Choice(picked, {g.granule_id: cover[g.granule_id] for g in picked}, "manual")
    if not granules:
        return Choice([], {}, "")

    groups: dict[tuple, list[Granule]] = defaultdict(list)
    for g in granules:  # CMR order: newest first
        groups[(g.track, g.orbit_direction)].append(g)

    def score(key: tuple) -> tuple:
        takes = groups[key]
        best = max(cover[g.granule_id] for g in takes)
        dual = any((g.polarization_mode or "").startswith("D") for g in takes)
        return (round(best / COVERAGE_STEP), dual, min(len(takes), count), takes[0].time_start)

    key = max(groups, key=score)
    takes = groups[key]
    if any((g.polarization_mode or "").startswith("D") for g in takes):
        takes = [g for g in takes if (g.polarization_mode or "").startswith("D")]  # HV/RVI comparable
    picked = _evenly(takes, count)
    return Choice(picked, {g.granule_id: cover[g.granule_id] for g in picked}, f"track {key[0]} {key[1]}")
