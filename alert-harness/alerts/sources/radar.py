"""Radar evidence from the nisar-harness (NISAR, or Sentinel-1 fallback) - consumed as a separate harness.

Either reuse an existing run (case.radar_run) or launch the nisar-harness CLI without the
language model (`--no-interpret`), then read its deterministic outputs:
curated_metrics.json (per take) and hotspots.geojson (change summary + sediment corridor).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("alerts.radar")


@dataclass
class RadarEvidence:
    run_id: str
    sensor: str | None
    dates: list[str]
    spans_event: bool  # oldest take before the event and newest after it
    valid_pixels_pct: float | None
    kinds: dict[str, Any] = field(default_factory=dict)  # hotspot kinds -> {cells, area_km2, pct_of_area}
    corridor: dict[str, Any] | None = None
    scene_shift_db: dict[str, Any] | None = None


def _read_run(run_dir: Path, event_day: str) -> RadarEvidence:
    metrics = [json.loads(p.read_text()) for p in sorted(run_dir.glob("granules/*/curated_metrics.json"))]
    dates = sorted((m["acquisition"].get("start_time") or "")[:10] for m in metrics)
    hotspots = run_dir / "hotspots.geojson"
    summary = json.loads(hotspots.read_text()).get("summary", {}) if hotspots.exists() else {}
    return RadarEvidence(
        run_id=run_dir.name,
        sensor=metrics[0]["radar_physics"].get("mission") if metrics else None,
        dates=dates,
        spans_event=bool(dates) and dates[0] < event_day <= dates[-1],
        valid_pixels_pct=min((m["data_quality"]["valid_pixels_pct"] for m in metrics), default=None),
        kinds=summary.get("kinds", {}),
        corridor=summary.get("sediment_corridor"),
        scene_shift_db=summary.get("scene_shift_db"),
    )


def _launch(nisar_dir: Path, uv_bin: str, bbox: tuple[float, ...], event_day: str, hazard: str) -> Path:
    day = date.fromisoformat(event_day)
    temporal = f"{(day - timedelta(days=35)).isoformat()}T00:00:00Z,{(day + timedelta(days=21)).isoformat()}T23:59:59Z"
    theme = "inundacion" if hazard in ("inundacion", "mazamorra") else "vegetacion"
    cmd = [uv_bin, "run", "--project", str(nisar_dir), "python", "run.py", "--events", "--no-interpret",
           "--bbox", *map(str, bbox), "--temporal", temporal, "--theme", theme]
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    log.info("Lanzando nisar-harness para %s (%s)…", event_day, hazard)
    proc = subprocess.run(cmd, cwd=nisar_dir, env=env, capture_output=True, text=True, timeout=1800, check=False)
    run_id = None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        run_id = event.get("run_id") or run_id
    if not run_id:
        raise RuntimeError(f"nisar-harness no devolvió corrida (rc={proc.returncode}): {proc.stderr[-300:]}")
    return nisar_dir / "output" / "runs" / run_id


def evidence(nisar_dir: Path, uv_bin: str, bbox: tuple[float, ...], event_day: str, hazard: str,
             run_id: str | None = None, mode: str = "reuse") -> RadarEvidence | None:
    """mode: reuse (only case.radar_run) | run (launch if no run given) | skip."""
    if mode == "skip":
        return None
    if run_id:
        run_dir = nisar_dir / "output" / "runs" / run_id
        if run_dir.is_dir():
            return _read_run(run_dir, event_day)
        log.warning("Corrida radar %s no encontrada", run_id)
    if mode == "run":
        return _read_run(_launch(nisar_dir, uv_bin, bbox, event_day, hazard), event_day)
    return None
