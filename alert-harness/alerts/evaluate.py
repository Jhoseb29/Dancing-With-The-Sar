"""Evaluation loop: run every case, compare with what we expected, score, keep history.

Score (0–100), documented so changes are comparable run to run:
  40 · CSI          hits / (hits + misses + false alarms), alert = level >= ALERT_FROM (naranja)
  25 · nivel        fraction of cases whose level falls inside [nivel_min, nivel_max]
  25 · expectativas fraction of indicator expectations met (op/valor per case)
  10 · schema       fraction of alerts + indicators that validate
Also reported (not in the score): POD, FAR, mean confidence, missing sources.
"""
from __future__ import annotations

import json
import logging
import operator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import schema
from .engine import LEVELS, Request, evaluate
from .settings import HARNESS_DIR, Settings

log = logging.getLogger("alerts.eval")

ALERT_FROM = "naranja"  # amarillo = vigilar, naranja = actuar (eval v2: antes era amarillo)
OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt}
WEIGHTS = {"csi": 40, "nivel": 25, "expectativas": 25, "schema": 10}


@dataclass
class CaseResult:
    case: dict[str, Any]
    alert: dict[str, Any] | None
    error: str | None
    outcome: str  # acierto | fallo | falsa_alarma | negativo_correcto | error
    level_ok: bool
    expectations: list[dict[str, Any]]


def load_cases(only: list[str] | None = None) -> list[dict[str, Any]]:
    cases = []
    for path in sorted((HARNESS_DIR / "cases").glob("*.json")):
        case = schema.require("case", json.loads(path.read_text(encoding="utf-8")))
        if not only or case["id"] in only:
            cases.append(case)
    return cases


def _check(exp: dict[str, Any], indicators: dict[str, dict]) -> dict[str, Any]:
    got = indicators.get(exp["indicador"])
    if exp["op"] == "existe":
        ok = got is not None
    else:
        ok = got is not None and OPS[exp["op"]](got["valor"], exp["valor"])
    return {**exp, "obtenido": got["valor"] if got else None, "cumple": ok}


def run_case(case: dict[str, Any], st: Settings, radar_mode: str) -> CaseResult:
    req = Request(nombre=case["nombre"], bbox=tuple(case["bbox"]), fecha=case["fecha"], peligro=case["peligro"],
                  radar_run=case.get("radar_run"), radar_mode=radar_mode, case_id=case["id"])
    try:
        alert = evaluate(req, st)
    except Exception as exc:
        log.exception("Caso %s falló", case["id"])
        return CaseResult(case, None, str(exc), "error", False, [])
    lv = LEVELS.index(alert["nivel"])
    exp = case["esperado"]
    level_ok = LEVELS.index(exp["nivel_min"]) <= lv <= LEVELS.index(exp["nivel_max"])
    alerted = lv >= LEVELS.index(ALERT_FROM)
    outcome = ("acierto" if alerted else "fallo") if case["ocurrio"] else ("falsa_alarma" if alerted else "negativo_correcto")
    by_id = {i["id"]: i for i in alert["indicadores"]}
    return CaseResult(case, alert, None, outcome, level_ok, [_check(e, by_id) for e in exp["expectativas"]])


def score(results: list[CaseResult]) -> dict[str, Any]:
    count = {k: sum(r.outcome == k for r in results)
             for k in ("acierto", "fallo", "falsa_alarma", "negativo_correcto", "error")}
    h, m, f = count["acierto"], count["fallo"], count["falsa_alarma"]
    csi = h / (h + m + f) if h + m + f else 0.0
    pod = h / (h + m) if h + m else None
    far = f / (h + f) if h + f else None
    level = sum(r.level_ok for r in results) / len(results)
    exps = [e for r in results for e in r.expectations]
    exp_rate = sum(e["cumple"] for e in exps) / len(exps) if exps else 0.0
    docs = [r.alert for r in results if r.alert] + [i for r in results if r.alert for i in r.alert["indicadores"]]
    valid = sum(not schema.errors("alert" if "nivel" in d else "indicator", d) for d in docs) / len(docs) if docs else 0.0
    total = WEIGHTS["csi"] * csi + WEIGHTS["nivel"] * level + WEIGHTS["expectativas"] * exp_rate + WEIGHTS["schema"] * valid
    confs = [r.alert["confianza"]["porcentaje"] for r in results if r.alert]
    return {
        "puntaje": round(total, 1),
        "componentes": {"csi": round(csi, 3), "nivel": round(level, 3), "expectativas": round(exp_rate, 3),
                        "schema": round(valid, 3)},
        "pod": round(pod, 3) if pod is not None else None,
        "far": round(far, 3) if far is not None else None,
        "tabla": count,
        "confianza_media_pct": round(sum(confs) / len(confs), 1) if confs else None,
        "casos": len(results),
    }


def write_report(results: list[CaseResult], summary: dict[str, Any], st: Settings, note: str) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = st.output_dir / "evals" / ts
    out.mkdir(parents=True, exist_ok=True)
    history = st.output_dir / "evals" / "history.jsonl"
    previous = None
    if history.exists():
        lines = [json.loads(line) for line in history.read_text().splitlines() if line.strip()]
        previous = lines[-1] if lines else None
    summary = {**summary, "eval_id": ts, "nota": note,
               "delta_vs_anterior": round(summary["puntaje"] - previous["puntaje"], 1) if previous else None,
               "umbrales_version": st.thresholds.get("version")}
    detail = [{
        "case_id": r.case["id"], "ocurrio": r.case["ocurrio"], "esperado": [r.case["esperado"]["nivel_min"], r.case["esperado"]["nivel_max"]],
        "nivel": r.alert["nivel"] if r.alert else None, "indice": r.alert["indice_riesgo"] if r.alert else None,
        "confianza": r.alert["confianza"] if r.alert else None, "componentes": r.alert["componentes"] if r.alert else None,
        "resultado": r.outcome, "nivel_ok": r.level_ok, "expectativas": r.expectations, "error": r.error,
    } for r in results]
    (out / "scorecard.json").write_text(json.dumps({"resumen": summary, "casos": detail}, ensure_ascii=False, indent=2))
    for r in results:
        if r.alert:
            (out / f"alert_{r.case['id']}.json").write_text(json.dumps(r.alert, ensure_ascii=False, indent=2))
    (out / "scorecard.md").write_text(_markdown(summary, detail), encoding="utf-8")
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return out


def _markdown(s: dict[str, Any], detail: list[dict[str, Any]]) -> str:
    c = s["componentes"]
    delta = f" ({s['delta_vs_anterior']:+})" if s.get("delta_vs_anterior") is not None else ""
    lines = [f"# Evaluación {s['eval_id']} — puntaje {s['puntaje']}/100{delta}", "",
             f"CSI {c['csi']} · nivel {c['nivel']} · expectativas {c['expectativas']} · schema {c['schema']} · "
             f"POD {s['pod']} · FAR {s['far']} · confianza media {s['confianza_media_pct']} %", "",
             f"Tabla: {s['tabla']}", "", "| Caso | ¿Ocurrió? | Esperado | Nivel (índice) | Confianza | Resultado | Expectativas |",
             "|---|---|---|---|---|---|---|"]
    for d in detail:
        exp = " ".join(("✅" if e["cumple"] else "❌") + f"{e['indicador']}{e['op']}{e['valor']}→{e['obtenido']}" for e in d["expectativas"])
        conf = f"{d['confianza']['porcentaje']}% {d['confianza']['etiqueta']}" if d["confianza"] else "—"
        lines.append(f"| {d['case_id']} | {'sí' if d['ocurrio'] else 'no'} | {d['esperado'][0]}–{d['esperado'][1]} | "
                     f"{d['nivel']} ({d['indice']}) | {conf} | {d['resultado']} | {exp or d['error'] or ''} |")
    return "\n".join(lines) + "\n"
