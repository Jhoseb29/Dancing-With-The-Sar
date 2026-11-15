"""Automatic monitoring: one tick evaluates every district and publishes only level changes.

State with memory (output/monitor/state.json), per district:
  * the level RISES immediately (never delay a warning);
  * it only LOWERS after the computed level has stayed lower for `horas_para_bajar`
    (avoids red -> green -> red flicker between two rain updates).
Every tick is logged (output/monitor/log.jsonl): that log is what we later compare with what
really happened, to create new evaluation cases.

`tick()` is a plain function on purpose: cron, a loop or a Dagster schedule can call it as is.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from . import districts as districts_mod
from .engine import LEVELS, Request, evaluate
from .publish import publish
from .predictions import PredictionStore
from .situation import publish as publish_situation
from .summary import compact
from .settings import Settings

log = logging.getLogger("alerts.monitor")


def _decide(prev: dict[str, Any] | None, level: str, now: datetime, hold: timedelta) -> tuple[str, str, str | None]:
    """-> (level to keep, decision, lower_since)."""
    if prev is None:
        return level, "primera_observacion", None
    old = prev["nivel"]
    if LEVELS.index(level) > LEVELS.index(old):
        return level, "sube", None
    if LEVELS.index(level) == LEVELS.index(old):
        return old, "sin_cambio", None
    since = prev.get("bajando_desde") or now.isoformat()
    last_calc = prev.get("calculado")
    if last_calc and LEVELS.index(level) > LEVELS.index(last_calc):
        since = now.isoformat()  # conditions worsened again while lowering: restart the clock
    if now - datetime.fromisoformat(since) >= hold:
        return level, "baja", None
    return old, "mantiene_por_memoria", since


def tick(st: Settings, now: datetime | None = None, only: list[str] | None = None) -> list[dict[str, Any]]:
    cfg = st.thresholds["monitor"]
    now = now or datetime.now(timezone.utc)
    local_day = (now + timedelta(hours=cfg["utc_offset_horas"])).date().isoformat()
    hold = timedelta(hours=cfg["horas_para_bajar"])
    mon_dir = st.output_dir / "monitor"
    mon_dir.mkdir(parents=True, exist_ok=True)
    state_path = mon_dir / "state.json"
    state: dict[str, Any] = json.loads(state_path.read_text()) if state_path.exists() else {}
    predictions = PredictionStore(st.output_dir)

    bursts = publish_situation(st, now)  # rain every 30 min + radar passes, for the web
    rows = []
    for feat in districts_mod.load():
        props = feat["properties"]
        if only and props["id"] not in only:
            continue
        req = Request(nombre=f"{props['distrito']} · {props['comuna']}", bbox=tuple(props["bbox"]),
                      fecha=local_day, peligro=None, radar_mode="skip", case_id=f"monitor-{props['id']}")
        try:
            alert = evaluate(req, st)
        except Exception as exc:  # noqa: BLE001 - one district failing must not stop the others
            log.warning("%s: %s", props["id"], exc)
            rows.append({"ts": now.isoformat(), "distrito": props["id"], "error": str(exc)})
            continue
        kept, decision, lowering = _decide(state.get(props["id"]), alert["nivel"], now, hold)
        predictions.upsert(
            alert,
            now,
            cfg["horizonte_prediccion_horas"],
            st.thresholds["version"],
            cfg["prediccion_desde"],
        )
        published = None
        if decision in ("primera_observacion", "sube", "baja"):
            published = str(publish(alert, st.output_dir).name)
        state[props["id"]] = {"nivel": kept, "calculado": alert["nivel"], "indice": alert["indice_riesgo"],
                              "peligro": alert["peligro"],
                              "datos": {**compact(alert, st.thresholds), "rafaga": bursts.get(props["id"])},
                              "actualizado": now.isoformat(), "bajando_desde": lowering,
                              # a level never drops before `hold`: the warning is valid at least until then
                              "vigente_hasta": (now + hold).isoformat()}
        row = {"ts": now.isoformat(), "dia_local": local_day, "distrito": props["id"], "peligro": alert["peligro"],
               "nivel_calculado": alert["nivel"], "nivel_vigente": kept, "indice": alert["indice_riesgo"],
               "confianza": alert["confianza"]["porcentaje"], "decision": decision, "publicada": published}
        rows.append(row)
        log.info("%s %-13s %-8s (índice %5.1f) -> %s", props["id"], alert["peligro"], kept, alert["indice_riesgo"], decision)

    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    with (mon_dir / "log.jsonl").open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows
