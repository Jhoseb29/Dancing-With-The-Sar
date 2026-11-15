"""Runtime Python de Dancing with the SARs (FastAPI).

Ejecutar desde backend/compute-py:
    .venv/Scripts/python -m uvicorn main:app --app-dir src --port 8000
"""

import logging

from fastapi import FastAPI

from config.settings import get_settings
from modules.events.adapters.http import router as events_router
from modules.ui_agent.adapters.websocket import router as agent_router

# 12-Factor XI: logs a stdout. Nunca se registran keys.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx registra la URL completa de cada petición; la de FIRMS lleva la MAP_KEY en la ruta.
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Dancing with the SARs · compute-py")
app.include_router(agent_router)
app.include_router(events_router)


@app.get("/api/health")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "agent": {"llm_configured": bool(settings.gemini_api_key), "model": settings.gemini_model},
        "events": {"firms_configured": bool(settings.firms_map_key)},
    }
