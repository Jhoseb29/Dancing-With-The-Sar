"""Adaptador WebSocket del agente: /api/agent/session (contrato agent-message.schema.json)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config.settings import get_settings
from modules.events.adapters.http import fire_service
from modules.llm_advisor.adapters.gemini_provider import GeminiProvider
from modules.llm_advisor.adapters.gemini_transcriber import GeminiTranscriber
from modules.ui_agent.application.agent_session import AgentSession
from modules.ui_agent.domain.catalog import UiCatalog
from modules.ui_agent.domain.patch_validation import PatchValidator

log = logging.getLogger("ui_agent")
router = APIRouter()

_settings = get_settings()
_catalog = UiCatalog.load(_settings.ui_config_dir)
_validator = PatchValidator(_settings.schemas_dir)
_llm = GeminiProvider(_settings.gemini_api_key, _settings.gemini_model, _settings.gemini_fallback_model)
_stt = GeminiTranscriber(_settings.gemini_api_key, _settings.gemini_stt_model)


@router.websocket("/api/agent/session")
async def agent_session(websocket: WebSocket) -> None:
    await websocket.accept()

    async def send(message: dict[str, Any]) -> None:
        await websocket.send_json(message)

    session = AgentSession(_llm, _catalog, _validator, _settings, send, fire_service(), _stt)
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                await session.handle(message)
    except WebSocketDisconnect:
        pass
    except ValueError:
        await send({"type": "error", "code": "bad_message", "message": "El mensaje no es JSON válido."})
    finally:
        await session.close()
