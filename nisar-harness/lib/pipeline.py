"""Pipeline steps. Each step reads/writes only inside the RunContext, so steps compose
in-process (run.py) or run standalone (scripts/*) over an existing run directory.

    text ─► intent ─► catalog (CMR) ─► stream from AWS ─► export + curate ─► interpret ─► UI payload
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
from typing import Any

from . import alerts_bridge, exporters, interpreter
from .access import GranuleSource, open_granule
from .catalog import CatalogQuery, CatalogResult, Granule, search_granules
from .catalog_sentinel1 import search_sentinel1
from .credentials import AwsCredentials, check_sts_identity
from .curation import curate
from .drainage import build_corridor, write_channels
from .exporters import DEFAULT_FORMATS
from .hotspots import THEME_KINDS, write_hotspots
from .intent import Intent, offline_intent, parse_intent
from .jsonio import read_json, write_json
from .run_context import RunContext
from .scene import LoadOptions, SarScene, load_scene
from .selection import Choice, choose
from .sensors import NISAR, SENTINEL1
from .sentinel1 import load_scene_sentinel1
from .settings import DEFAULT_COLLECTIONS, Settings
from .themes import get_theme

log = logging.getLogger("nisar.pipeline")

WIDEN_DAYS = 365  # if the requested window has no acquisitions, look back this far


@dataclass
class PipelineRequest:
    """Everything a UI/backend call can control. JSON-serialisable."""
    text: str | None = None  # natural-language question; fills the fields below
    bbox: tuple[float, float, float, float] | None = None
    temporal: str | None = None  # "2026-01-01T00:00:00Z,2026-12-31T23:59:59Z"
    theme: str | None = None
    collections: tuple[str, ...] = DEFAULT_COLLECTIONS
    limit: int = 60  # catalog page size (all takes in the window, to pick coverage + baseline)
    max_granules: int | None = None  # default: decided by the theme
    granule_ids: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=lambda: list(DEFAULT_FORMATS))
    frequency: str = "auto"
    access: str = "auto"  # auto | s3 | https
    sensor: str = "auto"  # auto (NISAR, fallback Sentinel-1) | nisar | sentinel-1
    target_mpix: float = 2.0
    max_read_mpix: float = 8.0
    interpret: bool = True
    model: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineRequest:
        known = {f.name for f in fields(cls)}
        req = cls(**{k: v for k, v in data.items() if k in known and v is not None})
        req.bbox = tuple(req.bbox) if req.bbox else None
        req.collections = tuple(req.collections)
        return req

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def apply_intent(self, intent: Intent) -> None:
        """Intent fills only what the caller did not set explicitly."""
        self.bbox = self.bbox or intent.bbox
        self.temporal = self.temporal or intent.temporal
        self.theme = self.theme or intent.theme
        if self.sensor == "auto" and intent.sensor != "auto":
            self.sensor = intent.sensor  # "con Sentinel-1" in the question
    @property
    def granules_to_process(self) -> int:
        return self.max_granules or get_theme(self.theme).granules

    def load_options(self) -> LoadOptions:
        return LoadOptions(bbox=self.bbox, frequency=self.frequency,
                           target_pixels=int(self.target_mpix * 1e6),
                           max_read_pixels=int(self.max_read_mpix * 1e6))


# ------------------------------------------------------------------ step 0
def step_intent(run: RunContext, settings: Settings, req: PipelineRequest) -> Intent:
    started = time.monotonic()
    run.emit("intent", "Entendiendo tu pregunta…", 0.02)
    try:
        intent = parse_intent(req.text, settings)
    except Exception as exc:  # noqa: BLE001 - Claude down / limit reached: the data path must still work
        log.warning("Parser de intención no disponible: %s", exc)
        run.emit("intent", "El asistente no está disponible; uso una interpretación básica de tu pregunta.", 0.04,
                 level="warning")
        intent = offline_intent(req.text, reason=str(exc))
    req.apply_intent(intent)
    run.manifest["intent"] = intent.to_dict()
    run.manifest["request"] = req.to_dict()
    run.record_step("intent", "needs_clarification" if intent.needs_clarification else "ok", started,
                    usage=intent.usage)
    if not intent.needs_clarification:
        run.emit("intent", f"Analizaré «{get_theme(intent.theme).label}» en {intent.place_name} "
                           f"({intent.start_date} → {intent.end_date})", 0.08,
                 place=intent.place_name, bbox=intent.bbox, theme=intent.theme)
    return intent


# ------------------------------------------------------------------ step 1
MIN_COVERAGE = 0.7  # NISAR below this AOI coverage -> try Sentinel-1


def _search(searcher, query: CatalogQuery, settings: Settings, req: PipelineRequest) -> tuple[CatalogResult, bool]:
    """Catalog search; if the requested window is empty, widen it to WIDEN_DAYS (same end date)."""
    result = searcher(query, settings)
    if result.granules or not req.temporal:
        return result, False
    end = req.temporal.split(",")[1]
    start = (date.fromisoformat(end[:10]) - timedelta(days=WIDEN_DAYS)).isoformat()
    widened = CatalogQuery(bbox=query.bbox, temporal=f"{start}T00:00:00Z,{end}", collections=query.collections,
                           limit=query.limit)
    result = searcher(widened, settings)
    return result, bool(result.granules)


def _adequate(choice: Choice, needed: int) -> bool:
    """Enough takes for the theme (2 for change detection) and good AOI coverage."""
    if not choice.granules:
        return False
    enough = len(choice.granules) >= min(needed, 2)
    return enough and max(choice.coverage.values()) >= MIN_COVERAGE


def step_query(run: RunContext, settings: Settings, req: PipelineRequest) -> list[Granule]:
    """NISAR first; Sentinel-1 (OPERA RTC) when NISAR has no usable takes or poor coverage."""
    started = time.monotonic()
    needed = req.granules_to_process
    query = CatalogQuery(bbox=req.bbox, temporal=req.temporal, collections=req.collections, limit=req.limit)

    nisar = sentinel1 = None
    nisar_choice = sentinel1_choice = Choice([], {}, "")
    if req.sensor in ("auto", "nisar"):
        run.emit("query", "Buscando pasadas del satélite NISAR en el catálogo de NASA…", 0.10)
        nisar = _search(search_granules, query, settings, req)
        nisar_choice = choose(nisar[0].granules, needed, req.bbox)
    use_sentinel1 = req.sensor == SENTINEL1.key or (req.sensor == "auto" and not _adequate(nisar_choice, needed))
    if use_sentinel1:
        run.emit("query", "NISAR no tiene tomas suficientes aquí; busco también Sentinel-1 (ESA)…", 0.12)
        sentinel1 = _search(search_sentinel1, CatalogQuery(bbox=req.bbox, temporal=req.temporal,
                                             collections=SENTINEL1.collections, limit=req.limit), settings, req)
        sentinel1_choice = choose(sentinel1[0].granules, needed, req.bbox)

    # Keep NISAR unless Sentinel-1 is clearly better (adequate when NISAR is not, or more coverage/takes).
    def score(c: Choice) -> tuple:
        return (_adequate(c, needed), len(c.granules) >= min(needed, 2),
                max(c.coverage.values(), default=0.0), len(c.granules))
    pick_sentinel1 = sentinel1 is not None and (nisar is None or score(sentinel1_choice) > score(nisar_choice))
    (result, widened), sensor = (sentinel1, SENTINEL1) if pick_sentinel1 else (nisar, NISAR)

    payload = result.to_dict()
    payload["sensor"] = sensor.key
    payload["sensor_label"] = sensor.label
    payload["sensor_reason"] = (
        "Sentinel-1 elegido: NISAR sin tomas suficientes o con cobertura baja en esta zona y fecha"
        if pick_sentinel1 else "NISAR (sensor principal)")
    payload["alternatives"] = {
        k: {"takes": len(c.granules), "best_coverage": max(c.coverage.values(), default=0.0)}
        for k, c, r in ((NISAR.key, nisar_choice, nisar), (SENTINEL1.key, sentinel1_choice, sentinel1)) if r is not None
    }
    payload["temporal_widened"] = widened
    payload["aws_sts"] = check_sts_identity(AwsCredentials.load(settings.aws_credentials_file))
    payload["earthdata_token_present"] = bool(settings.earthdata_token)
    write_json(run.query_json, payload)
    run.record_step("query", "ok", started, sensor=sensor.key, total_hits=result.total_hits,
                    returned=len(result.granules), temporal_widened=widened,
                    alternatives=payload["alternatives"], aws_sts=payload["aws_sts"]["status"])
    if widened:
        run.emit("query", "No hubo pasadas en ese periodo; amplié la búsqueda a 12 meses.", 0.13)
    run.emit("query", f"Usaré {sensor.label}: {len(result.granules)} pasadas sobre el área.", 0.15,
             sensor=sensor.key, dates=[g.time_start[:10] for g in result.granules])
    return result.granules


def resolve_sources(run: RunContext, req: PipelineRequest) -> list[GranuleSource]:
    if not run.query_json.exists():
        raise FileNotFoundError("La corrida no tiene query.json: ejecuta primero la consulta")
    granules = [Granule.from_dict(g) for g in read_json(run.query_json)["granules"]]
    choice = choose(granules, req.granules_to_process, req.bbox, req.granule_ids)
    run.manifest["selection"] = {"group": choice.group, "coverage": choice.coverage,
                                 "dates": [g.time_start[:10] for g in choice.granules]}
    run.save_manifest()
    if choice.granules:
        best = max(choice.coverage.values())
        dates = " y ".join(sorted({g.time_start[:10] for g in choice.granules}))
        run.emit("query", f"Elegí la órbita que mejor cubre el área ({best:.0%}): {dates}.", 0.15)
    return [GranuleSource.from_granule(g) for g in choice.granules]


def load(src: GranuleSource, settings: Settings, req: PipelineRequest) -> SarScene:
    if src.sensor == SENTINEL1.key:
        return load_scene_sentinel1(src, settings, req.load_options(), prefer=req.access)
    with open_granule(src, settings, prefer=req.access) as (h5, mode):
        return load_scene(h5, src.granule_id, mode, req.load_options())


# ------------------------------------------------------------------ steps 2 & 3
def step_export(run: RunContext, scene: SarScene, req: PipelineRequest) -> dict[str, str]:
    gdir = run.granule_dir(scene.granule_id)
    files = {fmt: run.rel(p) for fmt, p in exporters.export_all(scene, gdir / "formats", req.formats).items()}
    write_json(gdir / "formats.json", files)
    return files


def step_curate(run: RunContext, scene: SarScene) -> dict[str, Any]:
    metrics = curate(scene)
    write_json(run.granule_dir(scene.granule_id) / "curated_metrics.json", metrics)
    return metrics


def step_process(run: RunContext, settings: Settings, req: PipelineRequest,
                 do_export: bool = True, do_curate: bool = True) -> list[dict[str, Any]]:
    started = time.monotonic()
    sources = resolve_sources(run, req)
    results = []
    for i, src in enumerate(sources):
        base = 0.15 + 0.65 * i / max(len(sources), 1)
        span = 0.65 / max(len(sources), 1)
        item: dict[str, Any] = {"granule_id": src.granule_id}
        try:
            run.emit("process", f"Leyendo imagen radar {i + 1}/{len(sources)} directo desde AWS…", round(base, 2))
            scene = load(src, settings, req)
            item.update(access_mode=scene.access_mode, frequency=scene.radar.frequency,
                        date=(scene.identification.start_time or "")[:10],
                        shape=list(scene.shape), pixel_spacing_m=scene.pixel_spacing_m)
            if do_export:
                run.emit("process", f"Generando mapas e imágenes ({item['date']})…", round(base + span * 0.6, 2))
                item["formats"] = step_export(run, scene, req)
            if do_curate:
                item["scattering"] = step_curate(run, scene)["physical_scattering_breakdown"]
            item["status"] = "ok"
            run.emit("process", f"Imagen del {item['date']} lista.", round(base + span, 2), granule=item)
        except Exception as exc:
            log.exception("Fallo procesando %s", src.granule_id)
            item.update(status="error", error=str(exc))
            run.emit("process", f"No se pudo procesar una imagen: {exc}", round(base + span, 2), level="warning")
        results.append(item)
    ok = sum(r["status"] == "ok" for r in results)
    status = "ok" if results and ok == len(results) else ("partial" if ok else "error")
    run.record_step("process", status, started, granules=results)
    return results


# ------------------------------------------------------------------ step 3b
def step_change(run: RunContext, req: PipelineRequest) -> dict[str, Any] | None:
    """Cell-by-cell change hotspots between the oldest and newest take (needs the globe grid)."""
    started = time.monotonic()
    takes = []
    for gdir in run.granule_dirs():
        index, metrics = gdir / "formats.json", gdir / "curated_metrics.json"
        if index.exists() and metrics.exists() and "globe" in read_json(index):
            date = read_json(metrics)["acquisition"].get("start_time") or ""
            takes.append((date, run.run_dir / read_json(index)["globe"]))
    takes.sort()
    try:
        theme = req.theme or "general"
        corridor = None
        if len(takes) >= 2 and "nuevo_sedimento" in THEME_KINDS.get(theme, THEME_KINDS["general"]):
            run.emit("change", "Buscando ríos y torrenteras del área para ubicar sedimento…", 0.82)
            corridor = build_corridor(read_json(takes[-1][1]))
            write_channels(corridor, run.channels_geojson)
        summary = write_hotspots([p for _, p in takes], theme, run.hotspots_geojson, corridor)
    except ValueError as exc:  # grids differ (should not happen: same AOI)
        log.warning("Hotspots: %s", exc)
        summary = None
    run.record_step("change", "ok" if summary else "skipped", started, hotspots=summary)
    if summary:
        found = sum(k["cells"] for k in summary["kinds"].values())
        run.emit("change", f"Comparé {summary['from_date']} y {summary['to_date']}: {found} celdas con cambios.", 0.83)
    return summary


# ------------------------------------------------------------------ step 4
def step_interpret(run: RunContext, settings: Settings, req: PipelineRequest) -> dict[str, Any]:
    started = time.monotonic()
    context = interpreter.build_context(run)
    usage = [run.manifest.get("steps", {}).get("intent", {}).get("usage")]
    interpret_usage = None
    status = "skipped"
    if req.interpret and context["dates"]:
        run.emit("interpret", "Preparando la explicación…", 0.85)
        try:
            interpret_usage = interpreter.interpret(run, settings, req.model)
            usage.append(interpret_usage)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - data is still delivered without narrative
            log.error("Intérprete: %s", exc)
            status = "error"
            run.emit("interpret", "No pude generar la explicación; te muestro los datos.", 0.95, level="warning")
    payload = interpreter.assemble_ui_payload(run, [u for u in usage if u])
    run.record_step("interpret", status, started, payload_status=payload["status"], usage=interpret_usage)
    return payload


# ------------------------------------------------------------------ alert mode
def step_alerts(run: RunContext, settings: Settings, req: PipelineRequest, intent: Intent) -> dict[str, Any]:
    """Same chat, no radar download: explain Centinela's current alerts with its own data."""
    started = time.monotonic()
    root = settings.alert_harness_dir
    if not alerts_bridge.available(root):
        msg = "Centinela todavía no publicó alertas (corre el monitor de alertas)."
        interpreter.clarification_payload(run, msg)
        run.record_step("alerts", "no_data", started)
        return {"status": "no_data", "message": msg}
    run.emit("alerts", "Leyendo las alertas vigentes de Centinela…", 0.3)
    context = alerts_bridge.build_context(intent.text, root)
    write_json(run.context_json, context)
    focus = ", ".join(f"{d['id']} {d.get('nivel')}" for d in context["focus"])
    run.emit("alerts", f"Distritos a explicar: {focus}", 0.45)
    usage = [run.manifest.get("steps", {}).get("intent", {}).get("usage")]
    explain_usage, status = None, "skipped"
    if req.interpret:
        run.emit("interpret", "Preparando la explicación…", 0.6)
        try:
            explain_usage = interpreter.explain(run, settings, alerts_bridge.role(root), context, req.model,
                                                level=alerts_bridge.level_for(context))
            usage.append(explain_usage)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - the data is still shown on the alerts map
            log.error("Explicación de alertas: %s", exc)
            status = "error"
    payload = interpreter.assemble_alerts_payload(run, context, [u for u in usage if u])
    run.record_step("alerts", status, started, focus=[d["id"] for d in context["focus"]], usage=explain_usage)
    return payload


# ------------------------------------------------------------------ full run
def run_pipeline(req: PipelineRequest, settings: Settings, echo_events: bool = False) -> RunContext:
    run = RunContext.create(settings.output_dir, req.to_dict())
    run.echo_events = echo_events
    try:
        if req.text:
            intent = step_intent(run, settings, req)
            if intent.needs_clarification:
                interpreter.clarification_payload(run, intent.clarification_question)
                run.emit("done", intent.clarification_question, 1.0, status="needs_clarification")
                run.finish("needs_clarification")
                return run
            if intent.mode == "alertas":
                payload = step_alerts(run, settings, req, intent)
                status = "ok" if payload["status"] == "complete" else payload["status"]
                run.emit("done", "Explicación lista." if status == "ok" else payload.get("message", "Listo."), 1.0,
                         status=status, payload=run.rel(run.ui_payload_json))
                run.finish(status)
                return run
        req.bbox = req.bbox or settings.default_bbox
        run.manifest["request"] = req.to_dict()

        if not step_query(run, settings, req):
            msg = "No encontré pasadas de NISAR sobre esa zona en el último año."
            interpreter.clarification_payload(run, msg)
            run.emit("done", msg, 1.0, status="no_data")
            run.finish("no_data")
            return run
        results = step_process(run, settings, req)
        if not any(r["status"] == "ok" for r in results):
            run.emit("done", "No se pudo leer ninguna imagen del satélite.", 1.0, status="error")
            run.finish("error")
            return run
        step_change(run, req)
        payload = step_interpret(run, settings, req)
        all_ok = all(r["status"] == "ok" for r in results)
        interpreted_ok = not req.interpret or payload["status"] == "complete"
        status = "ok" if all_ok and interpreted_ok else "partial"
        run.emit("done", "Análisis listo.", 1.0, status=status, payload=run.rel(run.ui_payload_json))
        run.finish(status)
    except Exception as exc:
        run.emit("done", f"Error: {exc}", 1.0, status="error", level="error")
        run.finish("error")
        raise
    return run
