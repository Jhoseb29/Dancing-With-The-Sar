"""Deterministic geographic & seasonal context, so the interpreter never has to guess *where* or *when*."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    bbox: tuple[float, float, float, float]  # minLon, minLat, maxLon, maxLat
    aliases: tuple[str, ...] = field(default_factory=tuple)  # lowercase substrings of a place name
    landmarks: tuple[str, ...] = field(default_factory=tuple)
    wet_months: tuple[int, ...] = (12, 1, 2, 3)
    dry_months: tuple[int, ...] = (5, 6, 7, 8, 9, 10)


REGIONS: tuple[Region, ...] = (
    Region(
        key="cochabamba_basin",
        name="Cuenca de Cochabamba (Bolivia)",
        bbox=(-66.54, -17.87, -65.57, -17.18),
        aliases=("cochabamba", "valle central", "río rocha", "rio rocha"),
        landmarks=(
            "Cordillera y Parque Nacional Tunari (norte): laderas, cuencas altas, torrenteras",
            "Conurbación metropolitana: Cochabamba, Sacaba, Quillacollo, Colcapirhua, Tiquipaya",
            "Eje hídrico: Río Rocha; lagunas Alalay, La Angostura y Coña Coña",
        ),
    ),
    Region(
        key="chiquitania",
        name="Chiquitania (Santa Cruz, Bolivia)",
        bbox=(-61.6, -17.2, -60.1, -15.8),
        aliases=("chiquitania", "chiquitanía", "san ignacio de velasco", "concepción", "concepcion"),
        landmarks=(
            "Bosque seco chiquitano: ecosistema de transición con alta recurrencia de incendios",
            "Centros poblados: San Ignacio de Velasco, Concepción, San Rafael",
            "Frontera agrícola y ganadera con chaqueos estacionales",
        ),
        wet_months=(11, 12, 1, 2, 3),
        dry_months=(5, 6, 7, 8, 9),
    ),
)


def bbox_overlap_fraction(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Fraction of bbox `a` covered by bbox `b`."""
    w, s = max(a[0], b[0]), max(a[1], b[1])
    e, n = min(a[2], b[2]), min(a[3], b[3])
    if e <= w or n <= s:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    return round((e - w) * (n - s) / area_a, 4) if area_a > 0 else 0.0


def matching_regions(bbox: tuple[float, ...] | None) -> list[dict]:
    if not bbox:
        return []
    out = []
    for r in REGIONS:
        overlap = bbox_overlap_fraction(r.bbox, bbox)
        if overlap > 0:
            out.append({"key": r.key, "name": r.name, "region_covered_fraction": overlap,
                        "landmarks": list(r.landmarks)})
    return out


def season_for(month: int, region_key: str | None = None) -> str | None:
    """Season only where we have a curated rainfall calendar; elsewhere None (never guess)."""
    region = next((r for r in REGIONS if r.key == region_key), None)
    if region is None:
        return None
    if month in region.wet_months:
        return "epoca_de_lluvias"
    if month in region.dry_months:
        return "epoca_seca"
    return "transicion"
