"""Timestamped run directories: every pipeline execution gets its own folder.

Layout::

    output/runs/<YYYYMMDD_HHMMSS>/
        run_manifest.json
        query.json
        granules/<granule_id>/curated_metrics.json
        granules/<granule_id>/formats/...
        interpreter_context.json
        events.jsonl                     (progreso para la UI)
        interpretation.md                (lección)
        interpretation_narrative.json    (mensaje corto de chat)
        interpretacion_didactica_nisar.json
    output/latest -> runs/<id>
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .jsonio import read_json, write_json

log = logging.getLogger("nisar.run")

RUN_ID_FORMAT = "%Y%m%d_%H%M%S"


@dataclass
class RunContext:
    run_id: str
    run_dir: Path
    output_dir: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    echo_events: bool = False  # also print events as JSON lines on stdout (backend -> SSE/WebSocket)

    # ---------- construction ----------
    @classmethod
    def create(cls, output_dir: Path, request: dict[str, Any]) -> RunContext:
        runs_dir = output_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = datetime.now(timezone.utc).strftime(RUN_ID_FORMAT)
        run_dir = runs_dir / run_id
        suffix = 1
        while run_dir.exists():
            run_dir = runs_dir / f"{run_id}_{suffix}"
            suffix += 1
        run_dir.mkdir()
        ctx = cls(run_dir.name, run_dir, output_dir)
        ctx.manifest = {
            "run_id": ctx.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "request": request,
            "steps": {},
            "status": "running",
        }
        ctx.save_manifest()
        ctx._point_latest()
        return ctx

    @classmethod
    def open(cls, run_dir: Path) -> RunContext:
        run_dir = run_dir.resolve()
        manifest_path = run_dir / "run_manifest.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {"run_id": run_dir.name, "steps": {}}
        return cls(run_dir.name, run_dir, run_dir.parent.parent, manifest)

    # ---------- paths ----------
    @property
    def query_json(self) -> Path:
        return self.run_dir / "query.json"

    @property
    def context_json(self) -> Path:
        return self.run_dir / "interpreter_context.json"

    @property
    def interpretation_md(self) -> Path:
        return self.run_dir / "interpretation.md"

    @property
    def narrative_json(self) -> Path:
        return self.run_dir / "interpretation_narrative.json"

    @property
    def events_jsonl(self) -> Path:
        return self.run_dir / "events.jsonl"

    @property
    def ui_payload_json(self) -> Path:
        return self.run_dir / "interpretacion_didactica_nisar.json"

    def granule_dir(self, granule_id: str) -> Path:
        path = self.run_dir / "granules" / granule_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def granule_dirs(self) -> list[Path]:
        root = self.run_dir / "granules"
        return sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []

    def rel(self, path: Path | str) -> str:
        """Path relative to the run dir (portable for the frontend)."""
        return str(Path(path).resolve().relative_to(self.run_dir))

    # ---------- progress events (what the UI shows while the run is going) ----------
    def emit(self, stage: str, message: str, progress: float | None = None, **data: Any) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "stage": stage,
            "message": message,
            "progress": progress,
            **data,
        }
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self.events_jsonl.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        if self.echo_events:
            print(line, file=sys.stdout, flush=True)
        log.info("[%s] %s", stage, message)

    # ---------- manifest ----------
    def record_step(self, name: str, status: str, started: float, **details: Any) -> None:
        self.manifest.setdefault("steps", {})[name] = {
            "status": status,
            "duration_s": round(time.monotonic() - started, 2),
            **details,
        }
        self.save_manifest()

    def finish(self, status: str) -> None:
        self.manifest["status"] = status
        self.manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.save_manifest()

    def save_manifest(self) -> None:
        write_json(self.run_dir / "run_manifest.json", self.manifest)

    def _point_latest(self) -> None:
        latest = self.output_dir / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(Path("runs") / self.run_id, target_is_directory=True)
        except OSError:
            (self.output_dir / "LATEST").write_text(self.run_id, encoding="utf-8")
