"""Sentinel-1 catalog (OPERA L2 RTC-S1 via NASA CMR): bursts grouped into acquisitions.

OPERA delivers one granule per ~20x90 km *burst* (VV, VH and a layover/shadow mask as COGs).
A satellite pass over the AOI is the set of bursts with the same relative orbit (track) and
day. That group becomes one `Granule(sensor="sentinel-1")`, so selection, processing and the globe treat
it exactly like a NISAR granule.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import requests
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .catalog import CatalogQuery, CatalogResult, Granule
from .sensors import SENTINEL1
from .settings import Settings

log = logging.getLogger("nisar.catalog.sentinel1")

UMM_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
ASSET_SUFFIXES = {"VV": "_VV.tif", "VH": "_VH.tif", "mask": "_mask.tif"}


def search_sentinel1(query: CatalogQuery, settings: Settings, max_bursts: int = 2000) -> CatalogResult:
    params: dict[str, Any] = {
        "short_name": list(SENTINEL1.collections),
        "page_size": min(max_bursts, 2000),
        "sort_key": "-start_date",
    }
    if query.bbox:
        params["bounding_box"] = ",".join(str(v) for v in query.bbox)
    if query.temporal:
        params["temporal"] = query.temporal
    resp = requests.get(UMM_URL, params=params, headers={"Client-Id": settings.cmr_client_id}, timeout=60)
    resp.raise_for_status()
    bursts = [b for b in (_parse_burst(item["umm"]) for item in resp.json().get("items", [])) if b]
    acquisitions = _group(bursts)
    log.info("CMR Sentinel-1: %d bursts -> %d pasadas", len(bursts), len(acquisitions))
    return CatalogResult(query, len(acquisitions), acquisitions[: query.limit],
                         datetime.now(timezone.utc).isoformat())


def _attr(umm: dict[str, Any], name: str) -> list[str]:
    return next((a.get("Values", []) for a in umm.get("AdditionalAttributes", []) if a.get("Name") == name), [])


def _size_mb(umm: dict[str, Any]) -> float | None:
    """Total size of the burst files (UMM lists each file in bytes or with a unit)."""
    total = 0.0
    for info in umm.get("DataGranule", {}).get("ArchiveAndDistributionInformation", []):
        if info.get("SizeInBytes"):
            total += info["SizeInBytes"] / 1e6
        elif info.get("Size"):
            total += float(info["Size"]) * {"KB": 1e-3, "MB": 1.0, "GB": 1e3}.get(info.get("SizeUnit", "MB"), 1.0)
    return round(total, 2) or None


def _parse_burst(umm: dict[str, Any]) -> dict[str, Any] | None:
    urls = [u.get("URL", "") for u in umm.get("RelatedUrls", [])]
    asset: dict[str, Any] = {}
    for key, suffix in ASSET_SUFFIXES.items():
        https = next((u for u in urls if u.startswith("https") and u.endswith(suffix)), None)
        s3 = next((u for u in urls if u.startswith("s3://") and u.endswith(suffix)), None)
        if https or s3:
            asset[key] = {"https": https, "s3": s3}
    if "VV" not in asset:
        return None
    try:
        points = umm["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["GPolygons"][0]["Boundary"]["Points"]
        ring = [[p["Longitude"], p["Latitude"]] for p in points]
    except (KeyError, IndexError):
        ring = []
    start = umm.get("TemporalExtent", {}).get("RangeDateTime", {}).get("BeginningDateTime", "")
    platform = next((p.get("ShortName") for p in umm.get("Platforms", [])), "Sentinel-1")
    return {
        "id": umm.get("GranuleUR"),
        "time_start": start,
        "track": (_attr(umm, "PATH_NUMBER") or [None])[0],
        "direction": (_attr(umm, "ASCENDING_DESCENDING") or [""])[0].capitalize() or None,
        "pols": _attr(umm, "POLARIZATION"),
        "platform": platform,
        "size_mb": _size_mb(umm),
        "footprint": ring,
        **asset,
    }


def _group(bursts: list[dict[str, Any]]) -> list[Granule]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for b in bursts:
        groups[(b["track"], b["time_start"][:10], b["platform"])].append(b)
    out = []
    for (track, day, platform), members in groups.items():
        members.sort(key=lambda b: b["time_start"])
        polys = [Polygon(b["footprint"]).buffer(0) for b in members if len(b["footprint"]) >= 3]
        union = unary_union(polys) if polys else None
        hull = list(union.convex_hull.exterior.coords) if union is not None and not union.is_empty else []
        pols = sorted({p for b in members for p in b["pols"]})
        out.append(Granule(
            granule_id=f"OPERA_RTC-S1_T{int(track):03d}_{members[0]['time_start'][:19].replace('-', '').replace(':', '')}_"
                       f"{platform.replace('Sentinel-', 'S')}" if track else members[0]["id"],
            collection=SENTINEL1.collections[0],
            time_start=members[0]["time_start"],
            time_end=members[-1]["time_start"],
            size_mb=round(sum(b["size_mb"] or 0 for b in members), 1),
            https_url=None,
            s3_url=None,
            browse_url=None,
            footprint=[[round(x, 5), round(y, 5)] for x, y in hull],
            track=f"{int(track):03d}" if track else None,
            orbit_direction=members[0]["direction"],
            polarization_mode="DV" if {"VV", "VH"} <= set(pols) else ("SV" if "VV" in pols else "+".join(pols)),
            sensor=SENTINEL1.key,
            assets=[{k: b[k] for k in ("id", "footprint", "VV", "VH", "mask") if k in b} for b in members],
        ))
    return sorted(out, key=lambda g: g.time_start, reverse=True)
