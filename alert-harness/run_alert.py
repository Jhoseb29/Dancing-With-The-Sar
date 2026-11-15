#!/usr/bin/env python3
"""Genera UNA alerta (validada con JSON Schema) para un área y un día, y la publica en output/alerts/.

    uv run python run_alert.py --case viloma-2026-01
    uv run python run_alert.py --nombre "Zona sur Cochabamba" --bbox -66.18 -17.47 -66.10 -17.42 --fecha 2026-11-14
El backend (compute-py, /api/alerts/ws) empuja cada alerta nueva por WebSocket a la UI.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from alerts.engine import Request, evaluate
from alerts.evaluate import load_cases
from alerts.publish import publish
from alerts.settings import Settings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--case", help="id de un caso de cases/")
    p.add_argument("--nombre")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"))
    p.add_argument("--fecha", help="YYYY-MM-DD")
    p.add_argument("--peligro", choices=["inundacion", "mazamorra", "deslizamiento"])
    p.add_argument("--radar", choices=["reuse", "run", "skip"], default="reuse")
    p.add_argument("--radar-run", help="Corrida del nisar-harness a reutilizar")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    st = Settings.load()

    if args.case:
        c = load_cases([args.case])[0]
        req = Request(c["nombre"], tuple(c["bbox"]), c["fecha"], c["peligro"], c.get("radar_run"), args.radar, c["id"])
    else:
        if not (args.nombre and args.bbox and args.fecha):
            p.error("usa --case o --nombre + --bbox + --fecha")
        req = Request(args.nombre, tuple(args.bbox), args.fecha, args.peligro, args.radar_run, args.radar)

    alert = evaluate(req, st)
    path = publish(alert, st.output_dir)
    print(json.dumps({k: alert[k] for k in ("nivel", "indice_riesgo", "confianza", "componentes", "motivos")},
                     ensure_ascii=False, indent=2))
    print(f"→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
