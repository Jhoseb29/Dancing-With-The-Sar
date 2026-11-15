"""Persistencia de predicciones operativas y su verificación posterior."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LEVELS = ("verde", "amarillo", "naranja", "rojo")

PENDING = "pendiente"
CONFIRMED = "confirmada"
FALSE_ALARM = "falsa_alarma"
EXPIRED = "expirada"


class PredictionStore:
    def __init__(self, output_dir: Path) -> None:
        self.path = output_dir / "predictions" / "predictions.json"

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._read()
        now = datetime.now(timezone.utc)
        changed = False
        for row in rows:
            if row["estado"] == PENDING and datetime.fromisoformat(row["valida_hasta"]) < now:
                row["estado"] = EXPIRED
                row["cerrada_en"] = now.isoformat(timespec="seconds")
                changed = True
        if changed:
            self._write(rows)
        rows.sort(key=lambda row: row["emitida_en"], reverse=True)
        return rows[:limit]

    def upsert(
        self, alert: dict[str, Any], now: datetime, horizon_hours: int, model_version: Any, start_level: str = "amarillo"
    ) -> dict[str, Any] | None:
        if LEVELS.index(alert["nivel"]) < LEVELS.index(start_level):
            return None
        rows = self._read()
        self._expire(rows, now)
        key = f"{alert['area']['nombre']}|{alert['peligro']}|{alert['fecha_referencia']}"
        prediction_id = "pred-" + hashlib.sha1(key.encode()).hexdigest()[:12]
        existing = next((row for row in rows if row["id"] == prediction_id), None)
        valid_until = now + timedelta(hours=horizon_hours)
        snapshot = {
            "id": prediction_id,
            "area": alert["area"],
            "peligro": alert["peligro"],
            "nivel": alert["nivel"],
            "indice_riesgo": alert["indice_riesgo"],
            "confianza": alert["confianza"],
            "componentes": alert["componentes"],
            "indicadores": alert["indicadores"],
            "motivos": alert["motivos"],
            "fuentes": alert["fuentes"],
            "alerta_id": alert["id"],
            "fecha_referencia": alert["fecha_referencia"],
            "modelo": f"thresholds-v{model_version}",
            "estado": existing["estado"] if existing and existing["estado"] != EXPIRED else PENDING,
            "emitida_en": existing["emitida_en"] if existing else now.isoformat(timespec="seconds"),
            "actualizada_en": now.isoformat(timespec="seconds"),
            "valida_hasta": valid_until.isoformat(timespec="seconds"),
        }
        if existing:
            snapshot["confirmada_en"] = existing.get("confirmada_en")
            snapshot["observacion"] = existing.get("observacion")
            rows[rows.index(existing)] = snapshot
        else:
            rows.append(snapshot)
        self._write(rows)
        return snapshot

    def confirm(self, prediction_id: str, occurred: bool, observation: dict[str, Any]) -> dict[str, Any] | None:
        rows = self._read()
        row = next((item for item in rows if item["id"] == prediction_id), None)
        if row is None:
            return None
        row["estado"] = CONFIRMED if occurred else FALSE_ALARM
        row["confirmada_en"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row["observacion"] = observation
        self._write(rows)
        return row

    def _read(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _expire(rows: list[dict[str, Any]], now: datetime) -> None:
        for row in rows:
            if row["estado"] == PENDING and datetime.fromisoformat(row["valida_hasta"]) < now:
                row["estado"] = EXPIRED
                row["cerrada_en"] = now.isoformat(timespec="seconds")
