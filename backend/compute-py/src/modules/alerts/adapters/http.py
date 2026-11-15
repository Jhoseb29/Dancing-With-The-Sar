"""Alertas tempranas.

GET /api/alerts            últimas alertas válidas (JSON)
GET /api/alerts/districts  15 distritos (GeoJSON) con el nivel vigente del monitor
GET /api/alerts/rain       lluvia IMERG de las últimas 24 h cada 30 min sobre la ciudad (grilla 0,1°)
GET /api/alerts/radar      última y próxima pasada estimada de NISAR y Sentinel-1
GET /api/alerts/basins     cuencas torrenciales (GeoJSON) con datos de terreno y radar
GET /api/alerts/eval       última evaluación (scorecard) + historial de puntajes
WS  /api/alerts/ws         al conectar: {"type":"snapshot","alerts":[...]}; después
                           {"type":"alert","alert":{...}} por cada alerta nueva del alert-harness
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from config.settings import get_settings
from modules.alerts.application.feed import AlertFeed

router = APIRouter(prefix="/api/alerts")
log = logging.getLogger(__name__)


@lru_cache
def feed() -> AlertFeed:
    s = get_settings()
    return AlertFeed(s.alerts_dir, s.alerts_schema_dir)


@router.get("")
def latest_alerts(limit: int = Query(20, ge=1, le=200)) -> dict:
    alerts, _ = feed().latest(limit)
    return {"alerts": alerts}


def _read_json(path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@router.get("/districts")
def districts() -> dict:
    root = get_settings().alerts_harness_dir
    fc = _read_json(root / "data" / "districts.geojson") or {"type": "FeatureCollection", "features": []}
    state = _read_json(root / "output" / "monitor" / "state.json") or {}
    for feat in fc["features"]:
        feat["properties"]["estado"] = state.get(feat["properties"]["id"])
    return fc


@router.get("/rain")
def rain() -> dict:
    return _read_json(get_settings().alerts_harness_dir / "output" / "monitor" / "rain.json") or {"slots": []}


@router.get("/radar")
def radar() -> dict:
    return _read_json(get_settings().alerts_harness_dir / "output" / "monitor" / "radar.json") or {}


@router.get("/basins")
def basins() -> dict:
    root = get_settings().alerts_harness_dir
    return _read_json(root / "data" / "basins.geojson") or {"type": "FeatureCollection", "features": []}


@router.get("/eval")
def evaluation() -> dict:
    evals = get_settings().alerts_harness_dir / "output" / "evals"
    history_file = evals / "history.jsonl"
    history = [json.loads(line) for line in history_file.read_text().splitlines() if line.strip()] \
        if history_file.exists() else []
    latest = _read_json(evals / history[-1]["eval_id"] / "scorecard.json") if history else None
    return {"latest": latest, "history": history}


@router.websocket("/ws")
async def alerts_socket(ws: WebSocket) -> None:
    s = get_settings()
    await ws.accept()
    alerts, cursor = await asyncio.to_thread(feed().latest, s.alerts_initial)
    await ws.send_json({"type": "snapshot", "alerts": alerts})
    try:
        while True:
            await asyncio.sleep(s.alerts_poll_s)
            fresh, cursor = await asyncio.to_thread(feed().since, cursor)
            for alert in fresh:
                await ws.send_json({"type": "alert", "alert": alert})
    except WebSocketDisconnect:
        return
