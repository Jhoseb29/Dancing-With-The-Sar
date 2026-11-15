"""Catálogo público real de NISAR (NASA CMR) sobre la Cuenca de Cochabamba.

Consulta sin credenciales `cmr.earthdata.nasa.gov` para inventariar gránulos reales
GCOV y GUNW (VALIDATED, PROVISIONAL, BETA), registra track/frame/órbita/madurez y
persiste el manifiesto CSV en `data/manifests/nisar_cochabamba.csv`.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from modules.basin_risk.domain.zones import BASIN_BBOX

log = logging.getLogger("basin_risk.nisar_cmr")

CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
CACHE_TTL_HOURS = 6

NISAR_COLLECTIONS: tuple[tuple[str, str, str], ...] = (
    ("NISAR_L2_GCOV_V1", "GCOV", "VALIDATED"),
    ("NISAR_L2_GCOV_PROVISIONAL_V1", "GCOV", "PROVISIONAL"),
    ("NISAR_L2_GCOV_BETA_V1", "GCOV", "BETA"),
    ("NISAR_L2_GUNW_V1", "GUNW", "VALIDATED"),
    ("NISAR_L2_GUNW_PROVISIONAL_V1", "GUNW", "PROVISIONAL"),
)

# Ej: NISAR_L2_PR_GCOV_034_017_A_169_2005_DHDH_A_20261025T101543_...
_GCOV_RE = re.compile(
    r"NISAR_L2_(?:PR_)?(?P<product>GCOV|GUNW)_(?P<cycle>\d+)_(?P<track>\d+)_(?P<dir>[AD])_(?P<frame>\d+)_\d+_(?P<pol>[A-Z]+)"
)


class NisarCmrProvider:
    def __init__(self, manifests_dir: Path, ui_config_dir: Path) -> None:
        self._manifests_dir = manifests_dir
        self._ui_config_dir = ui_config_dir
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def verified_gibs_dates(self) -> list[str]:
        events_file = self._ui_config_dir / "events.json"
        if not events_file.is_file():
            return []
        data = json.loads(events_file.read_text(encoding="utf-8"))
        radar = next((e for e in data.get("events", []) if e.get("id") == "radar"), None)
        if not radar:
            return []
        dates = {
            v["date"]
            for v in radar.get("verifiedDates", [])
            if v.get("placeId") in ("cochabamba-basin", "cochabamba-city")
        }
        return sorted(dates, reverse=True)

    async def catalog(self) -> dict[str, Any]:
        cache_file = self._manifests_dir / f"nisar_cochabamba_{date.today().isoformat()}.json"
        if cache_file.is_file():
            age_h = (datetime.now(timezone.utc).timestamp() - cache_file.stat().st_mtime) / 3600.0
            if age_h < CACHE_TTL_HOURS:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if "opera_dswx_dates" in cached and "sar_change_default" in cached:
                    return cached

        bbox_str = ",".join(str(v) for v in BASIN_BBOX)

        async def _fetch(short_name: str, product: str, maturity: str) -> list[dict[str, Any]]:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(
                        CMR_GRANULES_URL,
                        params={
                            "short_name": short_name,
                            "bounding_box": bbox_str,
                            "page_size": 25,
                            "sort_key": "-start_date",
                        },
                    )
                resp.raise_for_status()
                entries = resp.json().get("feed", {}).get("entry", [])
                return [_parse_entry(e, short_name, product, maturity) for e in entries]
            except Exception as exc:
                log.warning("CMR %s falló: %s", short_name, exc)
                return []

        groups = await asyncio.gather(*(_fetch(sn, pr, mt) for sn, pr, mt in NISAR_COLLECTIONS))
        granules = [item for sub in groups for item in sub]
        granules.sort(key=lambda g: g.get("date") or "", reverse=True)

        opera_dates = await self._fetch_opera_dswx_dates(bbox_str)
        self._write_csv(granules)
        gibs_dates = self.verified_gibs_dates()

        by_maturity: dict[str, int] = {}
        by_product: dict[str, int] = {}
        tracks: set[str] = set()
        for g in granules:
            by_maturity[g["maturity"]] = by_maturity.get(g["maturity"], 0) + 1
            by_product[g["product"]] = by_product.get(g["product"], 0) + 1
            if g.get("track") and g.get("frame"):
                tracks.add(f"T{g['track']}/F{g['frame']} ({g['direction']})")

        sar_default = None
        if len(gibs_dates) >= 2:
            sar_default = {"before_day": gibs_dates[-1], "after_day": gibs_dates[0], "sensor": "NISAR GCOV"}
        elif len(opera_dates) >= 2:
            sar_default = {"before_day": opera_dates[-1], "after_day": opera_dates[0], "sensor": "OPERA DSWx-S1"}
        elif gibs_dates:
            sar_default = {"before_day": gibs_dates[0], "after_day": gibs_dates[0], "sensor": "NISAR GCOV"}

        result = {
            "source": "NASA CMR (public granule search)",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total_granules": len(granules),
            "by_product": by_product,
            "by_maturity": by_maturity,
            "tracks_frames": sorted(tracks),
            "verified_gibs_dates": gibs_dates,
            "opera_dswx_dates": opera_dates,
            "sar_change_default": sar_default,
            "latest_granule": granules[0] if granules else None,
            "granules": granules[:20],
        }
        self._manifests_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result

    async def _fetch_opera_dswx_dates(self, bbox_str: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(
                    CMR_GRANULES_URL,
                    params={
                        "short_name": "OPERA_L3_DSWX-S1_V1",
                        "bounding_box": bbox_str,
                        "page_size": 30,
                        "sort_key": "-start_date",
                    },
                )
            r.raise_for_status()
            dates = {str(e.get("time_start", ""))[:10] for e in r.json().get("feed", {}).get("entry", [])}
            return sorted((d for d in dates if len(d) == 10), reverse=True)[:10]
        except Exception as exc:
            log.warning("CMR OPERA_L3_DSWX-S1_V1 falló: %s", exc)
            return []

    def _write_csv(self, granules: list[dict[str, Any]]) -> None:
        self._manifests_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self._manifests_dir / "nisar_cochabamba.csv"
        fieldnames = ["date", "product", "maturity", "collection", "track", "frame", "direction", "pol", "title"]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for g in granules:
                writer.writerow({k: g.get(k, "") for k in fieldnames})


def _parse_entry(entry: dict[str, Any], collection: str, product: str, maturity: str) -> dict[str, Any]:
    title = str(entry.get("title") or "")
    m = _GCOV_RE.search(title)
    return {
        "title": title,
        "date": str(entry.get("time_start") or "")[:10],
        "product": product,
        "maturity": maturity,
        "collection": collection,
        "track": m.group("track") if m else "",
        "frame": m.group("frame") if m else "",
        "direction": m.group("dir") if m else "",
        "pol": m.group("pol") if m else "",
    }
