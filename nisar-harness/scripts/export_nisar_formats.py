#!/usr/bin/env python3
"""Paso 2 - Exportación multi-formato (GeoTIFF, PNG dB, RGB falso color, clases, histograma, KML, GeoJSON).

Procesa (streaming desde AWS) los gránulos seleccionados en la corrida (query.json).
    uv run python scripts/export_nisar_formats.py                 # sobre output/latest
"""
import argparse
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
    results = step_process(run, settings, req, do_export=True, do_curate=False)
    for r in results:
        print(r["granule_id"], r["status"], *(r.get("formats") or {}).values(), sep="\n  ")
    return 0 if any(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
