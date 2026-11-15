"""When did the radar last look at Cochabamba, and when will it look again?

Radar confirms after the fact (water / new sediment) but satellites only pass every few days.
From NASA CMR we take the recent acquisitions over the area and, per orbit track, add the
repeat cycle (12 days for NISAR and for each Sentinel-1 unit) to estimate the next pass.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
REPEAT_DAYS = 12
MISSIONS = {
    # NISAR_L2_PR_GCOV_<cycle>_<track>_<A|D>_...  /  OPERA_L2_RTC-S1_T<track>-..._<S1C|S1D>_30_...
    "NISAR": {"short_name": "NISAR_L2_GCOV_V1", "track": re.compile(r"GCOV_\d{3}_(\d{3}_[AD])_")},
    "Sentinel-1": {"short_name": "OPERA_L2_RTC-S1_V1", "track": re.compile(r"_T(\d{3})-.*_(S1[A-D])_")},
}


def _granules(short_name: str, bbox: tuple[float, ...], since: date) -> list[dict[str, Any]]:
    params = {"short_name": short_name, "bounding_box": ",".join(map(str, bbox)),
              "temporal": f"{since.isoformat()}T00:00:00Z,", "sort_key": "-start_date", "page_size": 200}
    return requests.get(CMR, params=params, timeout=60).json()["feed"]["entry"]


def schedule(bbox: tuple[float, ...], today: date | None = None, lookback_days: int = 40) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    out = {}
    for mission, cfg in MISSIONS.items():
        try:
            entries = _granules(cfg["short_name"], bbox, today - timedelta(days=lookback_days))
        except (requests.RequestException, ValueError, KeyError):
            out[mission] = {"ultima": None, "proxima_estimada": None, "error": "CMR no respondió"}
            continue
        last_by_track: dict[str, date] = {}
        for e in entries:
            m = cfg["track"].search(e.get("producer_granule_id") or e.get("title", ""))
            track = "-".join(m.groups()) if m else "?"  # one repeat cycle per track (and per S1 unit)
            d = date.fromisoformat(e["time_start"][:10])
            last_by_track[track] = max(d, last_by_track.get(track, d))
        nexts = []
        for d in last_by_track.values():
            n = d + timedelta(days=REPEAT_DAYS)
            while n <= today:
                n += timedelta(days=REPEAT_DAYS)
            nexts.append(n)
        dates = sorted({date.fromisoformat(e["time_start"][:10]) for e in entries}, reverse=True)
        out[mission] = {"ultima": dates[0].isoformat() if dates else None,
                        "recientes": [d.isoformat() for d in dates[:6]],
                        "proxima_estimada": min(nexts).isoformat() if nexts else None,
                        "ciclo_dias": REPEAT_DAYS}
    return out
