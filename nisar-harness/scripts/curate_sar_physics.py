#!/usr/bin/env python3
"""Paso 3 - Curación física SAR: multilook/speckle, limpieza NoData/outliers, dB, clases de dispersión, RVI y CPR.

Escribe granules/<id>/curated_metrics.json dentro de la corrida.
    uv run python scripts/curate_sar_physics.py                   # sobre output/latest
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import cli
from lib.pipeline import step_process
from lib.settings import Settings, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_run_dir_arg(parser)
    cli.add_override_args(parser)
    args = parser.parse_args()
    setup_logging()
    settings = Settings.from_env()
    run = cli.open_run(args, settings)
    req = cli.build_request(args, base=run.manifest.get("request"))
    results = step_process(run, settings, req, do_export=False, do_curate=True)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if any(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
