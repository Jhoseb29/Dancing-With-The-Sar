"""Endpoints del harness NISAR.

POST /api/harness/ask                         {"text": "..."} -> stream NDJSON de eventos + `result`
GET  /api/harness/runs/{run_id}               payload final de una corrida (recargar sin re-ejecutar)
GET  /api/harness/runs/{run_id}/files/{path}  imágenes y descargas de la corrida
"""

from __future__ import annotations

from typing import Literal

import json
from collections.abc import Iterator
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from config.settings import get_settings
from modules.harness.application.runner import PAYLOAD_FILE, HarnessRunner
from modules.harness.domain.rules import HarnessError, clean_question, run_dir, servable_file

router = APIRouter(prefix="/api/harness")

_STATUS = {
    "empty_question": 400, "too_long": 400, "bad_run_id": 400,
    "run_not_found": 404, "file_not_found": 404, "busy": 429, "harness_missing": 503,
}


class AskBody(BaseModel):
    text: str
    # Satélite para aprender/navegar: auto (NISAR y, si no cubre, Sentinel-1) | nisar | sentinel-1
    sensor: Literal["auto", "nisar", "sentinel-1"] = "auto"


@lru_cache
def runner() -> HarnessRunner:
    s = get_settings()
    return HarnessRunner(s.harness_dir, s.harness_uv_bin, s.harness_max_concurrent, s.harness_timeout_s)


def _http_error(err: HarnessError) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(err.code, 500), detail={"code": err.code, "message": err.message})


def _ndjson(events: Iterator[dict]) -> Iterator[str]:
    for event in events:
        yield json.dumps(event, ensure_ascii=False) + "\n"


@router.post("/ask")
def ask(body: AskBody) -> StreamingResponse:
    try:
        question = clean_question(body.text, get_settings().harness_max_text_chars)
        run = runner().start(question, body.sensor)
    except HarnessError as err:
        raise _http_error(err) from err
    return StreamingResponse(
        _ndjson(run.events()),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}")
def run_payload(run_id: str) -> dict:
    try:
        path = run_dir(get_settings().harness_output_dir, run_id) / PAYLOAD_FILE
    except HarnessError as err:
        raise _http_error(err) from err
    if not path.is_file():
        raise _http_error(HarnessError("run_not_found", "La corrida aún no tiene resultado."))
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/runs/{run_id}/files/{relative:path}")
def run_file(run_id: str, relative: str) -> FileResponse:
    try:
        path, media_type = servable_file(get_settings().harness_output_dir, run_id, relative)
    except HarnessError as err:
        raise _http_error(err) from err
    return FileResponse(path, media_type=media_type)
