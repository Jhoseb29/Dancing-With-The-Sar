"""Runtime configuration (12-factor: everything overridable by environment)."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = HARNESS_DIR.parent

DEFAULT_COLLECTIONS = (
    "NISAR_L2_GCOV_V1",
    "NISAR_L2_GCOV_PROVISIONAL_V1",
    "NISAR_L2_GCOV_BETA_V1",
)
# Cuenca de Cochabamba (minLon, minLat, maxLon, maxLat)
COCHABAMBA_BBOX = (-66.54, -17.87, -65.57, -17.18)

log = logging.getLogger("nisar")


def load_dotenv(*candidates: Path) -> None:
    """Load KEY=VALUE pairs from the first existing .env files without overriding the env."""
    for env_file in candidates:
        if not env_file.is_file():
            continue
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            os.environ.setdefault(key, value.strip().strip("'\""))


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


def _env_bbox(name: str, default: tuple[float, ...]) -> tuple[float, ...]:
    value = os.environ.get(name)
    if not value:
        return default
    parts = tuple(float(x) for x in value.replace(",", " ").split())
    if len(parts) != 4:
        raise ValueError(f"{name} debe tener 4 valores: minLon minLat maxLon maxLat")
    return parts


@dataclass(frozen=True)
class Settings:
    output_dir: Path
    aws_credentials_file: Path
    earthdata_token: str | None
    cmr_url: str
    cmr_client_id: str
    default_bbox: tuple[float, ...]
    claude_backend: str  # auto | cli (Claude Code subscription) | api (ANTHROPIC_API_KEY)
    claude_bin: str
    intent_model: str
    interpret_model: str
    claude_timeout_s: int
    alert_harness_dir: Path  # Centinela outputs, read-only (single chat explains its alerts)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(HARNESS_DIR / ".env", PROJECT_ROOT / ".env")
        token = os.environ.get("EARTHDATA_TOKEN")
        if not token and os.environ.get("EARTHDATA_TOKE"):
            log.warning("Usando EARTHDATA_TOKE (typo); renómbrala a EARTHDATA_TOKEN en .env")
            token = os.environ["EARTHDATA_TOKE"]
        return cls(
            output_dir=_env_path("NISAR_OUTPUT_DIR", HARNESS_DIR / "output"),
            aws_credentials_file=_env_path(
                "NISAR_AWS_CREDENTIALS", PROJECT_ROOT / "aws-nisar-data-credentials.json"
            ),
            earthdata_token=token or None,
            cmr_url=os.environ.get("CMR_GRANULES_URL", "https://cmr.earthdata.nasa.gov/search/granules.json"),
            cmr_client_id=os.environ.get("CMR_CLIENT_ID", "nisar-harness"),
            default_bbox=_env_bbox("NISAR_DEFAULT_BBOX", COCHABAMBA_BBOX),
            claude_backend=os.environ.get("CLAUDE_BACKEND", "auto").lower(),
            claude_bin=os.environ.get("CLAUDE_BIN", "claude"),
            intent_model=os.environ.get("CLAUDE_INTENT_MODEL", "haiku"),
            interpret_model=os.environ.get("CLAUDE_INTERPRET_MODEL", "haiku"),
            claude_timeout_s=int(os.environ.get("CLAUDE_TIMEOUT_S", "300")),
            alert_harness_dir=_env_path("ALERT_HARNESS_DIR", PROJECT_ROOT / "alert-harness"),
        )


def setup_logging(verbose: bool = False, stream=None) -> None:
    logging.basicConfig(
        stream=stream,
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
