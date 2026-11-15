"""Shared argparse definitions so run.py and every step script accept the same options."""
from __future__ import annotations

import argparse
from pathlib import Path

from .exporters import EXPORTERS
from .jsonio import read_json
from .pipeline import PipelineRequest
from .run_context import RunContext
from .settings import Settings
from .themes import THEMES


def add_text_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("text", nargs="?", help='Pregunta en lenguaje natural, ej. "incendios recientes en la Chiquitania"')
    p.add_argument("--request", type=Path, help="JSON con un PipelineRequest (lo que envía el backend)")


def add_override_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("ajustes avanzados (opcionales; sobrescriben lo que se entendió del texto)")
    g.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    g.add_argument("--temporal", help="Rango ISO: 2026-01-01T00:00:00Z,2026-12-31T23:59:59Z")
    g.add_argument("--theme", choices=list(THEMES))
    g.add_argument("--collections", nargs="+", help="Short names CMR (default: GCOV V1/PROVISIONAL/BETA)")
    g.add_argument("--max-granules", type=int, help="Fechas a analizar (default: según el tema)")
    g.add_argument("--granule-id", nargs="+", dest="granule_ids", help="Procesar estos gránulos del catálogo")
    g.add_argument("--formats", nargs="+", choices=["all", *EXPORTERS])
    g.add_argument("--frequency", choices=["auto", "frequencyA", "frequencyB"])
    g.add_argument("--access", choices=["auto", "s3", "https"])
    g.add_argument("--sensor", choices=["auto", "nisar", "sentinel-1"],
                   help="Radar: auto = NISAR y, si no hay tomas útiles, Sentinel-1 (default)")
    g.add_argument("--target-mpix", type=float, help="Megapíxeles de análisis tras multilook (default 2)")
    g.add_argument("--max-read-mpix", type=float, help="Presupuesto de lectura remota por capa (default 8)")


def add_interpret_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("intérprete (Claude Code, suscripción)")
    g.add_argument("--no-interpret", dest="interpret", action="store_false", default=None,
                   help="Solo datos y mapas, sin explicación del modelo")
    g.add_argument("--model", help="Modelo del intérprete (default CLAUDE_INTERPRET_MODEL o sonnet)")


def add_run_dir_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--run-dir", type=Path, help="Corrida existente (default: output/latest)")


def explicit_args(args: argparse.Namespace) -> dict:
    """Only the PipelineRequest fields the user actually passed on the command line."""
    return {k: v for k in PipelineRequest.__dataclass_fields__ if (v := getattr(args, k, None)) is not None}


def build_request(args: argparse.Namespace, base: dict | None = None) -> PipelineRequest:
    """Merge order: defaults < base (existing run) < --request JSON < explicit CLI flags."""
    data = dict(base or {})
    if getattr(args, "request", None):
        data.update(read_json(args.request))
    data.update(explicit_args(args))
    return PipelineRequest.from_dict(data)


def open_run(args: argparse.Namespace, settings: Settings) -> RunContext:
    run_dir = getattr(args, "run_dir", None) or settings.output_dir / "latest"
    if not run_dir.exists():
        raise SystemExit(f"No existe la corrida {run_dir}. Ejecuta primero run.py o scripts/input_data.py")
    return RunContext.open(run_dir)
