"""Write a validated alert where the backend WebSocket (/api/alerts/ws) picks it up."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import schema


def publish(alert: dict[str, Any], output_dir: Path) -> Path:
    schema.require("alert", alert)
    out = output_dir / "alerts"
    out.mkdir(parents=True, exist_ok=True)
    stamp = alert["created_at"].replace(":", "").replace("-", "")[:15]
    path = out / f"{stamp}_{alert['id']}.json"
    path.write_text(json.dumps(alert, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
