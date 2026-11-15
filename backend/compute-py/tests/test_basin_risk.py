"""Pruebas unitarias e integración física para Qucha-SAR (`basin_risk`)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "backend" / "compute-py" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from main import app  # noqa: E402
from modules.basin_risk.adapters.copernicus_dem import CopernicusDemProvider  # noqa: E402
from modules.basin_risk.adapters.dem_hydrology import SUBBASIN_CATALOG, ensure_dem_hydrology  # noqa: E402
from modules.basin_risk.adapters.nasa_precip import _parse_opendap_ascii  # noqa: E402
from modules.basin_risk.adapters.satellite_pipeline import (  # noqa: E402
    compute_opera_delta_png,
    compute_sar_change_png,
)
from modules.basin_risk.domain.zones import (  # noqa: E402
    BasinZone,
    build_subsystems_summary,
    evaluate_zone_risk,
)


def _solid_png(rgb: tuple[int, int, int, int], size: int = 16) -> bytes:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[:, :] = rgb
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def test_dem_hydrology_generates_9_real_subbasins() -> None:
    dem_path = REPO_ROOT / "data" / "processed" / "cog" / "cochabamba_copernicus_dem_30m.tif"
    hydro_dir = REPO_ROOT / "data" / "processed" / "hydro"
    hydro = ensure_dem_hydrology(dem_path, hydro_dir)

    assert len(hydro.subbasins) == len(SUBBASIN_CATALOG) == 9
    subsystems = {sb.subsystem for sb in hydro.subbasins}
    assert subsystems == {"north", "central", "south"}
    for sb in hydro.subbasins:
        assert sb.area_km2 > 10.0
        assert sb.geometry["type"] in ("Polygon", "MultiPolygon")

    pt = hydro.point_hydro(-66.1568, -17.3936)
    assert pt["subbasin_id"] is not None
    assert isinstance(pt["twi"], float)


def test_copernicus_polygon_stats_and_point_endpoint() -> None:
    dem_path = REPO_ROOT / "data" / "processed" / "cog" / "cochabamba_copernicus_dem_30m.tif"
    dem = CopernicusDemProvider(dem_path)
    stats = dem.all_polygon_stats()
    assert len(stats) == 9
    assert stats["norte-taquina-pintumayu"]["above_2750_pct"] > 50.0
    assert stats["norte-taquina-pintumayu"]["steep_pct_gt25"] > 5.0
    assert "twi_p90" in stats["centro-rocha-cercado"]

    client = TestClient(app)
    res = client.get("/api/basin/point", params={"lon": -66.1568, "lat": -17.3936})
    assert res.status_code == 200
    body = res.json()
    assert body["inside_basin"] is True
    assert body["dem"]["elevation_m"] > 2400.0
    assert "sar_terrain_caution" in body["dem"]
    assert body["dem"]["hydro"]["subbasin_id"] is not None


def test_sar_change_masks_steep_slopes_and_south_has_no_m3() -> None:
    before = _solid_png((180, 180, 180, 255), size=16)
    after = _solid_png((20, 40, 220, 255), size=16)  # caída especular + ganancia azul
    steep = np.zeros((16, 16), dtype=bool)
    steep[:8, :] = True

    out = compute_sar_change_png(before, after, steep_mask=steep)
    arr = np.asarray(Image.open(io.BytesIO(out)).convert("RGBA"))
    # Zona escarpada >= 25° debe estar atenuada (alfa 84) con tono violeta cautela SAR
    assert int(arr[2, 2, 3]) == 84
    # Zona plana muestra nueva expansión agua/saturación (cian alfa 220)
    assert int(arr[12, 12, 3]) == 220
    assert int(arr[12, 12, 2]) == 255

    # Delta OPERA entre base vacía y nueva agua
    op_delta = compute_opera_delta_png(_solid_png((0, 0, 0, 0), 16), _solid_png((0, 180, 255, 255), 16))
    op_arr = np.asarray(Image.open(io.BytesIO(op_delta)).convert("RGBA"))
    assert int(op_arr[4, 4, 2]) == 255


def test_dry_season_negative_control_and_historical_storm_benchmark() -> None:
    north = BasinZone(
        id="norte-taquina-pintumayu",
        subsystem="north",
        name_es="Norte Taquiña",
        name_en="North Taquiña",
        hazard="slope_mudflow",
        bbox=(-66.2, -17.35, -66.1, -17.25),
        centroid=(-66.15, -17.30),
        description_es="Cabecera norte",
        description_en="North headwaters",
        area_km2=86.0,
    )
    south = BasinZone(
        id="sur-angostura-valle-alto",
        subsystem="south",
        name_es="Sur Angostura",
        name_en="South Angostura",
        hazard="water_balance",
        bbox=(-66.1, -17.6, -65.9, -17.45),
        centroid=(-66.0, -17.52),
        description_es="Balance Sur",
        description_en="South balance",
        area_km2=2023.0,
    )
    dem_n = {"steep_pct_gt20": 45.0, "steep_pct_gt25": 28.0, "slope_p90_deg": 32.0, "above_2750_pct": 85.0, "low_slope_pct_lt5": 10.0, "twi_p90": 9.5}
    dem_s = {"steep_pct_gt20": 15.0, "steep_pct_gt25": 8.0, "slope_p90_deg": 18.0, "above_2750_pct": 25.0, "low_slope_pct_lt5": 48.0, "twi_p90": 11.2}

    # Control negativo: estiaje seco agosto sin fuego ni lluvia -> NUNCA alerta roja
    dry_precip = {"latest_mm": 0.0, "sum_7d_mm": 0.0, "sum_30d_mm": 3.0, "max_24h_30d_mm": 0.0}
    res_n_dry = evaluate_zone_risk(north, dem_n, dry_precip, fire_count_30d=0)
    res_s_dry = evaluate_zone_risk(south, dem_s, dry_precip, fire_count_30d=0, sat_zone_metrics={"opera_water_km2": 1.2, "baseline_dry_km2": 1.2, "water_anomaly_km2": 0.0})
    assert res_n_dry["level"] in ("verde", "amarillo")
    assert res_s_dry["level"] in ("verde", "amarillo")
    assert "sin m³" in " ".join(res_s_dry["caveats"] + [d["value"] for d in res_s_dry["drivers"]])

    # Benchmark histórico húmedo (tipo evento mazamorra Tiquipaya / Taquiña) -> naranja/rojo
    storm_precip = {"latest_mm": 38.0, "sum_7d_mm": 96.0, "sum_30d_mm": 210.0, "max_24h_30d_mm": 44.0}
    res_n_storm = evaluate_zone_risk(north, dem_n, storm_precip, fire_count_30d=3)
    assert res_n_storm["level"] == "rojo"
    subs = build_subsystems_summary([res_n_storm, res_s_dry])
    assert len(subs) == 2


def test_opendap_parser_and_sar_change_endpoint() -> None:
    ascii_sample = "\n".join([
        "precipitation.lon, -66.25, -66.15",
        "precipitation.lat, -17.45, -17.35",
        "[0][0], 1.2, 5.4",
        "[0][1], 8.1, 14.6",
    ])
    parsed = _parse_opendap_ascii(ascii_sample)
    assert parsed is not None
    assert parsed["values"][1][1] == 14.6

    client = TestClient(app)
    tile_res = client.get("/api/basin/tiles/sar-change/2026-10-25/2026-11-10/10/323/562.png")
    assert tile_res.status_code == 200
    assert tile_res.headers["content-type"] == "image/png"


def test_integrated_alert_tile_varies_in_both_axes() -> None:
    """Regresión visual: las filas deben variar en 2D sobre la topografía (sin franjas verticales)."""
    client = TestClient(app)
    res = client.get("/api/basin/tiles/integrated_alert/11/647/1124.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    arr = np.asarray(Image.open(io.BytesIO(res.content)).convert("RGBA"))
    assert arr.shape == (256, 256, 4)
    # Garantizar variación vertical (entre filas) además de horizontal
    row_std = float(np.std(arr[..., 3].astype(np.float32), axis=0).mean())
    assert row_std > 1.0
