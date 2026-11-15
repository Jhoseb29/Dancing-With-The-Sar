"""Ejecuta el harness NISAR (`run.py "<pregunta>" --events`) y re-emite su progreso.

Cada línea de stdout del harness es un evento JSON (stage, message, progress). Al
terminar se agrega un evento `result` con el payload final para la UI, de modo que
el frontend recibe todo por un único stream NDJSON.

Usa subprocess + hilos (no asyncio) para funcionar igual en Linux y Windows.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.harness.domain.rules import HarnessError, run_dir

log = logging.getLogger(__name__)

PAYLOAD_FILE = "interpretacion_didactica_nisar.json"


def _event(stage: str, message: str, **data: Any) -> dict[str, Any]:
    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stage": stage, "message": message, **data}


class HarnessRun:
    """Una ejecución en curso. `events()` libera el cupo y mata el proceso al terminar."""

    def __init__(self, proc: subprocess.Popen[str], output_dir: Path, timeout_s: int, release: threading.Semaphore) -> None:
        self._proc = proc
        self._output_dir = output_dir
        self._release = release
        self._timer = threading.Timer(timeout_s, self._kill)
        self._timer.daemon = True
        self._timer.start()
        self.timed_out = False

    def _kill(self) -> None:
        if self._proc.poll() is None:
            self.timed_out = True
            self._proc.kill()

    def events(self) -> Iterator[dict[str, Any]]:
        run_id: str | None = None
        done: dict[str, Any] | None = None
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # stdout no-evento (no debería ocurrir con --events)
                run_id = event.get("run_id") or run_id
                if event.get("stage") == "done":
                    done = event
                yield event
            self._proc.wait(timeout=30)

            if self.timed_out:
                yield _event("error", "El análisis tardó demasiado y se canceló.", code="timeout", run_id=run_id)
            elif run_id and done:
                yield _event("result", "Resultado listo.", run_id=run_id, payload=self._payload(run_id))
            else:
                yield _event("error", "El análisis terminó sin resultado.", code="harness_failed",
                             run_id=run_id, exit_code=self._proc.returncode)
        finally:
            self._timer.cancel()
            if self._proc.poll() is None:  # cliente desconectado: no dejar el proceso huérfano
                self._proc.kill()
            self._release.release()

    def _payload(self, run_id: str) -> dict[str, Any] | None:
        path = run_dir(self._output_dir, run_id) / PAYLOAD_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class HarnessRunner:
    def __init__(self, harness_dir: Path, uv_bin: str, max_concurrent: int, timeout_s: int) -> None:
        self._harness_dir = harness_dir
        self._uv_bin = uv_bin
        self._timeout_s = timeout_s
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._log_file = harness_dir / "output" / "backend-runs.log"

    def start(self, question: str, sensor: str = "auto") -> HarnessRun:
        if not (self._harness_dir / "run.py").is_file():
            raise HarnessError("harness_missing", f"No se encontró el harness en {self._harness_dir}.")
        if not self._slots.acquire(blocking=False):
            raise HarnessError("busy", "Hay demasiados análisis en curso; intenta en unos minutos.")
        try:
            # `--` evita que una pregunta que empiece con "-" se lea como opción.
            cmd = [self._uv_bin, "run", "--project", str(self._harness_dir), "python", "run.py", "--events",
                   "--sensor", sensor, "--", question]
            env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
            # Windows: sin esto el harness escribe stdout en cp1252 y aquí se lee UTF-8.
            env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            self._log_file.parent.mkdir(parents=True, exist_ok=True)
            with self._log_file.open("a", encoding="utf-8") as stderr_log:
                proc = subprocess.Popen(  # noqa: S603 - lista de argumentos, sin shell
                    cmd, cwd=self._harness_dir, env=env, text=True, encoding="utf-8",
                    stdout=subprocess.PIPE, stderr=stderr_log, bufsize=1,
                )
        except Exception:
            self._slots.release()
            raise
        log.info("Harness iniciado (pid %s)", proc.pid)
        return HarnessRun(proc, self._harness_dir / "output", self._timeout_s, self._slots)
