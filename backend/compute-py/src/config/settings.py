"""Configuración 12-Factor (III): todo desde variables de entorno / .env de la raíz del repo."""

import shutil
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


def _default_uv() -> str:
    """`uv` del PATH o, si no está, el symlink del repo (./uv)."""
    return shutil.which("uv") or str(REPO_ROOT / "uv")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    port: int = 8000

    # NASA FIRMS (fase 3). Gratis, se pide con un email en firms.modaps.eosdis.nasa.gov/api/map_key
    firms_map_key: str = ""
    firms_cache_dir: Path = REPO_ROOT / "data" / "raw" / "firms"

    # Catálogo de UI compartido con el frontend y contratos JSON Schema.
    ui_config_dir: Path = REPO_ROOT / "frontend" / "src" / "assets" / "config"
    schemas_dir: Path = REPO_ROOT / "backend" / "shared" / "schemas"

    # Harness NISAR (nisar-harness/): pregunta en texto -> análisis radar -> explicación.
    harness_dir: Path = REPO_ROOT / "nisar-harness"
    harness_uv_bin: str = _default_uv()
    harness_max_concurrent: int = 2  # cada corrida lee varios cientos de MB desde AWS
    harness_timeout_s: int = 1200
    harness_max_text_chars: int = 500

    # Alertas (alert-harness/): el harness escribe JSON en output/alerts; el WebSocket los empuja a la UI.
    alerts_dir: Path = REPO_ROOT / "alert-harness" / "output" / "alerts"
    alerts_harness_dir: Path = REPO_ROOT / "alert-harness"
    alerts_schema_dir: Path = REPO_ROOT / "alert-harness" / "schemas"
    alerts_poll_s: float = 3.0
    alerts_initial: int = 60

    @property
    def harness_output_dir(self) -> Path:
        return self.harness_dir / "output"


@lru_cache
def get_settings() -> Settings:
    return Settings()
