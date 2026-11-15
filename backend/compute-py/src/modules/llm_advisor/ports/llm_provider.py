"""Puerto LLM (Hexagonal). La aplicación depende de esto, nunca de un SDK concreto."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolDeclaration:
    """Herramienta neutral al proveedor: nombre, descripción y parámetros en JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class FunctionCall:
    id: str | None
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class FunctionResult:
    call: FunctionCall
    response: dict[str, Any]


@dataclass
class LLMTurn:
    text: str = ""
    function_calls: list[FunctionCall] = field(default_factory=list)


class LLMError(RuntimeError):
    pass


class Conversation(Protocol):
    """Conversación con historial propio del proveedor."""

    async def send_user(self, text: str) -> LLMTurn: ...

    async def send_function_results(self, results: list[FunctionResult]) -> LLMTurn: ...

    def trim(self, max_messages: int) -> None: ...


class LLMProviderPort(Protocol):
    @property
    def configured(self) -> bool: ...

    def start_conversation(self, system: str, tools: list[ToolDeclaration]) -> Conversation: ...
