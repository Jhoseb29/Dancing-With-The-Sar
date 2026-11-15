"""Alertas tempranas.

GET /api/alerts            últimas alertas válidas (JSON)
WS  /api/alerts/ws         al conectar: {"type":"snapshot","alerts":[...]}; después
                           {"type":"alert","alert":{...}} por cada alerta nueva del alert-harness
"""

from __future__ import annotations

import asyncio
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
