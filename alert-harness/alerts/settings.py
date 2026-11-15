"""Configuration (12-factor): paths, credentials and YAML parameters."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

HARNESS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = HARNESS_DIR.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip().removeprefix("export ").strip(), value.strip().strip("'\""))


@dataclass(frozen=True)
class Settings:
    earthdata_token: str | None
    output_dir: Path
    nisar_harness_dir: Path
    uv_bin: str
    thresholds: dict[str, Any]
    protocols: dict[str, Any]

    @classmethod
    def load(cls) -> Settings:
        _load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            earthdata_token=os.environ.get("EARTHDATA_TOKEN") or os.environ.get("EARTHDATA_TOKE"),
            output_dir=Path(os.environ.get("ALERT_OUTPUT_DIR", HARNESS_DIR / "output")),
            nisar_harness_dir=Path(os.environ.get("NISAR_HARNESS_DIR", PROJECT_ROOT / "nisar-harness")),
            uv_bin=os.environ.get("UV_BIN", str(PROJECT_ROOT / "uv")),
            thresholds=_yaml(HARNESS_DIR / "config" / "thresholds.yaml"),
            protocols=_yaml(HARNESS_DIR / "config" / "protocols.yaml"),
        )


@lru_cache
def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
