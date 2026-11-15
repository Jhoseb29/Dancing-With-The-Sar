"""Cliente real de precipitación NASA (GPM IMERG Late 0.1° vía OPeNDAP + respaldo NASA POWER).

- Si Earthdata Login está operativo (`EARTHDATA_TOKEN` o `EARTHDATA_USERNAME`/`PASSWORD`),
  descarga el subconjunto espacial 0.1° (~11 km) de `GPM_3IMERGDL` v07 sobre Cochabamba
  para diferenciar lluvia entre Tunari, Piedemonte, Valle del Rocha y Zona Sur.
- Si Earthdata aún requiere verificación/reset de contraseña o no está configurado,
  reporta `earthdata_auth_status` con honestidad y usa la serie diaria pública
  NASA POWER (`PRECTOTCORR`, mm/día) junto con el estado en NASA CMR.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from modules.basin_risk.domain.zones import BASIN_BBOX

log = logging.getLogger("basin_risk.precip")

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
URS_TOKENS_URL = "https://urs.earthdata.nasa.gov/api/users/tokens"
URS_CREATE_TOKEN_URL = "https://urs.earthdata.nasa.gov/api/users/token"
CACHE_TTL_HOURS = 6
IMERG_GRID_DAYS = 14


class NasaPrecipProvider:
    def __init__(
        self,
        cache_dir: Path,
        earthdata_username: str = "",
        earthdata_password: str = "",
        earthdata_token: str = "",
    ) -> None:
        self._cache_dir = cache_dir
        self._username = earthdata_username.strip()
        self._password = earthdata_password.strip()
        self._static_token = earthdata_token.strip()
        self._auth_checked_at: float = 0.0
        self._auth_status: str = "unconfigured"
        self._bearer_token: str = self._static_token
        self._eula_status: str = "unknown"
        self._eula_url: str | None = None
        self._eula_checked_at: float = 0.0
        self._auth_lock = asyncio.Lock()
        self._eula_lock = asyncio.Lock()

    @property
    def earthdata_configured(self) -> bool:
        return bool(self._static_token or (self._username and self._password))

    async def check_earthdata_auth(self) -> tuple[str, str | None]:
        """Verifica estado Earthdata sin registrar credenciales; cachea 10 minutos."""
        now_ts = datetime.now(timezone.utc).timestamp()
        if self._static_token:
            return "ok", self._static_token
        if not (self._username and self._password):
            return "unconfigured", None
        if now_ts - self._auth_checked_at < 600 and self._auth_status != "unconfigured":
            return self._auth_status, (self._bearer_token or None)

        async with self._auth_lock:
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - self._auth_checked_at < 600 and self._auth_status != "unconfigured":
                return self._auth_status, (self._bearer_token or None)
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    r = await client.get(URS_TOKENS_URL, auth=(self._username, self._password))
                self._auth_checked_at = now_ts
                if r.status_code == 200:
                    tokens = r.json() if r.content else []
                    tok = tokens[0].get("access_token") if tokens else None
                    if not tok:
                        async with httpx.AsyncClient(timeout=20.0) as client:
                            rc = await client.post(URS_CREATE_TOKEN_URL, auth=(self._username, self._password))
                        if rc.status_code == 200:
                            tok = rc.json().get("access_token")
                    self._auth_status = "ok"
                    self._bearer_token = tok or ""
                    return self._auth_status, (self._bearer_token or None)

                body_lower = r.text.lower()
                if r.status_code == 401 and ("reset your password" in body_lower or "invalid_account_status" in body_lower):
                    self._auth_status = "password_reset_required"
                else:
                    self._auth_status = "invalid_credentials"
                self._bearer_token = ""
                return self._auth_status, None
            except Exception as exc:
                log.warning("Verificación Earthdata URS falló: %s", exc)
                return "unreachable", None

    async def daily_series(self, zone_id: str, lon: float, lat: float, days: int = 60) -> dict[str, Any]:
        power = await self._fetch_power_series(zone_id, lon, lat, days)
        auth_status, token = await self.check_earthdata_auth()
        if auth_status != "ok" or not token:
            return power

        # Enriquecer últimos días con grilla 0.1° real de GPM_3IMERGDL si Earthdata responde.
        imerg_points = await self._recent_imerg_points(lon, lat, token, limit_days=IMERG_GRID_DAYS)
        if not imerg_points:
            return power

        by_date = {item["date"]: float(item["mm"]) for item in power["series"]}
        by_date.update(imerg_points)
        merged = [{"date": d, "mm": round(v, 2)} for d, v in sorted(by_date.items())][-days:]
        return {
            **power,
            "source": "GPM IMERG Late (0.1° ~11 km) + NASA POWER PRECTOTCORR",
            "imerg_spatial_active": True,
            "series": merged,
            "summary": _summarize(merged),
        }

    async def _fetch_power_series(self, zone_id: str, lon: float, lat: float, days: int) -> dict[str, Any]:
        today = date.today()
        start = today - timedelta(days=max(days, 35))
        cache_file = self._cache_dir / f"power_{zone_id}_{start.isoformat()}_{today.isoformat()}.json"

        if cache_file.is_file():
            age_h = (datetime.now(timezone.utc).timestamp() - cache_file.stat().st_mtime) / 3600.0
            if age_h < CACHE_TTL_HOURS:
                return json.loads(cache_file.read_text(encoding="utf-8"))

        params = {
            "parameters": "PRECTOTCORR",
            "community": "AG",
            "longitude": f"{lon:.4f}",
            "latitude": f"{lat:.4f}",
            "start": start.strftime("%Y%m%d"),
            "end": today.strftime("%Y%m%d"),
            "format": "JSON",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(POWER_URL, params=params)
        resp.raise_for_status()
        payload = resp.json()
        raw_map: dict[str, float] = payload.get("properties", {}).get("parameter", {}).get("PRECTOTCORR", {})

        series: list[dict[str, Any]] = []
        for k in sorted(raw_map):
            val = float(raw_map[k])
            if val <= -900.0:  # -999 = dato aún pendiente en NASA POWER
                continue
            iso = f"{k[:4]}-{k[4:6]}-{k[6:8]}"
            series.append({"date": iso, "mm": round(max(0.0, val), 2)})

        series = series[-days:]
        result = {
            "zone_id": zone_id,
            "lon": lon,
            "lat": lat,
            "source": "NASA POWER · PRECTOTCORR (0.5° respaldo diario)",
            "imerg_spatial_active": False,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "series": series,
            "summary": _summarize(series),
        }
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result

    async def _recent_imerg_points(self, lon: float, lat: float, token: str, limit_days: int = 14) -> dict[str, float]:
        async with self._eula_lock:
            now_ts = datetime.now(timezone.utc).timestamp()
            if self._eula_status == "eula_required" and (now_ts - self._eula_checked_at) < 300:
                return {}

            bbox_str = ",".join(str(v) for v in BASIN_BBOX)
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    r = await client.get(
                        CMR_GRANULES_URL,
                        params={
                            "short_name": "GPM_3IMERGDL",
                            "bounding_box": bbox_str,
                            "page_size": limit_days,
                            "sort_key": "-start_date",
                        },
                    )
                r.raise_for_status()
                entries = r.json().get("feed", {}).get("entry", [])
            except Exception as exc:
                log.warning("CMR GPM_3IMERGDL falló: %s", exc)
                return {}

            if entries and (now_ts - self._eula_checked_at) >= 300:
                data_url = next(
                    (l.get("href") for l in entries[0].get("links", []) if "data.gesdisc.earthdata.nasa.gov" in (l.get("href") or "") and ".nc4" in (l.get("href") or "")),
                    None,
                )
                if data_url:
                    await self._probe_gesdisc_eula(data_url, token)
            if self._eula_status == "eula_required":
                return {}

        sem = asyncio.Semaphore(4)

        async def _one(entry: dict[str, Any]) -> tuple[str, float] | None:
            day = str(entry.get("time_start", ""))[:10]
            odap_url = next(
                (l.get("href") for l in entry.get("links", []) if "opendap.earthdata.nasa.gov" in (l.get("href") or "")),
                None,
            )
            if not day or not odap_url:
                return None
            async with sem:
                grid = await self._load_imerg_grid(day, odap_url, token)
            if not grid:
                return None
            val = _nearest_grid_value(grid, lon, lat)
            return (day, val) if val is not None else None

        items = await asyncio.gather(*(_one(e) for e in entries))
        return {d: v for item in items if item is not None for d, v in [item]}

    async def _probe_gesdisc_eula(self, data_url: str, token: str) -> None:
        self._eula_checked_at = datetime.now(timezone.utc).timestamp()
        try:
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {token}", "Range": "bytes=0-128"},
                follow_redirects=True,
                timeout=15.0,
            ) as client:
                r = await client.get(data_url)
            if r.status_code in (200, 206):
                self._eula_status = "ok"
                self._eula_url = None
                return
            if r.status_code == 403 and "eula" in r.text.lower():
                self._eula_status = "eula_required"
                try:
                    self._eula_url = r.json().get("resolution_url")
                except Exception:
                    self._eula_url = None
                log.warning("GES DISC requiere aprobación EULA en Earthdata (%s)", self._eula_url)
                return
            self._eula_status = f"http_{r.status_code}"
        except Exception as exc:
            log.warning("Sonda GES DISC EULA falló: %s", exc)

    async def _load_imerg_grid(self, day: str, odap_url: str, token: str) -> dict[str, Any] | None:
        cache_file = self._cache_dir / f"imerg_dl_{day}.json"
        if cache_file.is_file():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        # Grilla IMERG 0.1° codificada para OPeNDAP HYRAX/DAP
        subset = quote("precipitation[0:0][1134:1145][720:729],lon[1134:1145],lat[720:729]", safe=",")
        query = f"{odap_url}.ascii?{subset}"
        try:
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {token}"}, follow_redirects=True, timeout=25.0
            ) as client:
                r = await client.get(query)
            if r.status_code != 200:
                return None
            grid = _parse_opendap_ascii(r.text)
            if not grid:
                return None
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(grid), encoding="utf-8")
            return grid
        except Exception as exc:
            log.warning("OPeNDAP GPM_3IMERGDL %s falló: %s", day, exc)
            return None

    async def gpm_catalog_status(self) -> dict[str, Any]:
        """Verifica en NASA CMR los últimos gránulos de GPM IMERG Late/Final y estado Earthdata."""
        auth_status, token = await self.check_earthdata_auth()
        cache_file = self._cache_dir / f"gpm_cmr_{date.today().isoformat()}.json"
        if cache_file.is_file():
            age_h = (datetime.now(timezone.utc).timestamp() - cache_file.stat().st_mtime) / 3600.0
            if age_h < CACHE_TTL_HOURS:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                cached["earthdata_configured"] = self.earthdata_configured
                cached["earthdata_auth_status"] = auth_status
                cached["gesdisc_eula_status"] = self._eula_status
                cached["eula_resolution_url"] = self._eula_url
                return cached

        bbox_str = ",".join(str(v) for v in BASIN_BBOX)
        out: dict[str, Any] = {
            "earthdata_configured": self.earthdata_configured,
            "earthdata_auth_status": auth_status,
            "gesdisc_eula_status": self._eula_status,
            "eula_resolution_url": self._eula_url,
            "collections": {},
        }

        async def _query(short_name: str) -> dict[str, Any]:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    r = await client.get(
                        CMR_GRANULES_URL,
                        params={
                            "short_name": short_name,
                            "bounding_box": bbox_str,
                            "page_size": 3,
                            "sort_key": "-start_date",
                        },
                    )
                r.raise_for_status()
                entries = r.json().get("feed", {}).get("entry", [])
                return {
                    "available_hits": len(entries),
                    "latest_start": (entries[0].get("time_start", "")[:10] if entries else None),
                    "latest_title": (entries[0].get("title") if entries else None),
                }
            except Exception as exc:
                return {"error": str(exc)}

        late, final = await asyncio.gather(_query("GPM_3IMERGDL"), _query("GPM_3IMERGDF"))
        out["collections"] = {"GPM_3IMERGDL": late, "GPM_3IMERGDF": final}
        out["gesdisc_eula_status"] = self._eula_status
        out["eula_resolution_url"] = self._eula_url
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out

    def eula_state(self) -> dict[str, Any]:
        return {
            "gesdisc_eula_status": self._eula_status,
            "eula_resolution_url": self._eula_url,
        }


def _parse_opendap_ascii(text: str) -> dict[str, Any] | None:
    """Extrae lon, lat y matriz precipitation desde respuesta OPeNDAP ASCII."""
    lons: list[float] = []
    lats: list[float] = []
    rows: dict[int, list[float]] = {}
    mode = ""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("precipitation.lon"):
            lons = [float(x) for x in s.split(",", 1)[1].split(",") if x.strip()]
            mode = "lon"
        elif s.startswith("precipitation.lat") or s.startswith("lat["):
            if "," in s and not s.startswith("["):
                lats = [float(x) for x in s.split(",", 1)[1].split(",") if x.strip()]
                mode = "lat"
        elif s.startswith("lon["):
            lons = [float(x) for x in s.split("]", 1)[1].lstrip(",").split(",") if x.strip()]
        elif s.startswith("[0]["):
            m = re.match(r"\[0\]\[(\d+)\],\s*(.+)", s)
            if m:
                idx = int(m.group(1))
                rows[idx] = [float(x) for x in m.group(2).split(",")]
        elif mode == "lat" and re.match(r"^-?\d+(\.\d+)?(,\s*-?\d+(\.\d+)?)*$", s):
            lats.extend(float(x) for x in s.split(","))
    if not lons or not lats or not rows:
        return None
    matrix = [rows[i] for i in sorted(rows)]
    return {"lons": lons, "lats": lats, "values": matrix}


def _nearest_grid_value(grid: dict[str, Any], lon: float, lat: float) -> float | None:
    lons: list[float] = grid["lons"]
    lats: list[float] = grid["lats"]
    matrix: list[list[float]] = grid["values"]
    if not lons or not lats or not matrix:
        return None
    i_lon = min(range(len(lons)), key=lambda i: abs(lons[i] - lon))
    i_lat = min(range(len(lats)), key=lambda j: abs(lats[j] - lat))
    if i_lon >= len(matrix) or i_lat >= len(matrix[i_lon]):
        return None
    val = float(matrix[i_lon][i_lat])
    if val < 0 or val > 1000:
        return None
    return round(val, 2)


def _summarize(series: list[dict[str, Any]]) -> dict[str, Any]:
    if not series:
        return {"latest_date": None, "latest_mm": 0.0, "sum_7d_mm": 0.0, "sum_30d_mm": 0.0, "max_24h_30d_mm": 0.0}
    last7 = series[-7:]
    last30 = series[-30:]
    return {
        "latest_date": series[-1]["date"],
        "latest_mm": round(float(series[-1]["mm"]), 2),
        "sum_7d_mm": round(sum(float(d["mm"]) for d in last7), 2),
        "sum_30d_mm": round(sum(float(d["mm"]) for d in last30), 2),
        "max_24h_30d_mm": round(max(float(d["mm"]) for d in last30), 2),
    }
