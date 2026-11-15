#!/usr/bin/env python3
"""Paso 0+1 - Pregunta en texto -> intención -> catálogo NASA CMR. Crea una corrida nueva.

    uv run python scripts/input_data.py "incendios recientes en la Chiquitania"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import cli
from lib.pipeline import step_intent, step_query
from lib.run_context import RunContext
from lib.settings import Settings, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_text_arg(parser)
    cli.add_override_args(parser)
    args = parser.parse_args()
    setup_logging()
    settings = Settings.from_env()
    req = cli.build_request(args)
    run = RunContext.create(settings.output_dir, req.to_dict())
    if req.text:
        intent = step_intent(run, settings, req)
        if intent.needs_clarification:
            print(intent.clarification_question)
            return 2
    req.bbox = req.bbox or settings.default_bbox
    granules = step_query(run, settings, req)
    for i, g in enumerate(granules, 1):
        print(f"[{i}] {g.time_start[:19]}  track {g.track} {g.orbit_direction or '-':10} {g.granule_id}")
    print(f"\nCorrida: {run.run_dir}")
    return 0 if granules else 2


if __name__ == "__main__":
    sys.exit(main())
