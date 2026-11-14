"""Sesión del agente de la UI (OpenSpec 08, D2): conversación, herramientas → parches,
espera de la confirmación del navegador y límites."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
import uuid
from collections import deque
from datetime import date
from typing import Any, Awaitable, Callable, Protocol

from config.settings import Settings
from modules.llm_advisor.ports.llm_provider import (
    Conversation,
    FunctionCall,
    FunctionResult,
    LLMError,
    LLMProviderPort,
    LLMTurn,
)
from modules.llm_advisor.ports.speech_to_text import SpeechToTextError, SpeechToTextPort
from modules.ui_agent.application.prompt import GREETING_INSTRUCTION, build_system_prompt
from modules.ui_agent.domain.catalog import UiCatalog
from modules.ui_agent.domain.patch_validation import PatchValidator
from modules.ui_agent.domain.tools import FIRE_STATS_TOOL, VIEW_TOOL, ToolError, build_ops, declarations

log = logging.getLogger("ui_agent")

Send = Callable[[dict[str, Any]], Awaitable[None]]

ALLOWED_AUDIO = {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac"}


class FireStatsPort(Protocol):
    async def stats(self, place_id: str, start: date, end: date) -> dict[str, Any]: ...


class AgentSession:
    def __init__(
        self,
        llm: LLMProviderPort,
        catalog: UiCatalog,
        validator: PatchValidator,
        settings: Settings,
        send: Send,
        fire_stats: FireStatsPort | None = None,
        stt: SpeechToTextPort | None = None,
    ) -> None:
        self._llm = llm
        self._catalog = catalog
        self._validator = validator
        self._settings = settings
        self._send = send
        self._fire_stats = fire_stats
        self._stt = stt

        self._conversation: Conversation | None = None
        self._lang = "es"
        self._scene: dict[str, Any] = {}
        self._reported: dict[str, Any] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._turn_task: asyncio.Task[None] | None = None
        self._turn_times: deque[float] = deque()

    # ---- Mensajes entrantes -------------------------------------------------

    async def handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "scene.patch.result":
            self._resolve_patch(message)
        elif kind == "session.start":
            self._update_state(message)
            self._lang = message.get("lang") if message.get("lang") in ("es", "en") else "es"
            if not self._llm.configured:
                await self._error("llm_not_configured", "El agente no tiene configurada GEMINI_API_KEY en el backend.")
                return
            tools = declarations(self._catalog)
            self._conversation = self._llm.start_conversation(build_system_prompt(self._catalog, self._lang), tools)
            await self._send({"type": "agent.status", "status": "ready"})
            self._start_turn(GREETING_INSTRUCTION[self._lang])
        elif kind == "user.text":
            text = str(message.get("text", "")).strip()
            if not text:
                return
            if len(text) > self._settings.agent_max_message_chars:
                await self._error("too_long", f"El mensaje supera {self._settings.agent_max_message_chars} caracteres.")
                return
            if not self._allow_turn():
                await self._error("rate_limited", "Demasiados mensajes seguidos; espera unos segundos.")
                return
            if self._conversation is None:
                await self._error("llm_not_configured", "La sesión del agente no está iniciada.")
                return
            self._update_state(message)
            self._start_turn(text)
        elif kind == "user.audio":
            await self._handle_audio(message)
        elif kind == "user.interrupt":
            self._cancel_turn()
        else:
            await self._error("bad_message", f"Tipo de mensaje desconocido: {kind}")

    async def close(self) -> None:
        self._cancel_turn()

    async def _handle_audio(self, message: dict[str, Any]) -> None:
        """Voz → texto (Gemini en el servidor) → mismo flujo que user.text."""
        if self._conversation is None or self._stt is None or not self._stt.configured:
            await self._error("llm_not_configured", "La transcripción de voz no está configurada.")
            return
        mime = str(message.get("mime", "")).split(";")[0].strip().lower()
        if mime not in ALLOWED_AUDIO:
            await self._error("bad_message", f"Formato de audio no soportado: {mime}")
            return
        try:
            audio = base64.b64decode(str(message.get("data", "")), validate=True)
        except (binascii.Error, ValueError):
            await self._error("bad_message", "Audio inválido.")
            return
        if not audio or len(audio) > self._settings.agent_max_audio_bytes:
            await self._error("audio_too_large", "El audio es demasiado largo; habla en frases más cortas.")
            return
        if not self._allow_turn():
            await self._error("rate_limited", "Demasiados mensajes seguidos; espera unos segundos.")
            return
        self._update_state(message)
        self._cancel_turn()
        await self._send({"type": "agent.status", "status": "transcribing"})
        try:
            text = await self._stt.transcribe(audio, mime, self._lang)
        except SpeechToTextError as err:
            log.warning("STT error: %s", err)
            await self._error("stt_error", "No se pudo transcribir el audio. Intenta de nuevo.")
            return
        if not text:
            await self._error("no_speech", "No se entendió lo que dijiste. Intenta de nuevo.")
            return
        await self._send({"type": "user.transcript", "text": text[: self._settings.agent_max_message_chars]})
        self._start_turn(text[: self._settings.agent_max_message_chars])

    # ---- Turnos -------------------------------------------------------------

    def _start_turn(self, text: str) -> None:
        self._cancel_turn()
        self._turn_task = asyncio.create_task(self._run_turn(text))

    def _cancel_turn(self) -> None:
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
        for future in self._pending.values():
            future.cancel()
        self._pending.clear()

    async def _run_turn(self, text: str) -> None:
        assert self._conversation is not None
        turn_id = uuid.uuid4().hex[:8]
        try:
            await self._send({"type": "agent.status", "status": "thinking"})
            turn = await self._conversation.send_user(self._with_context(text))
            for _ in range(self._settings.agent_max_tool_steps):
                if not turn.function_calls:
                    break
                results = [await self._execute(call) for call in turn.function_calls]
                await self._send({"type": "agent.status", "status": "thinking"})
                turn = await self._conversation.send_function_results(results)
            await self._finish(turn_id, turn)
        except asyncio.CancelledError:
            raise
        except LLMError as err:
            log.warning("LLM error: %s", err)
            await self._error("llm_error", "El agente no pudo responder ahora. Intenta de nuevo en un momento.")
        except Exception:  # noqa: BLE001 - la sesión no debe caerse por un turno
            log.exception("Fallo inesperado en el turno")
            await self._error("llm_error", "Ocurrió un error inesperado en el agente.")
        finally:
            self._conversation.trim(self._settings.agent_history_messages)

    async def _finish(self, turn_id: str, turn: LLMTurn) -> None:
        text = turn.text or ("Listo." if self._lang == "es" else "Done.")
        await self._send({"type": "agent.text", "turnId": turn_id, "text": text})
        await self._send({"type": "agent.turn.end", "turnId": turn_id})
        await self._send({"type": "agent.status", "status": "idle"})

    def _with_context(self, text: str) -> str:
        state = {"today": date.today().isoformat(), "scene": self._scene, "reported": self._reported}
        return f"[Estado actual de la pantalla]\n{json.dumps(state, ensure_ascii=False)}\n\n[Usuario]\n{text}"

    # ---- Herramientas -------------------------------------------------------

    async def _execute(self, call: FunctionCall) -> FunctionResult:
        if call.name == VIEW_TOOL:
            return FunctionResult(call, {"scene": self._scene, "reported": self._reported})
        if call.name == FIRE_STATS_TOOL:
            return FunctionResult(call, await self._fire_stats_result(call.args))

        await self._send({"type": "agent.status", "status": "acting", "tool": call.name})
        try:
            ops = build_ops(call.name, call.args, self._scene, self._catalog)
        except ToolError as err:
            return FunctionResult(call, {"applied": False, "reason": str(err)})

        base_version = int(self._scene.get("version", 0))
        error = self._validator.error(base_version, ops)
        if error:
            return FunctionResult(call, {"applied": False, "reason": error})

        patch_id = uuid.uuid4().hex[:12]
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[patch_id] = future
        await self._send({"type": "scene.patch", "patchId": patch_id, "baseVersion": base_version, "ops": ops})
        try:
            result = await asyncio.wait_for(future, timeout=self._settings.agent_patch_timeout_s)
        except asyncio.TimeoutError:
            return FunctionResult(call, {"applied": False, "reason": "El navegador no confirmó el cambio a tiempo."})
        finally:
            self._pending.pop(patch_id, None)

        self._update_state(result)
        response: dict[str, Any] = {"applied": bool(result.get("ok"))}
        if not result.get("ok"):
            response["reason"] = result.get("reason", "rechazado")
        response["now_showing"] = {"route": self._scene.get("route"), "camera": self._scene.get("camera"), "layers": self._scene.get("layers")}
        return FunctionResult(call, response)

    async def _fire_stats_result(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._fire_stats is None:
            return {"ok": False, "reason": "Estadísticas de incendios no disponibles en este servidor."}
        await self._send({"type": "agent.status", "status": "acting", "tool": FIRE_STATS_TOOL})
        try:
            start = date.fromisoformat(str(args.get("start_date")))
            end = min(date.fromisoformat(str(args.get("end_date"))), date.today())
            stats = await self._fire_stats.stats(str(args.get("place_id")), start, end)
        except ValueError as err:
            code = getattr(err, "code", "bad_request")
            return {"ok": False, "code": code, "reason": str(err)}
        # Resumen compacto para el modelo (sin listas enormes).
        top_months = sorted(stats["monthly"], key=lambda m: m["count"], reverse=True)[:4]
        return {
            "ok": True,
            "place": stats["place"],
            "start": stats["start"],
            "end": stats["end"],
            "total_hotspots": stats["total"],
            "peak_day": stats["peak_day"],
            "top_months": top_months,
            "source": stats["source"],
        }

    def _resolve_patch(self, message: dict[str, Any]) -> None:
        future = self._pending.get(str(message.get("patchId")))
        if future and not future.done():
            future.set_result(message)

    # ---- Utilidades ---------------------------------------------------------

    def _update_state(self, message: dict[str, Any]) -> None:
        if isinstance(message.get("scene"), dict):
            self._scene = message["scene"]
        if isinstance(message.get("reported"), dict):
            self._reported = message["reported"]

    def _allow_turn(self) -> bool:
        now = time.monotonic()
        while self._turn_times and now - self._turn_times[0] > 60:
            self._turn_times.popleft()
        if len(self._turn_times) >= self._settings.agent_turns_per_minute:
            return False
        self._turn_times.append(now)
        return True

    async def _error(self, code: str, message: str) -> None:
        await self._send({"type": "error", "code": code, "message": message})
        await self._send({"type": "agent.status", "status": "idle"})
