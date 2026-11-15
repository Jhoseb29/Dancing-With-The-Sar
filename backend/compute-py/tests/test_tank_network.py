"""Pruebas de integración hidro-espacial para la red estratégica de tanques (`/api/alerts/tanks`)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "backend" / "compute-py" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from main import app  # noqa: E402


def test_strategic_tank_network_covers_drought_and_fires() -> None:
    client = TestClient(app)

    res = client.get("/api/alerts/tanks")
    assert res.status_code == 200
    body = res.json()

    summary = body["summary"]
    assert summary["tanks_count"] == 6
    assert summary["total_storage_m3"] > 0
    assert summary["drought_targets_covered"] >= 1
    assert summary["fire_hotspots_covered"] >= 1
    assert body["analysis_source"] in ("gemini", "hydro_deterministic")
    assert body["analysis"]["headline"]
    assert body["analysis"]["drought_strategy"]
    assert body["analysis"]["wildfire_strategy"]
    assert len(body["analysis"]["priority_actions"]) >= 1

    roles = {t["role"] for t in body["tanks"]}
    assert "dual" in roles
    for tank in body["tanks"]:
        assert 2000.0 <= tank["elevation_m"] <= 4600.0
        assert len(tank["nearby_drought_targets"]) >= 1
        assert len(tank["nearby_fire_targets"]) >= 1
        assert tank["harvest_30d_m3"] >= 0
        assert 500 <= tank["recommended_capacity_m3"] <= 2500

    res_en = client.post(
        "/api/alerts/tanks/analyze",
        json={"focus": "Arrumani & Sacaba corridors", "lang": "en"},
    )
    assert res_en.status_code == 200
    body_en = res_en.json()
    assert body_en["focus_question"] == "Arrumani & Sacaba corridors"
    assert "rainwater" in body_en["analysis"]["headline"].lower() or "tanks" in body_en["analysis"]["headline"].lower()
