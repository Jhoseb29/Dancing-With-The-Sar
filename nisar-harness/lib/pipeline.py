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

from . import exporters, interpreter
from .access import GranuleSource, open_granule
from .catalog import CatalogQuery, Granule, search_granules
from .credentials import AwsCredentials, check_sts_identity
from .curation import curate
from .intent import Intent, parse_intent
from .jsonio import read_json, write_json
from .run_context import RunContext
from .scene import LoadOptions, SarScene, load_scene
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
    limit: int = 20  # catalog page size
    max_granules: int | None = None  # default: decided by the theme
    granule_ids: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=lambda: ["all"])
    frequency: str = "auto"
    access: str = "auto"  # auto | s3 | https
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
    intent = parse_intent(req.text, settings)
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
def step_query(run: RunContext, settings: Settings, req: PipelineRequest) -> list[Granule]:
    started = time.monotonic()
    run.emit("query", "Buscando pasadas del satélite NISAR en el catálogo de NASA…", 0.10)
    query = CatalogQuery(bbox=req.bbox, temporal=req.temporal, collections=req.collections, limit=req.limit)
    result = search_granules(query, settings)
    widened = False
    if not result.granules and req.temporal:
        end = req.temporal.split(",")[1][:10]
        start = (date.fromisoformat(end) - timedelta(days=WIDEN_DAYS)).isoformat()
        query.temporal = f"{start}T00:00:00Z,{req.temporal.split(',')[1]}"
        result = search_granules(query, settings)
        widened = bool(result.granules)
        run.emit("query", "No hubo pasadas en ese periodo; amplié la búsqueda a 12 meses.", 0.12)
    payload = result.to_dict()
    payload["temporal_widened"] = widened
    payload["aws_sts"] = check_sts_identity(AwsCredentials.load(settings.aws_credentials_file))
    payload["earthdata_token_present"] = bool(settings.earthdata_token)
    write_json(run.query_json, payload)
    run.record_step("query", "ok", started, total_hits=result.total_hits, returned=len(result.granules),
                    temporal_widened=widened, aws_sts=payload["aws_sts"]["status"])
    run.emit("query", f"Encontré {len(result.granules)} pasadas del satélite sobre el área.", 0.15,
             dates=[g.time_start[:10] for g in result.granules])
    return result.granules


def select_granules(granules: list[Granule], count: int, ids: list[str] | None = None) -> list[Granule]:
    """Newest acquisition first, then older ones from the SAME track/direction (comparable geometry)."""
    if ids:
        return [g for g in granules if g.granule_id in ids]
    if not granules:
        return []
    newest = granules[0]
    same_geometry = [g for g in granules[1:]
                     if (g.track, g.orbit_direction) == (newest.track, newest.orbit_direction)]
    return [newest, *same_geometry][: max(count, 1)]


def resolve_sources(run: RunContext, req: PipelineRequest) -> list[GranuleSource]:
    if not run.query_json.exists():
        raise FileNotFoundError("La corrida no tiene query.json: ejecuta primero la consulta")
    granules = [Granule.from_dict(g) for g in read_json(run.query_json)["granules"]]
    return [GranuleSource.from_granule(g) for g in select_granules(granules, req.granules_to_process,
                                                                    req.granule_ids)]


def load(src: GranuleSource, settings: Settings, req: PipelineRequest) -> SarScene:
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


# ------------------------------------------------------------------ step 4
def step_interpret(run: RunContext, settings: Settings, req: PipelineRequest) -> dict[str, Any]:
    started = time.monotonic()
    context = interpreter.build_context(run)
    usage = [run.manifest.get("steps", {}).get("intent", {}).get("usage")]
    status = "skipped"
    if req.interpret and context["dates"]:
        run.emit("interpret", "Preparando la explicación…", 0.85)
        try:
            usage.append(interpreter.interpret(run, settings, req.model))
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - data is still delivered without narrative
            log.error("Intérprete: %s", exc)
            status = "error"
            run.emit("interpret", "No pude generar la explicación; te muestro los datos.", 0.95, level="warning")
    payload = interpreter.assemble_ui_payload(run, [u for u in usage if u])
    run.record_step("interpret", status, started, payload_status=payload["status"])
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
