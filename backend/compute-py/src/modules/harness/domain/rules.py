"""Reglas del módulo harness: validación de preguntas, ids de corrida y archivos servibles."""

from __future__ import annotations

import re
from pathlib import Path

RUN_ID = re.compile(r"^\d{8}_\d{6}(_\d+)?$")  # output/runs/<YYYYMMDD_HHMMSS>[_n]
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Solo lo que la UI necesita mostrar o descargar.
SERVABLE_TYPES = {
    ".png": "image/png",
    ".tif": "image/tiff",
    ".kml": "application/vnd.google-earth.kml+xml",
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
}


class HarnessError(Exception):
    """Error con código estable para la API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def clean_question(text: str, max_chars: int) -> str:
    cleaned = _CONTROL.sub(" ", text or "").strip()
    if not cleaned:
        raise HarnessError("empty_question", "Escribe una pregunta.")
    if len(cleaned) > max_chars:
        raise HarnessError("too_long", f"La pregunta supera {max_chars} caracteres.")
    return cleaned


def run_dir(output_dir: Path, run_id: str) -> Path:
    if not RUN_ID.match(run_id):
        raise HarnessError("bad_run_id", "Identificador de corrida inválido.")
    path = output_dir / "runs" / run_id
    if not path.is_dir():
        raise HarnessError("run_not_found", "La corrida no existe.")
    return path


def servable_file(output_dir: Path, run_id: str, relative: str) -> tuple[Path, str]:
    """Resuelve un archivo de una corrida impidiendo salir de su carpeta (path traversal)."""
    base = run_dir(output_dir, run_id).resolve()
    target = (base / relative).resolve()
    media_type = SERVABLE_TYPES.get(target.suffix.lower())
    if not target.is_relative_to(base) or media_type is None or not target.is_file():
        raise HarnessError("file_not_found", "Archivo no disponible.")
    return target, media_type
