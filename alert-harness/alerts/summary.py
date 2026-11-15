"""Compact, UI-ready view of an alert: three 0..1 signals + the raw values behind them.

The web shows these as gauges (rain / wet soil / steep slope) instead of paragraphs; the full
indicators stay in the alert for technicians. Text lives in the frontend (i18n), not here.
"""
from __future__ import annotations

from typing import Any

from .engine import scale


def _value(alert: dict[str, Any], ind_id: str) -> float | None:
    return next((i["valor"] for i in alert["indicadores"] if i["id"] == ind_id), None)


def compact(alert: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    api = _value(alert, "lluvia_api_mm")
    comps = alert["componentes"]
    signals = {
        "lluvia": comps.get("disparo"),
        "suelo": round(scale(api, thresholds["lluvia"]["api_mm"]), 2) if api is not None else None,
        "terreno": comps.get("susceptibilidad"),
        "radar": comps.get("evidencia_radar"),
    }
    # terrain is a constant of the place, not a cause of today's alert
    strong = {k: v for k, v in signals.items() if k != "terreno" and v is not None and v >= 0.5}
    return {
        "senales": signals,
        # main driver, for a one-word "why" in the UI
        "causa": max(strong, key=strong.get) if strong else "calma",
        "valores": {
            "lluvia_24h_mm": _value(alert, "lluvia_max_24h_mm"),
            "lluvia_72h_mm": _value(alert, "lluvia_acumulada_72h_mm"),
            "lluvia_antecedente_mm": api,
            "ladera_fuerte_pct": _value(alert, "fraccion_pendiente_fuerte_pct"),
            "pendiente_media_grados": _value(alert, "pendiente_media_grados"),
        },
        "confianza": alert["confianza"]["etiqueta"],
        "alerta_id": alert["id"],
    }
