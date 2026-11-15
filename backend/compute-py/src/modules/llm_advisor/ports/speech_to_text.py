"""Puerto de voz a texto (OpenSpec 10). La aplicación depende de esto, no del proveedor."""

from __future__ import annotations

from typing import Protocol


class SpeechToTextError(RuntimeError):
    pass


class SpeechToTextPort(Protocol):
    @property
    def configured(self) -> bool: ...

    async def transcribe(self, audio: bytes, mime_type: str, lang: str) -> str:
        """Texto dicho en el audio; cadena vacía si no se entiende nada."""
        ...
