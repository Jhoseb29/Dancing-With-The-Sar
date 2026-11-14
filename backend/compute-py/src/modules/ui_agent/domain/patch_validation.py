"""Valida los parches del agente contra el contrato compartido (scene-patch.schema.json)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator


class PatchValidator:
    def __init__(self, schemas_dir: Path) -> None:
        schema = json.loads((schemas_dir / "scene-patch.schema.json").read_text(encoding="utf-8"))
        self._validator = Draft7Validator(schema)

    def error(self, base_version: int, ops: list[dict[str, Any]]) -> str | None:
        patch = {"origin": "agent", "baseVersion": base_version, "ops": ops}
        first = next(iter(self._validator.iter_errors(patch)), None)
        if first is None:
            return None
        where = "/".join(str(p) for p in first.absolute_path)
        return f"Parche inválido en /{where}: {first.message}"
