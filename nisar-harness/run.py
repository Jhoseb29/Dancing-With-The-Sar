#!/usr/bin/env python3
"""NISAR Harness - pregunta en lenguaje natural -> análisis radar -> explicación.

    texto ─► intención (Claude, 1 turno) ─► catálogo NASA CMR ─► streaming desde AWS S3
          ─► mapas + métricas físicas (deterministas) ─► explicación (Claude, 1 turno) ─► payload UI

Cada ejecución escribe en output/runs/<YYYYMMDD_HHMMSS>/ (output/latest apunta a la última).

Ejemplos:
    uv run python run.py "¿Cómo están las lagunas de la cuenca de Cochabamba?"
    uv run python run.py "incendios recientes en la Chiquitania" --events
    uv run python run.py --request request.json      # {"text": "...", ...} desde el backend
"""
from __future__ import annotations

import argparse
import sys

from lib import cli
from lib.pipeline import run_pipeline
from lib.settings import Settings, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_text_arg(parser)
    cli.add_override_args(parser)
    cli.add_interpret_args(parser)
    parser.add_argument("--events", action="store_true",
                        help="Emitir el progreso como JSON lines por stdout (para SSE/WebSocket)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    req = cli.build_request(args)
    if not req.text and not req.bbox:
        parser.error("Escribe una pregunta, ej.: run.py \"inundaciones en el río Rocha\"")

    setup_logging(args.verbose, stream=sys.stderr if args.events else None)
    run = run_pipeline(req, Settings.from_env(), echo_events=args.events)

    status = run.manifest.get("status")
    if not args.events:
        print(f"\nCorrida {run.run_id}: {status}\n  {run.ui_payload_json}")
    return 0 if status in ("ok", "partial", "needs_clarification", "no_data") else 1


if __name__ == "__main__":
    sys.exit(main())
