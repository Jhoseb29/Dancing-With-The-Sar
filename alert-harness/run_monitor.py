#!/usr/bin/env python3
"""Monitoreo automático de los 15 distritos de Cochabamba.

    uv run python run_monitor.py --once           # una pasada (ideal para cron)
    uv run python run_monitor.py                  # ciclo cada `monitor.intervalo_min` (30 min)
    uv run python run_monitor.py --once --districts D9 D13

Cron equivalente (cada 30 min):
    */30 * * * * cd /ruta/alert-harness && uv run python run_monitor.py --once >> output/monitor/cron.log 2>&1
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from alerts.monitor import tick
from alerts.settings import Settings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--once", action="store_true", help="Una sola pasada y salir")
    p.add_argument("--districts", nargs="+", help="Solo estos distritos (ej. D9 D13)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    st = Settings.load()
    every = st.thresholds["monitor"]["intervalo_min"] * 60
    while True:
        rows = tick(st, only=args.districts)
        changed = [r for r in rows if r.get("publicada")]
        logging.info("Pasada lista: %d distritos, %d alertas publicadas", len(rows), len(changed))
        if args.once:
            return 0
        time.sleep(every)


if __name__ == "__main__":
    sys.exit(main())
