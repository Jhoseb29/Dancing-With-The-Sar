"""Adaptador Gemini (google-genai) del LLMProviderPort. Llamada automática de funciones
desactivada: la aplicación ejecuta y valida cada herramienta (OpenSpec 08, D2)."""

from __future__ import annotations

import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from modules.llm_advisor.ports.llm_provider import (
    FunctionCall,
    FunctionResult,
    LLMError,
    LLMTurn,
    ToolDeclaration,
)

log = logging.getLogger("llm_advisor")


class GeminiConversation:
    def __init__(
        self,
        client: genai.Client,
        model: str,
        system: str,
        tools: list[ToolDeclaration],
        fallback: str | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._fallback = fallback
        self._history: list[types.Content] = []
        self._config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=tool.parameters,
                        )
                        for tool in tools
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def send_user(self, text: str) -> LLMTurn:
        self._history.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        return await self._generate()

    async def send_function_results(self, results: list[FunctionResult]) -> LLMTurn:
        parts = [
            types.Part(
                function_response=types.FunctionResponse(
                    id=result.call.id,
                    name=result.call.name,
                    response=result.response,
                )
            )
            for result in results
        ]
        self._history.append(types.Content(role="user", parts=parts))
        return await self._generate()

    def trim(self, max_messages: int) -> None:
        """Recorta el historial sin dejar respuestas de función huérfanas al inicio."""
        if len(self._history) <= max_messages:
            return
        trimmed = self._history[-max_messages:]
        while trimmed and not _is_plain_user_text(trimmed[0]):
            trimmed.pop(0)
        self._history = trimmed

    async def _generate(self) -> LLMTurn:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=self._history,
                config=self._config,
            )
        except genai_errors.APIError as err:
            # Modelo no disponible o caído (404 / 5xx): pasar al de respaldo para el resto de la sesión.
            if self._fallback and self._model != self._fallback and (err.code == 404 or err.code >= 500):
                log.warning("Gemini %s falló (%s); usando respaldo %s", self._model, err.code, self._fallback)
                self._model = self._fallback
                return await self._generate()
            raise LLMError(f"Gemini respondió {err.code}: {err.message}") from err

        candidate = (response.candidates or [None])[0]
        if candidate is None or candidate.content is None:
            raise LLMError("Gemini no devolvió contenido")
        # Guardar el contenido completo del modelo (incluye firmas de razonamiento).
        self._history.append(candidate.content)

        calls = [
            FunctionCall(id=call.id, name=call.name or "", args=dict(call.args or {}))
            for call in (response.function_calls or [])
        ]
        text = "".join(part.text for part in candidate.content.parts or [] if part.text and not part.thought)
        return LLMTurn(text=text.strip(), function_calls=calls)


def _is_plain_user_text(content: types.Content) -> bool:
    return content.role == "user" and any(part.text for part in content.parts or [])


class GeminiProvider:
    def __init__(self, api_key: str, model: str, fallback_model: str | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback = fallback_model
        self._client = genai.Client(api_key=api_key) if api_key else None

    @property
    def configured(self) -> bool:
        return self._client is not None

    def start_conversation(self, system: str, tools: list[ToolDeclaration]) -> GeminiConversation:
        if self._client is None:
            raise LLMError("GEMINI_API_KEY no configurada")
        return GeminiConversation(self._client, self._model, system, tools, self._fallback)
