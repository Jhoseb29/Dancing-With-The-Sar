"""Configuración 12-Factor (III): todo desde variables de entorno / .env de la raíz del repo."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    port: int = 8000

    # LLM (Gemini). La key nunca sale del backend.
    gemini_api_key: str = ""
    # Elegido midiendo latencia y llamadas a herramientas con el agente real (2026-11-14):
    # gemini-4-hydrogen ~3.5 s y completo; gemini-3.8-flash (estable) ~6 s como respaldo.
    gemini_model: str = "gemini-4-hydrogen"
    gemini_fallback_model: str = "gemini-3.8-flash"
    # Voz a texto (OpenSpec 10): modelo rápido con pistas de vocabulario.
    gemini_stt_model: str = "gemini-3.5-flash-lite"
    agent_max_audio_bytes: int = 2_000_000

    # NASA FIRMS (fase 3). Gratis, se pide con un email en firms.modaps.eosdis.nasa.gov/api/map_key
    firms_map_key: str = ""
    firms_cache_dir: Path = REPO_ROOT / "data" / "raw" / "firms"

    # Catálogo de UI compartido con el frontend y contratos JSON Schema.
    ui_config_dir: Path = REPO_ROOT / "frontend" / "src" / "assets" / "config"
    schemas_dir: Path = REPO_ROOT / "backend" / "shared" / "schemas"

    # Límites del agente (OpenSpec 08, D6).
    agent_max_message_chars: int = 500
    agent_turns_per_minute: int = 10
    agent_max_tool_steps: int = 6
    agent_patch_timeout_s: float = 5.0
    agent_history_messages: int = 20

    @field_validator("gemini_model", "gemini_fallback_model", "gemini_stt_model", mode="before")
    @classmethod
    def _default_model_when_empty(cls, value: object, info: object) -> object:
        """`GEMINI_MODEL=` vacío en .env no debe anular el modelo por defecto."""
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[info.field_name].default  # type: ignore[attr-defined]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
