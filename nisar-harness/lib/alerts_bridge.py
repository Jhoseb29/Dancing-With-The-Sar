"""Read-only bridge to Centinela (alert-harness), so the single chat can explain the alerts.

Contract = the files the alert monitor publishes; nothing is recomputed here:
  output/monitor/state.json   current level per district + compact signals (summary.py)
  output/monitor/rain.json    IMERG every 30 min (peak, per-basin rain)
  output/monitor/radar.json   last / next radar pass
  output/alerts/*_<id>.json   full alert (validated indicators, reasons, actions)
  data/basins.geojson         torrent basins (Melton type, districts they drain into)
  output/evals/history.jsonl  how well the model scores against real cases

The level is Centinela's decision (deterministic). The model only explains it; the pipeline
re-imposes the level on the model's answer.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LEVEL_ORDER = ("verde", "amarillo", "naranja", "rojo")
BOLIVIA = timezone(timedelta(hours=-4))  # no DST
MAX_FOCUS = 3
SKILL_REL = Path(".claude") / "skills" / "alert-advisor" / "SKILL.md"
_DISTRICT_RE = re.compile(r"\b(?:d|distrito)\s*-?\s*(\d{1,2})\b", re.IGNORECASE)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _fold(text: str) -> str:
    """Lowercase without accents ('Taquiña' == 'taquina')."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def _local(iso: str | None) -> str | None:
    """UTC timestamp -> 'YYYY-MM-DD HH:MM hora de Bolivia' (the model must not convert time zones)."""
    if not iso:
        return iso
    dt = datetime.fromisoformat(iso if ("+" in iso[10:] or iso.endswith("Z")) else iso + "+00:00")
    return dt.astimezone(BOLIVIA).strftime("%Y-%m-%d %H:%M") + " hora de Bolivia"


def _localise(obj: Any) -> Any:
    """Every timestamp field ('cuando', 'actualizado', 'vigente_hasta') in Bolivia time."""
    if isinstance(obj, dict):
        return {k: (_local(v) if k in ("cuando", "actualizado", "vigente_hasta") and isinstance(v, str) else _localise(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_localise(v) for v in obj]
    return obj


def role(root: Path) -> str:
    """The alert-advisor skill is the single source of the role (frontmatter stripped)."""
    text = (root / SKILL_REL).read_text(encoding="utf-8")
    return re.sub(r"\A---.*?---\s*", "", text, flags=re.DOTALL)


def available(root: Path) -> bool:
    return (root / "output" / "monitor" / "state.json").is_file()


def _districts(root: Path) -> list[dict[str, Any]]:
    fc = _read(root / "data" / "districts.geojson") or {"features": []}
    return [f["properties"] for f in fc["features"]]


def _basins(root: Path) -> list[dict[str, Any]]:
    fc = _read(root / "data" / "basins.geojson") or {"features": []}
    return [f["properties"] for f in fc["features"]]


def focus_ids(text: str, root: Path) -> list[str]:
    """Districts the question is about: 'D9', 'distrito 13', a comuna name or a basin name."""
    folded = _fold(text)
    ids = [f"D{int(n)}" for n in _DISTRICT_RE.findall(text)]
    for d in _districts(root):
        if d.get("comuna") and _fold(d["comuna"]) in folded:
            ids.append(d["id"])
    for b in _basins(root):
        if b.get("nombre") and len(b["nombre"]) > 3 and _fold(b["nombre"]) in folded:
            ids.extend(b.get("distritos", []))
    return list(dict.fromkeys(ids))  # unique, in order


def _full_alert(root: Path, alert_id: str | None) -> dict[str, Any] | None:
    if not alert_id:
        return None
    hits = sorted((root / "output" / "alerts").glob(f"*_{alert_id}.json"))
    return _read(hits[-1]) if hits else None


def _district_detail(root: Path, props: dict[str, Any], st: dict[str, Any], rain: dict[str, Any]) -> dict[str, Any]:
    data = st.get("datos") or {}
    alert = _full_alert(root, data.get("alerta_id")) or {}
    basin_rain = rain.get("cuencas") or {}
    feeding = [b for b in _basins(root) if props["id"] in b.get("distritos", [])]
    return {
        "id": props["id"], "comuna": props.get("comuna"),
        "nivel": st.get("nivel"), "indice": st.get("indice"), "peligro": st.get("peligro"),
        **_memory(st),
        "actualizado": st.get("actualizado"), "vigente_hasta": st.get("vigente_hasta"),
        "senales": data.get("senales"), "causa": data.get("causa"), "valores": data.get("valores"),
        "rafaga_24h": data.get("rafaga"),
        "confianza": alert.get("confianza"),
        "indicadores": [{k: i.get(k) for k in ("id", "valor", "unidad", "confianza", "caveat") if i.get(k) is not None}
                        for i in alert.get("indicadores", [])],
        "motivos": alert.get("motivos", []),
        "acciones": alert.get("acciones"),
        "cuencas_que_bajan": [
            {"nombre": b["nombre"], "tipo": b["tipo"], "melton": b["melton"], "ladera_fuerte_pct": b["ladera_fuerte_pct"],
             "lluvia": {k: v for k, v in (basin_rain.get(b["id"]) or {}).items() if k != "serie_mm_h"} or None,
             "sedimento_radar": b.get("sedimento_radar")}
            for b in sorted(feeding, key=lambda b: -b["melton"])],
    }


def _memory(st: dict[str, Any]) -> dict[str, Any]:
    """If today's computed level is lower than the one in force, the monitor is holding it (hysteresis)."""
    calc = st.get("calculado")
    if calc and calc != st.get("nivel"):
        return {"nivel_calculado_hoy": calc, "sostenido_por_memoria": True,
                "nota_memoria": "el nivel no baja hasta pasar 12 h sin empeorar (evita apagar la alerta antes de tiempo)"}
    return {}


def build_context(text: str, root: Path) -> dict[str, Any]:
    state = _read(root / "output" / "monitor" / "state.json") or {}
    rain = _read(root / "output" / "monitor" / "rain.json") or {}
    radar = _read(root / "output" / "monitor" / "radar.json") or {}
    props = {d["id"]: d for d in _districts(root)}

    levels: dict[str, int] = {}
    for st in state.values():
        levels[st["nivel"]] = levels.get(st["nivel"], 0) + 1
    ranking = sorted(state.items(), key=lambda kv: -(kv[1].get("indice") or 0))
    asked = [i for i in focus_ids(text, root) if i in state]
    focus = asked[:MAX_FOCUS] or [k for k, _ in ranking[:2]]

    history = []
    hist_file = root / "output" / "evals" / "history.jsonl"
    if hist_file.exists():
        history = [json.loads(line) for line in hist_file.read_text().splitlines() if line.strip()]
    last = history[-1] if history else {}

    return _localise({
        "now": _local(datetime.now(timezone.utc).isoformat()),
        "question": text,
        "asked_districts": asked,
        "city": {"levels": levels,
                 "worst": max(levels, key=LEVEL_ORDER.index) if levels else None,
                 "ranking": [{"id": k, "comuna": (props.get(k) or {}).get("comuna"), "nivel": v["nivel"],
                              "indice": v.get("indice"), "causa": (v.get("datos") or {}).get("causa"),
                              **({"calculado_hoy": v["calculado"]} if v.get("calculado") not in (None, v["nivel"]) else {})}
                             for k, v in ranking]},
        "focus": [_district_detail(root, props.get(i, {"id": i}), state[i], rain) for i in focus],
        "rain": {"fuente": rain.get("fuente"), "productos": rain.get("productos"), "pico": rain.get("pico"),
                 "medias_horas": len(rain.get("slots", [])), "esperadas": rain.get("esperadas")},
        "radar": {k: v for k, v in radar.items() if k != "actualizado"},
        "evaluation": {"puntaje": last.get("puntaje"), "pod": last.get("pod"), "far": last.get("far"),
                       "casos": last.get("casos"), "tabla": last.get("tabla"),
                       "limite_conocido": "IMERG (~10 km) no separa tormentas cortas sobre quebradas chicas "
                                          "de días lluviosos sin daño (hipótesis v4 rechazada)."},
    })


def level_for(context: dict[str, Any]) -> str:
    """Level the chat must show: the worst among the districts in focus (Centinela's decision)."""
    levels = [d["nivel"] for d in context["focus"] if d.get("nivel") in LEVEL_ORDER]
    return max(levels, key=LEVEL_ORDER.index) if levels else "sin_datos"
