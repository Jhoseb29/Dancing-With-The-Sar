"""NASA CMR catalog search for NISAR GCOV granules."""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from .settings import DEFAULT_COLLECTIONS, Settings

log = logging.getLogger("nisar.catalog")

# NISAR_L2_PR_GCOV_<cycle>_<track>_<dir>_<frame>_... e.g. ..._034_017_A_169_...
_NAME_RE = re.compile(r"GCOV_(?P<cycle>\d{3})_(?P<track>\d{3})_(?P<dir>[AD])_(?P<frame>\d{3})_\d{4}_(?P<pol>[A-Z]{4})")


@dataclass
class CatalogQuery:
    bbox: tuple[float, float, float, float] | None
    temporal: str | None = None
    collections: tuple[str, ...] = DEFAULT_COLLECTIONS
    limit: int = 10


@dataclass
class Granule:
    granule_id: str
    collection: str | None
    time_start: str
    time_end: str
    size_mb: float | None
    https_url: str | None
    s3_url: str | None
    browse_url: str | None
    footprint: list[list[float]] = field(default_factory=list)  # [[lon, lat], ...]
    track: str | None = None
    frame: str | None = None
    orbit_direction: str | None = None
    polarization_mode: str | None = None
    sensor: str = "nisar"  # "nisar" | "sentinel-1" (lib/sensors.py)
    # Sentinel-1: one acquisition = several bursts; each asset is
    # {"id", "footprint", "VV": {"https", "s3"}, "VH": {...}, "mask": {...}}
    assets: list[dict[str, Any]] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"{self.granule_id}.h5"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Granule:
        values = {k: data[k] for k in cls.__dataclass_fields__ if k in data and data[k] is not None}
        return cls(**{"collection": None, "time_end": "", "size_mb": None, "https_url": None, "s3_url": None,
                      "browse_url": None, **values})


@dataclass
class CatalogResult:
    query: CatalogQuery
    total_hits: int
    granules: list[Granule]
    searched_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "searched_at": self.searched_at,
            "query": asdict(self.query),
            "total_hits": self.total_hits,
            "granules_returned": len(self.granules),
            "granules": [g.to_dict() for g in self.granules],
        }


def search_granules(query: CatalogQuery, settings: Settings) -> CatalogResult:
    params: dict[str, Any] = {
        "short_name": list(query.collections),
        "page_size": min(max(query.limit, 1), 2000),
        "sort_key": "-start_date",
    }
    if query.bbox:
        params["bounding_box"] = ",".join(str(v) for v in query.bbox)
    if query.temporal:
        params["temporal"] = query.temporal

    resp = requests.get(
        settings.cmr_url, params=params, headers={"Client-Id": settings.cmr_client_id}, timeout=30
    )
    resp.raise_for_status()
    entries = resp.json().get("feed", {}).get("entry", [])
    granules = _deduplicate([_parse_entry(e) for e in entries], query.collections)
    total = int(resp.headers.get("CMR-Hits", len(entries)))
    log.info("CMR: %d coincidencias, %d gránulos únicos recuperados", total, len(granules))
    return CatalogResult(query, total, granules, datetime.now(timezone.utc).isoformat())


def _parse_entry(entry: dict[str, Any]) -> Granule:
    hrefs = [link.get("href", "") for link in entry.get("links", [])]
    https = next((h for h in hrefs if h.startswith("http") and h.endswith(".h5")), None)
    s3 = next((h for h in hrefs if h.startswith("s3://") and h.endswith(".h5")), None)
    browse = next((h for h in hrefs if h.startswith("http") and h.lower().endswith((".png", ".jpg"))), None)
    title = entry.get("title", "")
    name = _NAME_RE.search(title)
    size = entry.get("granule_size")
    return Granule(
        granule_id=title,
        collection=_collection_from_url(https or s3),
        time_start=entry.get("time_start", ""),
        time_end=entry.get("time_end", ""),
        size_mb=round(float(size), 2) if size not in (None, "") else None,
        https_url=https,
        s3_url=s3,
        browse_url=browse,
        footprint=_parse_footprint(entry),
        track=name["track"] if name else None,
        frame=name["frame"] if name else None,
        orbit_direction={"A": "Ascending", "D": "Descending"}.get(name["dir"]) if name else None,
        polarization_mode=name["pol"] if name else None,
    )


def _collection_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/(NISAR_L2_GCOV_[A-Z0-9_]+)/", url)
    return match.group(1) if match else None


def _parse_footprint(entry: dict[str, Any]) -> list[list[float]]:
    """CMR polygons are 'lat lon lat lon ...'; boxes are 'S W N E'."""
    polygons = entry.get("polygons") or []
    if polygons and polygons[0]:
        nums = [float(v) for v in polygons[0][0].split()]
        return [[nums[i + 1], nums[i]] for i in range(0, len(nums) - 1, 2)]
    boxes = entry.get("boxes") or []
    if boxes:
        s, w, n, e = (float(v) for v in boxes[0].split())
        return [[w, s], [e, s], [e, n], [w, n], [w, s]]
    return []


def _deduplicate(granules: list[Granule], preference: tuple[str, ...]) -> list[Granule]:
    """Same acquisition (track/frame/start) may exist in several maturity collections: keep the best."""
    rank = {name: i for i, name in enumerate(preference)}
    best: dict[tuple, Granule] = {}
    for g in granules:
        key = (g.track, g.frame, g.time_start[:19]) if g.track else (g.granule_id,)
        current = best.get(key)
        if current is None or rank.get(g.collection, 99) < rank.get(current.collection, 99):
            best[key] = g
    return sorted(best.values(), key=lambda g: g.time_start, reverse=True)
