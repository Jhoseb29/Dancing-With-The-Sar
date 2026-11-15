"""Alert feed: reads the alert-harness output, validates each alert against alert.schema.json,
and yields new alerts in order. Invalid files are skipped (and logged), never pushed to the UI."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

log = logging.getLogger(__name__)


@lru_cache
def _validator(schema_dir: Path) -> Draft202012Validator:
    resources = []
    for path in schema_dir.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        res = Resource.from_contents(schema)
        resources += [(schema["$id"], res), (path.name, res)]
    alert_schema = json.loads((schema_dir / "alert.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(alert_schema, registry=Registry().with_resources(resources))


class AlertFeed:
    def __init__(self, alerts_dir: Path, schema_dir: Path) -> None:
        self._dir = alerts_dir
        self._schema_dir = schema_dir

    def _files(self) -> list[Path]:
        return sorted(self._dir.glob("*.json")) if self._dir.is_dir() else []

    def _load(self, path: Path) -> dict[str, Any] | None:
        try:
            alert = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Alerta ilegible %s: %s", path.name, exc)
            return None
        problems = [e.message for e in _validator(self._schema_dir).iter_errors(alert)]
        if problems:
            log.warning("Alerta %s no cumple alert.schema.json: %s", path.name, problems[:2])
            return None
        return alert

    def latest(self, limit: int) -> tuple[list[dict[str, Any]], str | None]:
        """Newest `limit` valid alerts (oldest first) and the cursor (last file name)."""
        files = self._files()
        alerts = [a for a in (self._load(p) for p in files[-limit:]) if a]
        return alerts, files[-1].name if files else None

    def since(self, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        """Alerts written after `cursor` (file names sort by creation time)."""
        files = [p for p in self._files() if cursor is None or p.name > cursor]
        alerts = [a for a in (self._load(p) for p in files) if a]
        return alerts, files[-1].name if files else cursor
