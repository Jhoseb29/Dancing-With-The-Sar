#!/usr/bin/env python3
"""Evalúa el generador de alertas contra los casos reales (cases/*.json) y guarda el puntaje.

    uv run python run_eval.py                         # todos los casos, radar solo si el caso trae corrida
    uv run python run_eval.py --radar run             # lanza el nisar-harness para los casos sin corrida (lento)
    uv run python run_eval.py --cases viloma-2026-01 --nota "umbral 72h 25->20"
"""
from __future__ import annotations

import argparse
import logging
import sys

from alerts.evaluate import load_cases, run_case, score, write_report
from alerts.settings import Settings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cases", nargs="+", help="Solo estos ids")
    p.add_argument("--radar", choices=["reuse", "run", "skip"], default="reuse")
    p.add_argument("--nota", default="", help="Qué cambió respecto de la evaluación anterior")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    st = Settings.load()
    cases = load_cases(args.cases)
    results = [run_case(c, st, args.radar) for c in cases]
    summary = score(results)
    out = write_report(results, summary, st, args.nota)
    print((out / "scorecard.md").read_text())
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
