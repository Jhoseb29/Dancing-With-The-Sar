#!/usr/bin/env python3
"""Paso 4 - Intérprete: contexto compacto -> 1 llamada a Claude (rol = skill) -> chat + lección + payload UI.

    uv run python scripts/interpret.py                     # re-interpreta output/latest (1 llamada, sin tools)
    uv run python scripts/interpret.py --no-interpret      # solo contexto + payload (sin modelo)
    uv run python scripts/interpret.py --run-dir output/runs/20261114_233317 --model opus
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import cli
from lib.pipeline import step_interpret
from lib.settings import Settings, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_run_dir_arg(parser)
    cli.add_interpret_args(parser)
    args = parser.parse_args()
    setup_logging()
    settings = Settings.from_env()
    run = cli.open_run(args, settings)
    req = cli.build_request(args, base=run.manifest.get("request"))
    payload = step_interpret(run, settings, req)
    print(f"Payload ({payload['status']}): {run.ui_payload_json}")
    for issue in payload["validation_issues"]:
        print(f"  - {issue}")
    return 0 if payload["status"] == "complete" or not req.interpret else 1


if __name__ == "__main__":
    sys.exit(main())
